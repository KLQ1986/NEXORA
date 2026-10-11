"""The HTTP API (design v4.0, section 25). It holds no business logic: it validates and delegates."""
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".ogv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = ("wav", "m4a", "mp3", "aiff")
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".aiff", ".flac"}


class RegisterRequest(BaseModel):
    path: str


def run_view(system, run_id: str) -> dict:
    info = system.orch.run_info(run_id)
    return {
        "run_id": run_id,
        "pipeline": info["pipeline_id"],
        "subject_ref": info["subject_ref"],
        "created_at": info["created_at"],
        "status": system.orch.run_status(run_id).value,
        "cost": system.orch.run_cost(run_id),
        "stages": [{"stage_id": s.stage_id, "stage_key": s.stage_key, "status": s.status.value, "blocked_reason": s.blocked_reason,
                    "attempts": len(system.orch.attempts(s.stage_id)), "outputs": s.outputs}
                   for s in system.orch.stages(run_id)],
    }


def asset_view(system, asset: dict) -> dict:
    versions = system.assets.versions(asset["asset_id"])
    by_role = {v.role: v for v in versions}
    original = by_role["original"]
    meta, probe = original.metadata, original.metadata.get("probe", {})
    path = system.assets.path_of(original)
    runs = system.orch.runs_for_subject(asset["asset_id"])
    return {
        "asset_id": asset["asset_id"], "name": path.name, "path": str(path), "origin": asset["origin"],
        "privacy_class": asset["privacy_class"], "created_at": asset["created_at"], "online": path.is_file(),
        "size": original.size, "checksum": original.checksum, "duplicate_of": meta.get("duplicate_of"),
        "duration": probe.get("duration"), "width": probe.get("width"), "height": probe.get("height"),
        "frame_rate": probe.get("frame_rate"), "has_audio": probe.get("has_audio"),
        "usable_ranges": meta.get("usable_ranges", []), "black_ranges": meta.get("black_ranges", []),
        "frozen_ranges": meta.get("frozen_ranges", []),
        "still": bool(probe.get("still")), "kind": asset.get("kind"), "mean_db": probe.get("mean_db"),
        "thumbnail_url": f"/media/{by_role['thumbnail'].version_id}" if "thumbnail" in by_role else f"/media/{original.version_id}" if probe.get("still") else None,
        "proxy_url": f"/media/{by_role['proxy'].version_id}" if "proxy" in by_role else None,
        "ingest": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.ingest"), None),
        "understand": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.understand"), None),
    }


