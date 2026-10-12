"""The HTTP API (design v4.0, section 25). It holds no business logic: it validates and delegates."""
import shutil
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nexora.core.adapter import AdapterError, ErrorCode

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
        "held": held, "stalled": system.orch.stalled(run_id),
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


TEXT_TASKS = {"write": "Viết nháp kịch bản và gợi ý ý tưởng", "critique": "Phản biện kịch bản", "revise": "Viết lại theo nhận xét", "facts": "Tìm câu nêu dữ kiện",
              "check": "Đối chiếu dữ kiện với nguồn", "titles": "Gợi ý tiêu đề", "translate": "Dịch phụ đề", "command": "Chỉnh sửa bằng lời"}


def asset_view(system, asset: dict, used: dict | None = None) -> dict:
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
        "rejected": bool(asset.get("rejected")), "speech": meta.get("speech"), "session": f"{path.parent.name}, {str(probe.get('created') or '')[:10]}".rstrip(", "),
        "used_in": [{"project_id": pid, "title": (system.projects.project(pid) or {}).get("title", "")} for pid in (used if used is not None else system.projects.used_assets()).get(asset["asset_id"], [])],
        "transcribe": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.transcribe"), None),
        "enhance": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.enhance"), None),
        "enhanced": by_role["enhanced"].metadata if "enhanced" in by_role else None,
        "note": asset.get("note"), "rating": asset.get("rating", 0), "collections": json.loads(asset.get("collections") or "[]"),
        "still": bool(probe.get("still")), "kind": asset.get("kind"), "mean_db": probe.get("mean_db"),
        "thumbnail_url": f"/media/{by_role['thumbnail'].version_id}" if "thumbnail" in by_role else f"/media/{original.version_id}" if probe.get("still") else None,
        "proxy_url": f"/media/{by_role['proxy'].version_id}" if "proxy" in by_role else None,
        "ingest": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r).startswith("library.ingest")), None),
        "understand": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.understand"), None),
    }


