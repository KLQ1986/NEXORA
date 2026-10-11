"""The HTTP API (design v4.0, section 25). It holds no business logic: it validates and delegates."""
import shutil
import json
import time
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
    from nexora.core.schedule import in_window
    info = system.orch.run_info(run_id)
    stages = system.orch.stages(run_id)
    # Footage analysis that could run but is kept for the operator's chosen hours: waiting, not working.
    held = (info["pipeline_id"] == "library.understand" and not in_window(system.orch.setting("background_window", ""))
            and any(s.status.value == "ready" for s in stages) and not any(s.status.value == "running" for s in stages))
    return {
        "held": held,
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
        "angles": [{"asset_id": other, "offset": shift} for other, shift in meta.get("angles", {}).items()],
        "rating": asset.get("rating", 0), "collections": json.loads(asset.get("collections") or "[]"),
        "still": bool(probe.get("still")), "kind": asset.get("kind"), "mean_db": probe.get("mean_db"),
        "thumbnail_url": f"/media/{by_role['thumbnail'].version_id}" if "thumbnail" in by_role else f"/media/{original.version_id}" if probe.get("still") else None,
        "proxy_url": f"/media/{by_role['proxy'].version_id}" if "proxy" in by_role else None,
        "ingest": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r).startswith("library.ingest")), None),
        "understand": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.understand"), None),
    }