def create_app(system, *, web_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="NEXORA", version="0.1.0")

    @app.post("/api/v1/assets/register", status_code=202)
    def register_asset(body: RegisterRequest):
        root = Path(body.path).expanduser()
        if root.is_dir():
            files = sorted(f for f in root.rglob("*") if f.suffix.lower() in VIDEO_EXT | IMAGE_EXT | MUSIC_EXT and not f.name.startswith("."))
        elif root.is_file():
            files = [root]
        else:
            raise HTTPException(404, f"Không tìm thấy đường dẫn: {body.path}")
        registered = [dict(zip(("asset_id", "run_id"), system.library.ingest(f)), name=f.name) for f in files]
        first = registered[0] if registered else {}
        return {"registered": registered, "asset_id": first.get("asset_id"), "run_id": first.get("run_id")}

    @app.get("/api/v1/assets")
    def list_assets():
        out = []
        for asset in system.assets.assets():
            versions = system.assets.versions(asset["asset_id"])
            original = next(v for v in versions if v.role == "original")
            out.append({**asset, "roles": [v.role for v in versions], "path": str(system.assets.path_of(original)),
                        "checksum": original.checksum, "metadata": original.metadata})
        return out

    @app.get("/api/v1/library")
    def library():
        return {"assets": [asset_view(system, a) for a in system.assets.assets()]}

    @app.get("/api/v1/runs")
    def list_runs():
        return [run_view(system, run_id) for run_id in system.orch.runs()]

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        if system.orch.run_info(run_id) is None:
            raise HTTPException(404, f"no such run: {run_id}")
        return run_view(system, run_id)

    @app.post("/api/v1/stages/{stage_id}/resume")
    def resume_stage(stage_id: str):
        try:
            system.orch.resume(stage_id)
        except (ValueError, TypeError) as err:
            raise HTTPException(409, str(err))
        return {"ok": True}

    @app.get("/api/v1/control")
    def control():
        return {"kill_switch": system.orch.kill_switch(), "desktop_notifications": system.orch.setting("desktop_notifications", "1") == "1"}

    @app.post("/api/v1/control/desktop-notifications")
    def desktop_notifications(body: dict):
        system.orch.set_setting("desktop_notifications", "1" if body.get("on") else "0")
        return control()

    @app.post("/api/v1/control/kill-switch")
    def kill_switch(body: dict):
        system.orch.set_kill_switch(bool(body.get("on")))
        return {"kill_switch": system.orch.kill_switch()}

    @app.get("/api/v1/environment")
    def environment():
        from nexora.core.environment import report
        usage = shutil.disk_usage(system.data_dir)
        return {**report(system.adapters), "disk": {"free_bytes": usage.free, "total_bytes": usage.total}}

    @app.get("/media/{version_id}")
    def media(version_id: str):
        version = system.assets.version(version_id)
        if version is None:
            raise HTTPException(404, "no such media")
        path = system.assets.path_of(version)
        if not path.is_file():
            raise HTTPException(404, "the volume holding this file is offline")
        return FileResponse(path)

    # ------------------------------------------------------------------ understanding and search
    def moment_view(m, score=None) -> dict:
        return {"moment_id": m.moment_id, "asset_id": m.asset_id, "level": m.level, "t_start": m.t_start, "t_end": m.t_end, "text": m.text,
                "source": m.source, "score": score, "frame_url": f"/api/v1/moments/{m.moment_id}/frame" if m.data.get("frame") else None}

    def asset_brief(asset_id: str) -> dict:
        versions = {v.role: v for v in system.assets.versions(asset_id)}
        original = versions["original"]
        return {"asset_id": asset_id, "name": system.assets.path_of(original).name,
                "proxy_url": f"/media/{versions['proxy'].version_id}" if "proxy" in versions else None,
                "duration": original.metadata.get("probe", {}).get("duration"), "still": bool(original.metadata.get("probe", {}).get("still")),
                "thumbnail_url": f"/media/{versions['thumbnail'].version_id}" if "thumbnail" in versions
                else f"/media/{original.version_id}" if original.metadata.get("probe", {}).get("still") else None}

    @app.get("/api/v1/library/search")
    def search(q: str, limit: int = 24):
        hits = system.index.search(q, limit=limit, min_score=0.3)
        return {"hits": [{**moment_view(h.moment, h.score), "asset": asset_brief(h.moment.asset_id)} for h in hits]}

    @app.get("/api/v1/assets/{asset_id}/moments")
    def asset_moments(asset_id: str):
        moments = system.index.moments(asset_id)
        return {"video": next((moment_view(m) | {"title": m.data.get("detail", {}).get("tieu_de")} for m in moments if m.level == "video"), None),
                "segments": [moment_view(m) for m in moments if m.level == "segment"]}

    @app.patch("/api/v1/moments/{moment_id}")
    def correct_moment(moment_id: str, body: dict):
        if system.index.by_id(moment_id) is None or not str(body.get("text", "")).strip():
            raise HTTPException(404, "no such moment, or empty text")
        system.index.correct(moment_id, str(body["text"]).strip())
        return moment_view(system.index.by_id(moment_id))

    @app.get("/api/v1/moments/{moment_id}/frame")
    def moment_frame(moment_id: str):
        m = system.index.by_id(moment_id)
        if m is None or not m.data.get("frame") or not Path(m.data["frame"]).is_file():
            raise HTTPException(404, "no frame")
        return FileResponse(m.data["frame"])

    # ------------------------------------------------------------------ projects, matching, render
    def latest_run(subject: str, pipeline: str):
        return next((run_view(system, r) for r in system.orch.runs_for_subject(subject) if system.orch.pipeline_of(r) == pipeline), None)

    def project_view(project: dict) -> dict:
        script = system.projects.current_script(project["project_id"])
        shots = []
        for shot in (script["shots"] if script else []):
            sel = system.projects.selection(shot.shot_id)
            item = {"shot_id": shot.shot_id, "position": shot.position, "text": shot.text, "selection": None, "keyframe_url": None, "generation": None}
            keys = system.projects.generations(shot.shot_id, kind="keyframe")
            if keys:
                item["keyframe_url"] = f"/media/{system.assets.original(keys[-1]['asset_id']).version_id}"
                item["generation"] = {"prompt": keys[-1]["prompt"], "seed": keys[-1]["seed"], "provider": keys[-1]["provider"]}
            if sel:
                item["selection"] = {"status": sel.status, "t_in": sel.t_in, "t_out": sel.t_out, "score": sel.score, "reason": sel.reason,
                                     "decided_by": sel.decided_by, "moment_id": sel.moment_id,
                                     "frame_url": f"/api/v1/moments/{sel.moment_id}/frame" if sel.moment_id else None,
                                     "asset": asset_brief(sel.asset_id) if sel.asset_id else None,
                                     "alternates": [{**a, "frame_url": f"/api/v1/moments/{a['moment_id']}/frame", "asset": asset_brief(a["asset_id"])} for a in sel.alternates]}
            shots.append(item)
        renders = [{"render_id": r["render_id"], "script_id": r["script_id"], "created_at": r["created_at"], "qc": r["qc"],
                    "url": f"/api/v1/renders/{r['render_id']}/file", "package": system.distribution.package(r["render_id"])}
                   for r in system.projects.renders(project["project_id"])]
        return {**project, "script": {"script_id": script["script_id"], "version": script["version"], "match_approved": script["match_approved"]} if script else None,
                "shots": shots, "match": latest_run(script["script_id"], "sourcing.match") if script else None,
                "render": latest_run(script["script_id"], "edit.render") if script else None, "renders": renders,
                "generate": latest_run(script["script_id"], "sourcing.generate") if script else None, "generators": system.generation.available(),
                "auto_accept": bool(project.get("auto_accept")), "own_takes": own_takes(project, len(shots))}

    def own_takes(project: dict, lines: int) -> list[int]:
        """The line numbers for which the operator has put a recording in the narration folder (1.wav, 2.m4a, ...)."""
        folder = Path(project.get("narration_dir") or "/nonexistent")
        return [n for n in range(1, lines + 1) if any((folder / f"{n}.{ext}").is_file() for ext in AUDIO_EXT)]

    def need_project(project_id: str) -> dict:
        project = system.projects.project(project_id)
        if project is None:
            raise HTTPException(404, "Không tìm thấy dự án")
        return project

    def current_script_id(project_id: str) -> str:
        script = system.projects.current_script(need_project(project_id)["project_id"])
        if script is None:
            raise HTTPException(409, "Dự án chưa có kịch bản")
        return script["script_id"]

    @app.get("/api/v1/projects")
    def list_projects():
        return [project_view(p) for p in system.projects.projects()]

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: dict):
        title = str(body.get("title", "")).strip()
        if not title:
            raise HTTPException(422, "Dự án cần có tên")
        project_id = system.planning.create_project(title, format=body.get("format") if body.get("format") in ("landscape", "portrait", "square") else "landscape")
        if body.get("lines"):
            system.planning.save_script(project_id, list(body["lines"]))
        return project_view(system.projects.project(project_id))

    @app.get("/api/v1/projects/{project_id}")
    def get_project(project_id: str):
        return project_view(need_project(project_id))

    @app.put("/api/v1/projects/{project_id}/script")
    def save_script(project_id: str, body: dict):
        need_project(project_id)
        lines = [str(line).strip() for line in body.get("lines", []) if str(line).strip()]
        if not lines:
            raise HTTPException(422, "Kịch bản cần ít nhất một câu")
        system.planning.save_script(project_id, lines)
        return project_view(system.projects.project(project_id))

    @app.post("/api/v1/projects/{project_id}/draft")
    def draft_script(project_id: str, body: dict):
        need_project(project_id)
        try:
            return {"lines": system.planning.draft_script(str(body.get("topic", "")), lines=int(body.get("lines", 6)))}
        except Exception as err:
            raise HTTPException(503, f"Không viết nháp được: {err}")

    @app.post("/api/v1/projects/{project_id}/match", status_code=202)
    def start_match(project_id: str):
        return {"run_id": system.sourcing.start_match(current_script_id(project_id))}

    @app.post("/api/v1/projects/{project_id}/generate", status_code=202)
    def start_generate(project_id: str):
        return {"run_id": system.generation.start(current_script_id(project_id))}

    @app.post("/api/v1/projects/{project_id}/generate/approve")
    def approve_generate(project_id: str):
        run = latest_run(current_script_id(project_id), "sourcing.generate")
        if run is None or run["status"] != "waiting_review":
            raise HTTPException(409, "Chưa có gì đang chờ duyệt")
        system.generation.approve(run["run_id"])
        return project_view(need_project(project_id))

    @app.post("/api/v1/projects/{project_id}/match/approve")
    def approve_match(project_id: str):
        run = latest_run(current_script_id(project_id), "sourcing.match")
        if run is None or run["status"] != "waiting_review":
            raise HTTPException(409, "Chưa có lựa chọn nào đang chờ duyệt")
        system.sourcing.approve(run["run_id"])
        return project_view(need_project(project_id))

    @app.post("/api/v1/shots/{shot_id}/swap")
    def swap(shot_id: str, body: dict):
        try:
            system.sourcing.swap(shot_id, int(body.get("alternate", 0)))
        except (IndexError, AttributeError):
            raise HTTPException(409, "Không có phương án dự phòng này")
        return {"ok": True}

    @app.post("/api/v1/shots/{shot_id}/gap")
    def gap(shot_id: str):
        system.sourcing.mark_gap(shot_id)
        return {"ok": True}

    @app.post("/api/v1/shots/{shot_id}/stock")
    def stock(shot_id: str, body: dict):
        from nexora.app import fill_gap_from_stock
        from nexora.core.adapter import AdapterError
        query = str(body.get("query", "")).strip()
        if not query:
            raise HTTPException(422, "Cần từ khoá để tìm clip stock")
        try:
            return fill_gap_from_stock(system, shot_id, query)
        except AdapterError as err:
            raise HTTPException(503, f"Không tìm được clip stock: {err.message}")

    @app.post("/api/v1/shots/{shot_id}/trim")
    def trim(shot_id: str, body: dict):
        system.sourcing.trim(shot_id, float(body["t_in"]), float(body["t_out"]))
        return {"ok": True}

    @app.post("/api/v1/projects/{project_id}/render", status_code=202)
    def start_render(project_id: str):
        try:
            return {"run_id": system.edit.start_render(current_script_id(project_id))}
        except ValueError:
            raise HTTPException(409, "Hãy duyệt các clip đã chọn trước khi dựng video")

    @app.post("/api/v1/projects/{project_id}/render/decision")
    def decide_render(project_id: str, body: dict):
        run = latest_run(current_script_id(project_id), "edit.render")
        if run is None or run["status"] != "waiting_review":
            raise HTTPException(409, "Chưa có bản dựng nào đang chờ duyệt")
        stage = next(s for s in run["stages"] if s["status"] == "waiting_review")
        system.orch.decide_review(stage["stage_id"], approve=bool(body.get("approve")))
        return project_view(need_project(project_id))

    @app.patch("/api/v1/projects/{project_id}")
    def update_project(project_id: str, body: dict):
        need_project(project_id)
        if body.get("music_path") and not Path(str(body["music_path"])).expanduser().is_file():
            raise HTTPException(404, "Không tìm thấy file nhạc ở đường dẫn này")
        if body.get("narration_dir") and not Path(str(body["narration_dir"])).expanduser().is_dir():
            raise HTTPException(404, "Không tìm thấy thư mục này")
        fields = {k: (str(Path(str(v)).expanduser()) if k in ("music_path", "narration_dir") and v else v) for k, v in body.items()}
        system.projects.update_project(project_id, **fields)
        return project_view(need_project(project_id))

    @app.get("/api/v1/projects/{project_id}/board")
    def board(project_id: str):
        """Everything the Board shows that the project view does not: the activity of its runs, in time order."""
        script = system.projects.current_script(need_project(project_id)["project_id"])
        events = []
        for run_id in (system.orch.runs_for_subject(script["script_id"]) if script else []):
            keys = {s.stage_id: s.stage_key for s in system.orch.stages(run_id)}
            pipeline = system.orch.pipeline_of(run_id)
            for e in system.orch.events(run_id):
                events.append({"at": e.occurred_at, "kind": e.kind, "pipeline": pipeline, "stage_key": keys.get(e.stage_id), "actor": e.actor, "payload": e.payload})
        events.sort(key=lambda e: e["at"])
        cost = sum(system.orch.run_cost(r) for r in (system.orch.runs_for_subject(script["script_id"]) if script else []))
        return {"events": events, "cost": cost}

    @app.get("/api/v1/notifications")
    def notifications():
        out = []
        for n in system.orch.notifications():
            info = system.orch.run_info(n["run_id"]) or {}
            out.append({**n, "pipeline": info.get("pipeline_id"), "subject_ref": info.get("subject_ref")})
        return {"unread": sum(1 for n in out if n["read_at"] is None), "items": out}

    @app.post("/api/v1/notifications/read")
    def read_notifications():
        system.orch.mark_notifications_read()
        return {"ok": True}

    @app.post("/api/v1/renders/{render_id}/package")
    def build_package(render_id: str, body: dict | None = None):
        if system.projects.render(render_id) is None:
            raise HTTPException(404, "Không tìm thấy bản dựng")
        body = body or {}
        if body.get("thumbnail") and system.distribution.package(render_id):
            return system.distribution.choose_thumbnail(render_id, body["thumbnail"])
        return system.distribution.build_package(render_id, title=body.get("title"), description=body.get("description"))

    @app.get("/api/v1/renders/{render_id}/package")
    def get_package(render_id: str):
        package = system.distribution.package(render_id)
        if package is None:
            raise HTTPException(404, "Chưa có gói xuất bản")
        return package

    @app.get("/api/v1/renders/{render_id}/package/{name}")
    def package_file(render_id: str, name: str):
        package = system.distribution.package(render_id)
        if package is None or name not in (package["thumbnails"] + [package["video"], package["captions"]]):
            raise HTTPException(404, "Không có file này trong gói")
        return FileResponse(Path(package["folder"]) / name)

    @app.get("/api/v1/renders/{render_id}/file")
    def render_file(render_id: str):
        render = system.projects.render(render_id)
        if render is None or not Path(render["path"]).is_file():
            raise HTTPException(404, "Không tìm thấy bản dựng")
        return FileResponse(render["path"], media_type="video/mp4")

    if web_dir and Path(web_dir).is_dir():
        app.mount("/assets", StaticFiles(directory=Path(web_dir) / "assets"), name="web-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            return FileResponse(Path(web_dir) / "index.html")

    return app