def create_app(system, *, web_dir: str | Path | None = None, config=None) -> FastAPI:
    app = FastAPI(title="NEXORA", version="0.1.0")

    @app.middleware("http")
    async def keep_audit(request, call_next):
        """Everything done through the interface that changes something is written down: what was asked, when, and how it ended."""
        response = await call_next(request)
        if request.method != "GET" and request.url.path.startswith("/api/") and request.url.path != "/api/v1/notifications/read":
            try:
                system.orch.audit({"at": time.time(), "method": request.method, "path": request.url.path, "status": response.status_code})
            except Exception:
                pass                                 # the record of an action must never undo the action
        return response

    @app.get("/api/v1/audit")
    def audit(limit: int = 100):
        return {"entries": system.orch.audit_log(limit=max(1, min(500, limit)))}

    @app.get("/api/v1/autonomy")
    def autonomy():
        return system.autonomy.status()

    @app.post("/api/v1/autonomy")
    def set_autonomy(body: dict):
        try:
            return system.autonomy.set_level(int(body.get("level", -1)))
        except PermissionError as err:
            raise HTTPException(409, f"Chưa đủ điều kiện lên mức này. {err}")
        except (TypeError, ValueError):
            raise HTTPException(422, "Mức tự chủ là một số từ 0 đến 4")

    @app.get("/api/v1/models/routes")
    def model_routes():
        """Which model serves which kind of text task. Tasks with pictures always stay on this machine."""
        models = [{"name": c.name, "runs": c.runs} for c in system.adapters.describe() if c.name == "model" or c.name.startswith("model.")]
        return {"models": models, "routes": json.loads(system.orch.setting("model_routes", "{}")), "tasks": TEXT_TASKS,
                "privacy_local_only": system.orch.setting("privacy_local_only", "0") == "1"}

    @app.post("/api/v1/models/routes")
    def set_model_routes(body: dict):
        known = {c.name for c in system.adapters.describe() if c.name.startswith("model.")}
        routes = {task: name for task, name in (body.get("routes") or {}).items() if task in TEXT_TASKS and name in known}
        system.orch.set_setting("model_routes", json.dumps(routes))
        return model_routes()

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
        system.library.annotate(asset_id, rating=body.get("rating"), collections=body.get("collections"), note=body.get("note"),
                                rejected=body.get("rejected") if "rejected" in body else None)
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
        used = system.projects.used_assets()
        return {"assets": [asset_view(system, a, used) for a in system.assets.assets()]}

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
        return {r["path"] for p in system.projects.projects() for r in system.projects.renders(p["project_id"])} | \
               {r["path"] for p in system.projects.projects() for r in system.projects.renders(p["project_id"], previews=True)[:1]}      # only the newest preview is worth keeping

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

    @app.post("/api/v1/stages/{stage_id}/retry")
    def retry_stage(stage_id: str):
        try:
            system.orch.retry(stage_id)
        except (ValueError, TypeError) as err:
            raise HTTPException(409, str(err))
        return {"ok": True}

    @app.get("/api/v1/moments/{moment_id}/similar")
    def similar_moments(moment_id: str):
        m = system.index.moment(moment_id)
        if m is None:
            raise HTTPException(404, "no such moment")
        hits = system.index.search(m.text, limit=9, exclude=frozenset({moment_id}))
        return {"hits": [{**moment_view(h.moment, h.score), "asset": asset_brief(h.moment.asset_id)} for h in hits[:8]]}

    @app.get("/api/v1/settings")
    def get_settings():
        """What the Settings screen shows: voices, models, privacy mode, watched folders and templates."""
        from nexora.app import templates
        env = system.adapters.environment()
        return {"voice": system.orch.setting("voice", config.voice if config else "Linh"), "voices": sorted(set((env.get("voice") or {}).get("vietnamese_voices", []))),
                "models": (env.get("model") or {}).get("models", {}), "model_roles": {"vision": config.vision_model, "judge": config.judge_model or config.vision_model,
                                                                                     "writer": config.writer_model or config.vision_model, "embed": config.embed_model} if config else {},
                "privacy_local_only": system.orch.setting("privacy_local_only", "0") == "1",
                "watch_folders": json.loads(system.orch.setting("watch_folders", "[]")), "templates": templates(system)}

    @app.post("/api/v1/settings")
    def set_settings(body: dict):
        if "voice" in body:
            system.orch.set_setting("voice", str(body["voice"]))
        if "privacy_local_only" in body:
            system.orch.set_setting("privacy_local_only", "1" if body["privacy_local_only"] else "0")
        if "watch_folders" in body:
            folders = [str(Path(str(f)).expanduser()) for f in body["watch_folders"] if str(f).strip()]
            missing = [f for f in folders if not Path(f).is_dir()]
            if missing:
                raise HTTPException(404, f"Không tìm thấy thư mục: {missing[0]}")
            system.orch.set_setting("watch_folders", json.dumps(folders, ensure_ascii=False))
        if "templates" in body:
            clean = [{"name": str(t["name"]).strip(), "format": t.get("format") if t.get("format") in ("landscape", "portrait", "square") else "landscape", "voice": str(t.get("voice") or ""),
                      "music_gain": max(0.05, min(1.0, float(t.get("music_gain") or 0.35))), "auto_accept": bool(t.get("auto_accept")),
                      "caption_scale": max(0.7, min(1.6, float(t.get("caption_scale") or 1.0))), "caption_position": t.get("caption_position") if t.get("caption_position") in ("top", "middle", "bottom") else "bottom",
                      "typeface": "serif" if t.get("typeface") == "serif" else "sans", "caption_colour": t.get("caption_colour") if isinstance(t.get("caption_colour"), list) and len(t["caption_colour"]) == 3 else None,
                      "logo_path": str(Path(str(t["logo_path"])).expanduser()) if t.get("logo_path") else "",
                      "pronounce": {str(k).strip(): str(v).strip() for k, v in (t.get("pronounce") or {}).items() if str(k).strip() and str(v).strip()}} for t in body["templates"] if str(t.get("name", "")).strip()]
            system.orch.set_setting("templates", json.dumps(clean, ensure_ascii=False))
        return get_settings()

    @app.post("/api/v1/projects/{project_id}/template")
    def apply_template(project_id: str, body: dict):
        from nexora.app import templates
        need_project(project_id)
        chosen = next((t for t in templates(system) if t["name"] == body.get("name")), None)
        if chosen is None:
            raise HTTPException(404, "Không có mẫu này")
        system.projects.update_project(project_id, template=chosen["name"], format=chosen["format"], voice=chosen["voice"] or None, music_gain=chosen["music_gain"], auto_accept=int(chosen["auto_accept"]),
                                       profile=json.dumps({"caption_scale": chosen.get("caption_scale", 1.0), "caption_position": chosen.get("caption_position", "bottom"),
                                                           "typeface": chosen.get("typeface", "sans"), "caption_colour": chosen.get("caption_colour"), "logo_path": chosen.get("logo_path") or None,
                                                           "pronounce": chosen.get("pronounce", {})}, ensure_ascii=False))
        return project_view(need_project(project_id))

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
                                        lines=max(2, min(12, int(body.get("lines", 5)))), use_stock=bool(body.get("use_stock", True)),
                                        urls=[u for u in (str(u).strip() for u in body.get("urls") or []) if u.lower().startswith(("http://", "https://"))],
                                        critique=bool(body.get("critique", True)))
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

    @app.get("/api/v1/library/sessions")
    def sessions():
        return {"sessions": system.library.sessions()}

    @app.post("/api/v1/assets/{asset_id}/understand", status_code=202)
    def understand_again(asset_id: str):
        """Describe the footage again, for example after a note was added that names what is in it."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        run_id = system.library.understand(asset_id, force=True)
        if run_id is None:
            raise HTTPException(409, "Máy này chưa có mô hình để mô tả footage, hoặc đây là bản trùng")
        return {"run_id": run_id}

    @app.post("/api/v1/assets/{asset_id}/transcribe", status_code=202)
    def transcribe(asset_id: str):
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        run_id = system.library.transcribe(asset_id, force=True)
        if run_id is None:
            raise HTTPException(409, "Footage này không có tiếng, hoặc máy chưa có công cụ nhận dạng giọng nói")
        return {"run_id": run_id}

    @app.post("/api/v1/moments/{moment_id}/deepen")
    def deepen(moment_id: str):
        """Describe one stretch frame by frame."""
        if not system.library.understands or system.index.by_id(moment_id) is None:
            raise HTTPException(404, "no such moment, or no model to look with")
        try:
            made = system.library.deepen(moment_id)
        except ValueError:
            raise HTTPException(422, "Chỉ xem kỹ được một đoạn đã mô tả")
        except AdapterError as err:
            raise HTTPException(503, f"Mô hình không trả lời: {err.message or err.code.value}")
        return {"frames": [moment_view(system.index.by_id(m)) for m in made]}

    @app.get("/api/v1/library/search")
    def search(q: str, limit: int = 24):
        # Pictures, speech and the operator's own notes are searched together; assets set aside are left out.
        hits = system.index.search(q, limit=limit, min_score=0.3, level=("segment", "speech", "note", "frame"), exclude_assets=system.assets.rejected())
        return {"hits": [{**moment_view(h.moment, h.score), "asset": asset_brief(h.moment.asset_id)} for h in hits]}

    @app.get("/api/v1/assets/{asset_id}/moments")
    def asset_moments(asset_id: str):
        moments = system.index.moments(asset_id)
        return {"video": next((moment_view(m) | {"title": m.data.get("detail", {}).get("tieu_de")} for m in moments if m.level == "video"), None),
                "segments": [moment_view(m) for m in moments if m.level == "segment"],
                "frames": [moment_view(m) for m in moments if m.level == "frame"],
                "speech": [moment_view(m) | {"words": m.data.get("words", [])} for m in moments if m.level == "speech"]}

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
            item = {"shot_id": shot.shot_id, "position": shot.position, "text": shot.text, "scene": shot.scene, "brief": shot.brief, "screen_text": shot.screen_text, "target_seconds": shot.target_seconds, "sound_cue": shot.sound_cue,
                    "is_fact": shot.is_fact, "source": shot.source, "fact_check": shot.fact_check, "gen": shot.gen, "selection": None, "keyframe_url": None, "generation": None}
            keys = system.projects.generations(shot.shot_id, kind="keyframe")
            if keys:
                item["keyframe_url"] = f"/media/{system.assets.original(keys[-1]['asset_id']).version_id}"
                item["generation"] = {"prompt": keys[-1]["prompt"], "seed": keys[-1]["seed"], "provider": keys[-1]["provider"], "quality": keys[-1]["quality"],
                                      "spec": keys[-1]["spec"], "tries": len(system.projects.generations(shot.shot_id, kind="keyframe_try"))}
            if sel:
                item["selection"] = {"status": sel.status, "t_in": sel.t_in, "t_out": sel.t_out, "score": sel.score, "reason": sel.reason,
                                     "decided_by": sel.decided_by, "moment_id": sel.moment_id,
                                     "frame_url": f"/api/v1/moments/{sel.moment_id}/frame" if sel.moment_id else None,
                                     "asset": asset_brief(sel.asset_id) if sel.asset_id else None,
                                     "speed": float(sel.extras.get("speed") or 1.0), "stabilise": bool(sel.extras.get("stabilise")), "live_sound": bool(sel.extras.get("live_sound")), "sfx": sel.extras.get("sfx"),
                                     "inserts": sel.extras.get("inserts", []), "focus_x": (sel.extras.get("focus") or {}).get("x") if (sel.extras.get("focus") or {}).get("asset_id") == sel.asset_id else None,
                                     "angles": angles_of(sel),
                                     "alternates": [{**a, "frame_url": f"/api/v1/moments/{a['moment_id']}/frame", "asset": asset_brief(a["asset_id"])} for a in sel.alternates]}
            shots.append(item)
        renders = [{"render_id": r["render_id"], "script_id": r["script_id"], "created_at": r["created_at"], "qc": r["qc"], "review": r["review"],
                    "url": f"/api/v1/renders/{r['render_id']}/file", "package": system.distribution.package(r["render_id"])}
                   for r in system.projects.renders(project["project_id"])]
        return {**project, "script": {"script_id": script["script_id"], "version": script["version"], "match_approved": script["match_approved"], "critique": script["critique"]} if script else None,
                "shots": shots, "match": latest_run(script["script_id"], "sourcing.match") if script else None,
                "render": latest_run(script["script_id"], "edit.render") if script else None, "renders": renders,
                "generate": latest_run(script["script_id"], "sourcing.generate") if script else None, "generators": system.generation.available(),
                "preview": latest_run(script["script_id"], "edit.preview") if script else None, "options": json.loads(project.get("options") or "{}"),
                "previews": [{"render_id": r["render_id"], "created_at": r["created_at"], "script_id": r["script_id"], "url": f"/api/v1/renders/{r['render_id']}/file", "duration": r["qc"]["duration"], "gaps": r["qc"]["gaps"]}
                             for r in system.projects.renders(project["project_id"], previews=True)[:1]],
                "research": json.loads(project.get("research") or "[]"), "bible": json.loads(project.get("bible") or "[]"),
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

    @app.patch("/api/v1/shots/{shot_id}")
    def annotate_shot(shot_id: str, body: dict):
        system.projects.annotate_shot(shot_id, brief=body.get("brief"), screen_text=body.get("screen_text"),
                                      **{k: body[k] for k in ("target_seconds", "sound_cue", "is_fact", "source") if k in body})
        if isinstance(body.get("gen"), dict):        # the operator's choices for a generated picture
            system.projects.annotate_shot(shot_id, gen={k: (str(v).strip() if v is not None else None) for k, v in body["gen"].items() if k in ("subject", "shot_size", "camera", "provider_image", "provider_video")})
        return {"ok": True}

    @app.patch("/api/v1/shots/{shot_id}/treatment")
    def treat_shot(shot_id: str, body: dict):
        """How one shot is treated in the cut: speed, stabilising, its own sound, a sound effect."""
        try:
            system.edit.set_shot_options(shot_id, **{k: body[k] for k in ("speed", "stabilise", "live_sound", "sfx") if k in body})
        except ValueError:
            raise HTTPException(409, "Câu này chưa có clip")
        return {"ok": True}

    @app.post("/api/v1/projects/{project_id}/command")
    def propose_command(project_id: str, body: dict):
        """What an instruction in the operator's own words would change. Nothing is changed yet."""
        need_project(project_id)
        return {"ops": planning_call(lambda: system.commands.propose(project_id, str(body.get("text", ""))))}

    @app.post("/api/v1/projects/{project_id}/command/apply")
    def apply_command(project_id: str, body: dict):
        current_script_id(project_id)
        done = system.commands.apply(project_id, [op for op in body.get("ops") or [] if isinstance(op, dict)])
        return {**project_view(need_project(project_id)), "done": done["done"]}

    @app.post("/api/v1/projects/{project_id}/repurpose", status_code=201)
    def repurpose(project_id: str, body: dict):
        """The same video in another shape, as a project of its own."""
        source, shape = need_project(project_id), body.get("format")
        if shape not in ("landscape", "portrait", "square") or shape == source["format"]:
            raise HTTPException(422, "Chọn một khung hình khác với khung hiện tại")
        names = {"landscape": "ngang", "portrait": "dọc", "square": "vuông"}
        new = system.projects.clone(project_id, title=f"{source['title']} (bản {names[shape]})", format=shape)
        return project_view(need_project(new))

    @app.post("/api/v1/projects/{project_id}/renders/import", status_code=201)
    def import_finished(project_id: str, body: dict):
        current_script_id(project_id)
        try:
            system.edit.import_finished(project_id, str(body.get("path", "")))
        except FileNotFoundError:
            raise HTTPException(404, "Không tìm thấy file ở đường dẫn này")
        except AdapterError as err:
            raise HTTPException(422, f"Không đọc được file này như một video: {err.message or err.code.value}")
        return project_view(need_project(project_id))

    @app.post("/api/v1/renders/{render_id}/handoff")
    def handoff(render_id: str):
        if system.projects.render(render_id) is None:
            raise HTTPException(404, "no such render")
        return system.distribution.handoff(render_id)

    @app.post("/api/v1/renders/{render_id}/captions/translate")
    def translate_captions(render_id: str, body: dict):
        try:
            return planning_call(lambda: system.distribution.translate_captions(render_id, str(body.get("language", ""))))
        except ValueError:
            raise HTTPException(409, "Bản dựng này chưa có gói xuất bản, không có phụ đề, hoặc ngôn ngữ chưa được hỗ trợ")

    @app.post("/api/v1/assets/{asset_id}/enhance", status_code=202)
    def enhance(asset_id: str, body: dict):
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        try:
            return {"run_id": system.library.enhance(asset_id, upscale=int(body.get("upscale") or 1), smooth_fps=body.get("smooth_fps"))}
        except ValueError:
            raise HTTPException(422, "Chỉ nâng chất lượng được cho video, và phải chọn phóng to hoặc làm mượt")

    @app.post("/api/v1/projects/{project_id}/preview", status_code=202)
    def start_preview(project_id: str):
        return {"run_id": system.edit.start_preview(current_script_id(project_id))}

    @app.get("/api/v1/assets/{asset_id}/roughcut")
    def roughcut_plan(asset_id: str):
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        return system.roughcut.plan(asset_id)

    @app.post("/api/v1/assets/{asset_id}/roughcut", status_code=201)
    def roughcut(asset_id: str, body: dict):
        """Cut a recording by its words, into a project of its own or into an existing one."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        name = system.assets.path_of(system.assets.original(asset_id)).stem
        project_id = body.get("project_id") or system.planning.create_project(str(body.get("title") or f"Dựng thô: {name}").strip(),
                                                                              format=body.get("format") if body.get("format") in ("landscape", "portrait", "square") else "landscape")
        need_project(project_id)
        try:
            system.roughcut.apply(project_id, asset_id, keep=[int(i) for i in body["keep"]] if isinstance(body.get("keep"), list) else None)
        except ValueError:
            raise HTTPException(422, "Không có câu nào được giữ lại. Bản ghi này có thể chưa được nghe, hoặc không có lời nói.")
        return project_view(need_project(project_id))

    @app.post("/api/v1/shots/{shot_id}/variation")
    def vary_shot(shot_id: str):
        """Ask for another picture of the same thing; it is made the next time generation runs."""
        if system.projects.shot(shot_id) is None:
            raise HTTPException(404, "no such shot")
        return {"attempt": system.generation.vary(shot_id)}

    @app.get("/api/v1/projects/{project_id}/gaps")
    def gap_plan(project_id: str):
        have = system.generation.available()
        return {"gaps": system.sourcing.gap_plan(current_script_id(project_id), stock=any(c.name == "stock" for c in system.adapters.describe()), generate=have["image"] and have["video"])}

    @app.get("/api/v1/projects/{project_id}/shotlist")
    def shot_list(project_id: str):
        from fastapi.responses import PlainTextResponse
        text = system.sourcing.shot_list(current_script_id(project_id), title=need_project(project_id)["title"])
        return PlainTextResponse(text, media_type="text/markdown; charset=utf-8", headers={"content-disposition": "attachment; filename*=UTF-8''can-quay-them.md"})

    @app.post("/api/v1/control/providers")
    def set_providers(body: dict):
        """The order in which providers of one kind of picture are tried."""
        kind = body.get("kind")
        if kind not in ("image_gen", "video_gen"):
            raise HTTPException(422, "kind must be image_gen or video_gen")
        known = [p["name"] for p in system.generation.providers(kind)]
        order = [n for n in body.get("order") or [] if n in known]
        system.orch.set_setting(f"providers:{kind}", json.dumps(order))
        return system.generation.available()

    def planning_call(work):
        """Run a planning step that leans on a tool, and say plainly why it could not be done."""
        try:
            return work()
        except AdapterError as err:
            if err.code is ErrorCode.AUTH:
                raise HTTPException(409, "Chế độ riêng tư đang bật nên hệ thống không đọc trang web. Tắt ở mục Hệ thống, hoặc tự nhập nguồn.")
            raise HTTPException(503 if err.code in (ErrorCode.UNAVAILABLE, ErrorCode.TIMEOUT) else 422, f"Không làm được: {err.message or err.code.value}")
        except KeyError as err:
            raise HTTPException(409, f"Máy này chưa có công cụ {err.args[0]} cho việc này")

    @app.post("/api/v1/projects/{project_id}/sources/read")
    def read_source(project_id: str, body: dict):
        need_project(project_id)
        url = str(body.get("url", "")).strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(422, "Địa chỉ phải bắt đầu bằng http:// hoặc https://")
        planning_call(lambda: system.planning.read_source(project_id, url))
        return project_view(need_project(project_id))

    @app.post("/api/v1/projects/{project_id}/facts/find")
    def find_facts(project_id: str):
        current_script_id(project_id)
        found = planning_call(lambda: system.planning.find_facts(project_id))
        return {**project_view(need_project(project_id)), "found": len(found)}

    @app.post("/api/v1/projects/{project_id}/facts/check")
    def check_facts(project_id: str):
        current_script_id(project_id)
        planning_call(lambda: system.planning.check_facts(project_id))
        return project_view(need_project(project_id))

    @app.post("/api/v1/projects/{project_id}/critique")
    def critique_script(project_id: str):
        current_script_id(project_id)
        planning_call(lambda: system.planning.critique(project_id))
        return project_view(need_project(project_id))

    @app.post("/api/v1/projects/{project_id}/revise")
    def revise_script(project_id: str):
        current_script_id(project_id)
        revised = planning_call(lambda: system.planning.revise(project_id))
        return {**project_view(need_project(project_id)), "revised": bool(revised)}

    @app.get("/api/v1/radar")
    def radar():
        topics = json.loads(system.orch.setting("radar_topics", "[]"))
        return {**planning_call(lambda: system.planning.radar(topics)), "topics": topics}

    @app.post("/api/v1/radar/topics")
    def radar_topics(body: dict):
        topics = list(dict.fromkeys(t for t in (str(t).strip() for t in body.get("topics") or []) if t))[:20]
        system.orch.set_setting("radar_topics", json.dumps(topics, ensure_ascii=False))
        return radar()

    @app.get("/api/v1/calendar")
    def calendar():
        """The editorial calendar: every project with the day it is meant to go out and how far along it is."""
        rows = []
        for p in system.projects.projects():
            script = system.projects.current_script(p["project_id"])
            renders = system.projects.renders(p["project_id"])
            approved = next((r for r in renders if (r["review"] or {}).get("approved")), None)
            stage = ("Đã có gói xuất bản" if approved and system.distribution.package(approved["render_id"]) else "Bản dựng đã duyệt" if approved
                     else "Chờ duyệt bản dựng" if renders else "Đã chọn clip" if script and script["match_approved"] else "Có kịch bản" if script else "Mới có ý tưởng")
            rows.append({"project_id": p["project_id"], "title": p["title"], "format": p["format"], "due_date": p.get("due_date"), "stage": stage, "ready": bool(approved)})
        return {"projects": rows, "today": time.strftime("%Y-%m-%d")}

    @app.post("/api/v1/ideas")
    def propose_ideas():
        try:
            ideas = system.planning.ideas()
        except AdapterError as err:
            raise HTTPException(503, f"Mô hình không trả lời được: {err.message or err.code.value}")
        system.orch.set_setting("ideas", json.dumps(ideas, ensure_ascii=False))
        return {"ideas": ideas}

    @app.get("/api/v1/ideas")
    def last_ideas():
        return {"ideas": json.loads(system.orch.setting("ideas", "[]"))}

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
        if "options" in fields:                  # treatments applied to the whole cut
            current = json.loads(need_project(project_id).get("options") or "{}")
            fields["options"] = json.dumps({**current, **{k: bool(v) for k, v in (fields["options"] or {}).items() if k in ("clean_audio", "match_colour", "music_cleared")}})
        if "bible" in fields:                    # how the project's characters, places and props look, so that every shot shows them the same way
            kinds = ("character", "setting", "prop", "style")
            fields["bible"] = json.dumps([{"name": str(e.get("name", "")).strip(), "kind": e.get("kind") if e.get("kind") in kinds else "character", "voice": str(e.get("voice") or "").strip() or None,
                                           "description": str(e.get("description") or "").strip(), "asset_id": e.get("asset_id") if system.assets.asset(str(e.get("asset_id") or "")) else None}
                                          for e in fields["bible"] if str(e.get("name", "")).strip()], ensure_ascii=False)
        if "due_date" in fields:
            day = str(fields["due_date"] or "").strip()
            try:
                fields["due_date"] = time.strftime("%Y-%m-%d", time.strptime(day, "%Y-%m-%d")) if day else None
            except ValueError:
                raise HTTPException(422, "Ngày phải có dạng năm-tháng-ngày, ví dụ 2026-10-20")
        if "research" in fields:                 # sources: where a claim comes from, who published it, when, and the passage that supports it
            # A source link is shown as a link, so only web addresses are kept: anything else (a javascript: address, for example) is dropped.
            web = lambda url: url if url.lower().startswith(("http://", "https://")) else ""
            fields["research"] = json.dumps([{key: str(src.get(key) or "").strip() for key in ("title", "publisher", "date", "passage")} | {"url": web(str(src.get("url") or "").strip()), "retrieved_at": src.get("retrieved_at") or time.time()}
                                             for src in fields["research"] if str(src.get("title", "")).strip()], ensure_ascii=False)
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
            if n["kind"] == "metrics_due":
                name, link = n["reason"], "/ke-hoach?xem=ket-qua"
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
        # The rights gate: a cut with something unresolved is not packaged unless the operator says why it may go out.
        from nexora.app import render_rights
        from nexora.modules.quality.qc import package_checks
        rights, reason = render_rights(system, render_id), str(body.get("override_reason") or "").strip()
        if rights["blockers"] and not reason:
            raise HTTPException(409, "Chưa đóng gói được: " + " ".join(rights["blockers"]) + " Xử lý các điểm này, hoặc ghi lý do vẫn đăng.")
        package = system.distribution.build_package(render_id, title=body.get("title"), description=body.get("description"))
        package = system.distribution.annotate_package(render_id, rights={**rights, "override_reason": reason or None, "checked_at": time.time()})
        return system.distribution.annotate_package(render_id, checks=package_checks(package))

    # ------------------------------------------------------------------ publishing and what is learned from it
    def published(work):
        try:
            return work()
        except ValueError as err:
            reasons = {"no_package": (409, "Bản dựng này chưa có gói xuất bản"), "unknown_target": (422, "Không có nơi đăng này"), "bad_url": (422, "Địa chỉ phải bắt đầu bằng http:// hoặc https://"),
                       "not_published": (409, "Bản này chưa được đăng"), "no_figures": (422, "Hãy nhập ít nhất một con số")}
            status, text = reasons.get(str(err), (422, "Yêu cầu chưa hợp lệ"))
            raise HTTPException(status, text)

    @app.get("/api/v1/publishing")
    def publishing(project_id: str | None = None):
        rows = system.publishing.publications(project_id=project_id)
        return {"targets": system.publishing.targets(), "publications": rows, "due": system.publishing.due(), "marks": [1, 24, 72, 168],
                "experiments": system.publishing.experiments() if project_id is None else [], "breakdown": system.publishing.breakdown() if project_id is None else []}

    @app.post("/api/v1/renders/{render_id}/publish")
    def publish(render_id: str, body: dict):
        """Send a packaged cut to a destination, or record where the operator uploaded it by hand. Asking twice never sends twice."""
        target, variant = str(body.get("target", "")), str(body.get("variant") or "").strip()
        if body.get("url"):
            return published(lambda: system.publishing.record_manual(render_id, target, str(body["url"]), variant=variant))
        return published(lambda: system.publishing.publish(render_id, target, variant=variant))

    @app.post("/api/v1/publications/{publication_id}/reconcile")
    def reconcile_publication(publication_id: str):
        row = system.publishing.reconcile(publication_id)
        if row is None:
            raise HTTPException(404, "Không có bản đăng này")
        return row

    @app.post("/api/v1/publications/{publication_id}/metrics")
    def add_metrics(publication_id: str, body: dict):
        if system.publishing.publication(publication_id) is None:
            raise HTTPException(404, "Không có bản đăng này")
        try:
            return published(lambda: system.publishing.add_snapshot(publication_id, body))
        except (TypeError, ValueError):
            raise HTTPException(422, "Số liệu phải là số")

    @app.get("/api/v1/publications/{publication_id}/forecast")
    def forecast(publication_id: str):
        if system.publishing.publication(publication_id) is None:
            raise HTTPException(404, "Không có bản đăng này")
        return system.publishing.forecast(publication_id)

    @app.post("/api/v1/experiments", status_code=201)
    def create_experiment(body: dict):
        try:
            return system.publishing.create_experiment(str(body.get("question", "")), [str(p) for p in body.get("publications") or []], metric=str(body.get("metric") or "views"), labels=body.get("labels"))
        except ValueError:
            raise HTTPException(422, "Một thí nghiệm cần câu hỏi và ít nhất hai bản đăng khác nhau")

    @app.post("/api/v1/experiments/{experiment_id}/close")
    def close_experiment(experiment_id: str, body: dict):
        if system.publishing.experiment(experiment_id) is None:
            raise HTTPException(404, "Không có thí nghiệm này")
        return system.publishing.close_experiment(experiment_id, str(body.get("conclusion", "")))

    @app.post("/api/v1/renders/{render_id}/titles")
    def suggest_titles(render_id: str):
        if system.distribution.package(render_id) is None:
            raise HTTPException(409, "Bản dựng này chưa có gói xuất bản")
        return {"titles": planning_call(lambda: system.distribution.suggest_titles(render_id))}

    @app.patch("/api/v1/renders/{render_id}/package")
    def edit_package(render_id: str, body: dict):
        if system.distribution.package(render_id) is None:
            raise HTTPException(409, "Bản dựng này chưa có gói xuất bản")
        if body.get("poster_text"):
            try:
                return system.distribution.make_poster(render_id, str(body.get("base") or system.distribution.package(render_id)["thumbnails"][0]), str(body["poster_text"]))
            except ValueError:
                raise HTTPException(422, "Chọn một ảnh của gói và nhập chữ cho nó")
        return system.distribution.set_text(render_id, title=body.get("title"), description=body.get("description"))

    @app.get("/api/v1/renders/{render_id}/rights")
    def rights(render_id: str):
        from nexora.app import render_rights
        if system.projects.render(render_id) is None:
            raise HTTPException(404, "Không tìm thấy bản dựng")
        return render_rights(system, render_id)

    @app.post("/api/v1/renders/{render_id}/watch")
    def watch(render_id: str):
        """Have the vision model look at the finished cut, shot by shot, as a viewer would."""
        if system.projects.render(render_id) is None:
            raise HTTPException(404, "Không tìm thấy bản dựng")
        if system.viewer is None:
            raise HTTPException(409, "Máy này chưa có mô hình nhìn để xem lại bản dựng")
        return system.viewer.watch(render_id)

    @app.get("/api/v1/evaluation")
    def evaluation():
        return {"cases": system.evaluation.cases(), "runs": system.evaluation.runs()}

    @app.post("/api/v1/evaluation/cases", status_code=201)
    def add_case(body: dict):
        """Keep an accepted clip as a known right answer: the line of a shot and the stretch chosen for it."""
        shot = system.projects.shot(str(body.get("shot_id", "")))
        sel = system.projects.selection(shot.shot_id) if shot else None
        if sel is None or sel.status == "gap" or not sel.asset_id or sel.t_in is None:
            raise HTTPException(409, "Câu này chưa có clip để lấy làm mẫu")
        return {"case_id": system.evaluation.add_case(shot.brief or shot.text, sel.asset_id, sel.t_in, sel.t_out), "cases": len(system.evaluation.cases())}

    @app.delete("/api/v1/evaluation/cases/{case_id}")
    def remove_case(case_id: str):
        system.evaluation.remove_case(case_id)
        return evaluation()

    @app.post("/api/v1/evaluation/run")
    def run_evaluation():
        from nexora.app import evaluation_config
        if not system.evaluation.cases():
            raise HTTPException(409, "Chưa có mẫu nào. Lưu vài clip đã duyệt làm mẫu trước.")
        system.evaluation.run(evaluation_config(system))
        return evaluation()

    @app.get("/api/v1/renders/{render_id}/package")
    def get_package(render_id: str):
        package = system.distribution.package(render_id)
        if package is None:
            raise HTTPException(404, "Chưa có gói xuất bản")
        return package

    @app.get("/api/v1/renders/{render_id}/package/{name}")
    def package_file(render_id: str, name: str):
        package = system.distribution.package(render_id)
        if package is None or name not in (package["thumbnails"] + [package["video"], package["captions"], package.get("captions_vtt"), *package.get("translations", {}).values()]):
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