def create_app(system, *, web_dir: str | Path | None = None, config=None) -> FastAPI:
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

    @app.patch("/api/v1/assets/{asset_id}")
    def annotate_asset(asset_id: str, body: dict):
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        system.assets.annotate(asset_id, rating=body.get("rating"), collections=body.get("collections"))
        return asset_view(system, system.assets.asset(asset_id))

    @app.get("/api/v1/events/stream")
    async def event_stream(once: bool = False):
        """Tells an open screen that something changed, so it can refresh at once instead of waiting for its next poll."""
        import asyncio
        from fastapi.responses import StreamingResponse

        async def ticks():
            last = None
            while True:
                mark = system.orch.change_mark()
                if mark != last:
                    last = mark
                    yield f"data: {json.dumps(mark)}\n\n"
                    if once:
                        return
                await asyncio.sleep(0.7)
        return StreamingResponse(ticks(), media_type="text/event-stream", headers={"cache-control": "no-cache"})

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

    @app.get("/api/v1/runs/{run_id}/detail")
    def run_detail(run_id: str):
        """Everything that happened in a run: each attempt with how long it took and how it ended, and the events in order."""
        if system.orch.run_info(run_id) is None:
            raise HTTPException(404, "no such run")
        keys = {s.stage_id: s.stage_key for s in system.orch.stages(run_id)}
        attempts = []
        for stage in system.orch.stages(run_id):
            for row in system.orch.attempt_rows(stage.stage_id):
                attempts.append({"stage_key": stage.stage_key, "number": row["number"], "outcome": row["outcome"], "worker": row["worker_id"],
                                 "started_at": row["started_at"], "seconds": round(row["ended_at"] - row["started_at"], 2) if row["ended_at"] else None,
                                 "error_code": row["error_code"], "error_message": row["error_message"]})
        events = [{"at": e.occurred_at, "kind": e.kind, "stage_key": keys.get(e.stage_id), "actor": e.actor, "payload": e.payload} for e in system.orch.events(run_id)]
        return {**run_view(system, run_id), "attempts": sorted(attempts, key=lambda a: a["started_at"]), "events": events}

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        if system.orch.run_info(run_id) is None:
            raise HTTPException(404, "no such run")
        system.orch.cancel_run(run_id)
        return run_view(system, run_id)

    def renders_in_use() -> set[str]:
        return {r["path"] for p in system.projects.projects() for r in system.projects.renders(p["project_id"])}

    @app.get("/api/v1/storage")
    def storage_usage():
        from nexora.core import backup, storage
        return {"stores": storage.usage(system.data_dir / "media", renders_in_use=renders_in_use()), "backups": backup.backups(system.data_dir / "backups"),
                "volumes": system.assets.volumes()}

    @app.post("/api/v1/storage/clean")
    def storage_clean(body: dict):
        from nexora.core import storage
        try:
            return {"freed_bytes": storage.clean(system.data_dir / "media", list(body.get("keys", [])), renders_in_use=renders_in_use())}
        except ValueError as err:
            raise HTTPException(422, str(err))

    @app.post("/api/v1/storage/backup")
    def storage_backup():
        from nexora.core import backup
        made = backup.backup(system.data_dir / "nexora.db", system.data_dir / "backups", keep=config.backups_kept if config else 7)
        return {"name": made.name, "size": made.stat().st_size}

    @app.post("/api/v1/volumes/{volume_id}/relink")
    def relink_volume(volume_id: str, body: dict):
        mount = Path(str(body.get("mount", ""))).expanduser()
        if not mount.is_dir():
            raise HTTPException(404, "Không tìm thấy thư mục này")
        system.assets.relink_volume(volume_id, mount)
        return {"volumes": system.assets.volumes()}

    checked = {"at": 0.0, "checks": []}

    def health() -> list[dict]:
        """The system check starts other programs, so its answer is kept for half a minute instead of being asked on every poll."""
        from nexora.app import doctor
        if time.time() - checked["at"] > 30:
            checked.update(at=time.time(), checks=doctor(system, config))
        return checked["checks"]

    @app.get("/api/v1/doctor")
    def run_doctor():
        return {"checks": health()}

    @app.post("/api/v1/stages/{stage_id}/resume")
    def resume_stage(stage_id: str):
        try:
            system.orch.resume(stage_id)
        except (ValueError, TypeError) as err:
            raise HTTPException(409, str(err))
        return {"ok": True}

    @app.get("/api/v1/control")
    def control():
        from nexora.core.schedule import in_window
        window = system.orch.setting("background_window", "")
        return {"kill_switch": system.orch.kill_switch(), "desktop_notifications": system.orch.setting("desktop_notifications", "1") == "1",
                "background_window": window, "background_running_now": in_window(window)}

    @app.post("/api/v1/control/background-window")
    def background_window(body: dict):
        from nexora.core.schedule import parse_window
        spec = str(body.get("window") or "")
        try:
            parse_window(spec)
        except ValueError:
            raise HTTPException(422, "Giờ bắt đầu và kết thúc phải là hai số khác nhau từ 0 đến 23")
        system.orch.set_setting("background_window", spec)
        return control()

    @app.post("/api/v1/control/settings")
    def control_settings(body: dict):
        """Budgets for the day and month, which notifications reach the desktop, and the hours it stays silent."""
        from nexora.core.schedule import parse_window
        for key in ("budget_day", "budget_month"):
            if key in body:
                value = body[key]
                if value not in (None, "") and float(value) < 0:
                    raise HTTPException(422, "Ngân sách không thể là số âm")
                system.orch.set_setting(key, "" if value in (None, "") else str(float(value)))
        if "quiet_hours" in body:
            try:
                parse_window(str(body["quiet_hours"] or ""))
            except ValueError:
                raise HTTPException(422, "Giờ bắt đầu và kết thúc phải là hai số khác nhau từ 0 đến 23")
            system.orch.set_setting("quiet_hours", str(body["quiet_hours"] or ""))
        if "notify_off" in body:
            system.orch.set_setting("notify_off", json.dumps([k for k in body["notify_off"] if k in ("waiting_review", "blocked", "failed", "succeeded")]))
        return settings_view()

    def settings_view() -> dict:
        number = lambda key: float(v) if (v := system.orch.setting(key, "")) not in (None, "") else None
        return {"budget_day": number("budget_day"), "budget_month": number("budget_month"), "quiet_hours": system.orch.setting("quiet_hours", ""),
                "notify_off": json.loads(system.orch.setting("notify_off", "[]"))}

    def period_starts() -> tuple[float, float]:
        t = time.localtime()
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)), time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))

    @app.get("/api/v1/usage")
    def usage():
        """The Costs screen: money against budgets, and what every tool and model has been doing."""
        day, month = period_starts()
        projects = []
        for p in system.projects.projects():
            spent = system.generation.spent(p["project_id"])
            if spent or p.get("budget_cap") is not None:
                projects.append({"project_id": p["project_id"], "title": p["title"], "spent": spent, "budget_cap": p.get("budget_cap")})
        return {**settings_view(), "spent_today": system.orch.spent_since(day), "spent_month": system.orch.spent_since(month), "spent_total": system.orch.spent_since(0),
                "by_day": system.orch.spend_by_day(), "projects": projects,
                "tools_today": system.orch.usage(since=day), "tools_all": system.orch.usage()}

    @app.get("/api/v1/capabilities")
    def capability_matrix():
        from nexora.app import capabilities
        return {"pipelines": capabilities(system)}

    @app.get("/api/v1/home")
    def home():
        """What needs the operator, what is running, and where things stand."""
        from nexora.app import capabilities
        titles = {}
        for p in system.projects.projects():
            for sid in system.projects.script_ids(p["project_id"]):
                titles[sid] = p
        asset_names = {}
        attention, running, seen = [], [], set()
        for run_id in sorted(system.orch.runs(), key=lambda r: system.orch.run_info(r)["created_at"], reverse=True):
            view = run_view(system, run_id)
            subject = view["subject_ref"] or ""
            if (subject, view["pipeline"]) in seen:
                continue                                  # only the newest run of a piece of work speaks for it
            seen.add((subject, view["pipeline"]))
            project = titles.get(subject)
            if subject and subject not in asset_names and not project and system.assets.asset(subject):
                asset_names[subject] = system.assets.path_of(system.assets.original(subject)).name
            name = project["title"] if project else asset_names.get(subject, subject)
            link = f"/du-an/{project['project_id']}" if project else "/tien-trinh"
            item = {"run_id": run_id, "pipeline": view["pipeline"], "name": name, "link": link, "status": view["status"], "held": view["held"]}
            if view["status"] in ("waiting_review", "blocked", "failed"):
                stage = next((s for s in view["stages"] if s["status"] == view["status"]), None)
                if view["status"] == "failed" and project and system.projects.current_script(project["project_id"])["script_id"] != subject:
                    continue                                  # a failure of a script version that has since been replaced
                attention.append({**item, "stage_key": stage and stage["stage_key"], "reason": stage and stage["blocked_reason"]})
            elif view["status"] in ("running", "queued"):
                now = next((s for s in view["stages"] if s["status"] == "running"), None)
                running.append({**item, "stage_key": now and now["stage_key"], "stages": view["stages"]})
        gaps = []
        for p in system.projects.projects():
            script = system.projects.current_script(p["project_id"])
            missing = sum(1 for s in system.projects.selections(script["script_id"]) if s.status == "gap") if script else 0
            reviewing = any(a["link"] == f"/du-an/{p['project_id']}" for a in attention)     # the review already brings the operator there
            for a in attention:
                if a["link"] == f"/du-an/{p['project_id']}" and a["pipeline"] == "sourcing.match":
                    a["gaps"] = missing                      # said once, on the line that already takes the operator there
            if missing and not reviewing and not system.projects.renders(p["project_id"]):
                gaps.append({"project_id": p["project_id"], "title": p["title"], "gaps": missing})
        assets = system.assets.assets()
        seconds = sum((system.assets.original(a["asset_id"]).metadata.get("probe", {}).get("duration") or 0) for a in assets if a["kind"] == "video")
        usage_disk = shutil.disk_usage(system.data_dir)
        day, _ = period_starts()
        recent = [{"project_id": p["project_id"], "title": p["title"], "created_at": p["created_at"], "renders": len(system.projects.renders(p["project_id"]))}
                  for p in system.projects.projects()[:5]]
        return {"attention": attention, "running": running, "gaps": gaps,
                "offline_volumes": [v for v in system.assets.volumes() if not v["online"]],
                "problems": [c for c in health() if not c["ok"] and not c["optional"]],
                "unavailable": [c for c in capabilities(system) if not c["available"]],
                "agent": [t for t in system.producer.tasks() if t["status"] in ("working", "waiting_operator")],
                "counts": {"videos": sum(1 for a in assets if a["kind"] == "video"), "photos": sum(1 for a in assets if a["kind"] == "image"),
                           "music": sum(1 for a in assets if a["kind"] == "audio"), "footage_seconds": seconds, "projects": len(system.projects.projects()),
                           "moments": system.index.count()},
                "disk": {"free_bytes": usage_disk.free, "total_bytes": usage_disk.total}, "spent_today": system.orch.spent_since(day),
                "kill_switch": system.orch.kill_switch(), "recent": recent}

    @app.get("/api/v1/agent/tasks")
    def agent_tasks(project_id: str | None = None):
        return {"tasks": system.producer.tasks(project_id=project_id)}

    @app.post("/api/v1/agent/tasks", status_code=201)
    def start_agent_task(body: dict):
        goal = str(body.get("goal", "")).strip()
        if not goal:
            raise HTTPException(422, "Hãy mô tả video bạn muốn làm")
        task_id = system.producer.start(goal, format=body.get("format") if body.get("format") in ("landscape", "portrait", "square") else "landscape",
                                        lines=max(2, min(12, int(body.get("lines", 5)))), use_stock=bool(body.get("use_stock", True)))
        return system.producer.task(task_id)

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
                                     "inserts": sel.extras.get("inserts", []), "focus_x": (sel.extras.get("focus") or {}).get("x") if (sel.extras.get("focus") or {}).get("asset_id") == sel.asset_id else None,
                                     "angles": angles_of(sel),
                                     "alternates": [{**a, "frame_url": f"/api/v1/moments/{a['moment_id']}/frame", "asset": asset_brief(a["asset_id"])} for a in sel.alternates]}
            shots.append(item)
        renders = [{"render_id": r["render_id"], "script_id": r["script_id"], "created_at": r["created_at"], "qc": r["qc"], "review": r["review"],
                    "url": f"/api/v1/renders/{r['render_id']}/file", "package": system.distribution.package(r["render_id"])}
                   for r in system.projects.renders(project["project_id"])]
        return {**project, "script": {"script_id": script["script_id"], "version": script["version"], "match_approved": script["match_approved"]} if script else None,
                "shots": shots, "match": latest_run(script["script_id"], "sourcing.match") if script else None,
                "render": latest_run(script["script_id"], "edit.render") if script else None, "renders": renders,
                "generate": latest_run(script["script_id"], "sourcing.generate") if script else None, "generators": system.generation.available(),
                "auto_accept": bool(project.get("auto_accept")), "own_takes": own_takes(project, len(shots)),
                "spent": system.generation.spent(project["project_id"])}

    def angles_of(sel) -> list[dict]:
        """Other cameras that recorded the instant this selection shows."""
        if not sel.asset_id or sel.t_in is None or sel.status == "gap":
            return []
        out = []
        for other, shift in system.assets.original(sel.asset_id).metadata.get("angles", {}).items():
            brief = asset_brief(other)
            if 0 <= sel.t_in + shift < (brief["duration"] or 0):
                out.append({**brief, "offset": shift, "t_in": round(sel.t_in + shift, 2)})
        return out

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

    @app.post("/api/v1/assets/sync")
    def sync_assets(body: dict):
        try:
            return system.library.sync(str(body["a"]), str(body["b"]))
        except ValueError as err:
            raise HTTPException(409, {"no_audio": "Một trong hai clip không có âm thanh nên không đồng bộ theo tiếng được.",
                                      "too_short": "Clip quá ngắn để đồng bộ.",
                                      "not_alike": "Âm thanh của hai clip không giống nhau. Có thể chúng không quay cùng một lúc."}.get(str(err), str(err)))

    @app.post("/api/v1/shots/{shot_id}/angle")
    def use_angle(shot_id: str, body: dict):
        angle = next((a for a in angles_of(system.projects.selection(shot_id)) if a["asset_id"] == body.get("asset_id")), None)
        if angle is None:
            raise HTTPException(404, "Clip này chưa được đồng bộ với cảnh đang chọn")
        system.sourcing.use_angle(shot_id, angle["asset_id"], angle["offset"])
        return {"ok": True}

    @app.post("/api/v1/shots/{shot_id}/inserts")
    def add_insert(shot_id: str, body: dict):
        try:
            return system.sourcing.add_insert(shot_id, str(body.get("keyword", "")))
        except ValueError as err:
            raise HTTPException(422, str(err))
        except LookupError:
            raise HTTPException(404, "Không tìm thấy cảnh nào trong kho khớp với từ này")

    @app.post("/api/v1/shots/{shot_id}/inserts/remove")
    def remove_insert(shot_id: str, body: dict):
        system.sourcing.remove_insert(shot_id, str(body.get("keyword", "")))
        return {"ok": True}

    @app.post("/api/v1/shots/{shot_id}/focus")
    def set_focus(shot_id: str, body: dict):
        system.sourcing.set_focus(shot_id, body.get("x"))
        return {"ok": True}

    @app.post("/api/v1/projects/{project_id}/reorder")
    def reorder(project_id: str, body: dict):
        try:
            system.projects.reorder(current_script_id(project_id), [str(s) for s in body.get("shot_ids", [])])
        except ValueError:
            raise HTTPException(422, "Thứ tự mới phải gồm đủ mọi câu của kịch bản")
        return project_view(need_project(project_id))

    @app.get("/api/v1/renders/{render_id}/edl")
    def render_edl(render_id: str):
        if system.projects.render(render_id) is None:
            raise HTTPException(404, "no such render")
        return FileResponse(system.distribution.export_edl(render_id), filename="cut.edl", media_type="text/plain")

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
        latest = system.projects.renders(project_id)
        if latest:                                   # the decision and its reason stay with the render they were about
            system.projects.set_render_review(latest[0]["render_id"], approved=bool(body.get("approve")), comment=str(body.get("comment") or "").strip() or None)
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
        out, names = [], {}
        for p in system.projects.projects():
            for sid in system.projects.script_ids(p["project_id"]):
                names[sid] = (p["title"], f"/du-an/{p['project_id']}")
        for n in system.orch.notifications():
            info = system.orch.run_info(n["run_id"]) or {}
            subject = info.get("subject_ref") or ""
            if subject not in names and subject.startswith("ast_") and system.assets.asset(subject):
                names[subject] = (system.assets.path_of(system.assets.original(subject)).name, "/thu-vien")
            name, link = names.get(subject, (None, None))
            out.append({**n, "pipeline": info.get("pipeline_id"), "subject_ref": subject, "subject_name": name, "link": link})
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
