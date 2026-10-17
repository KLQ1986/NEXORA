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
        "status": (status := system.orch.run_status(run_id).value),
        "cleared": status == "failed" and system.orch.cleared(run_id),      # a failure set aside, or put right by a later run
        "cost": system.orch.run_cost(run_id),
        "stages": [{"stage_id": s.stage_id, "stage_key": s.stage_key, "status": s.status.value, "blocked_reason": s.blocked_reason,
                    "attempts": len(system.orch.attempts(s.stage_id)), "outputs": s.outputs}
                   for s in system.orch.stages(run_id)],
    }


TEXT_TASKS = {"write": "Viết nháp kịch bản và gợi ý ý tưởng", "critique": "Phản biện kịch bản", "revise": "Viết lại theo nhận xét", "facts": "Tìm câu nêu dữ kiện",
              "check": "Đối chiếu dữ kiện với nguồn", "titles": "Gợi ý tiêu đề", "translate": "Dịch phụ đề", "command": "Chỉnh sửa bằng lời"}


def enhanced_stale(system, asset_id: str, meta: dict) -> bool:
    approved = system.vq_reader.recipe(asset_id, status="approved")
    made_from = (meta or {}).get("visual_quality")
    return (made_from != approved.recipe_id) if approved else bool(made_from)


def asset_view(system, asset: dict, used: dict | None = None) -> dict:
    versions = system.assets.versions(asset["asset_id"])
    by_role = {v.role: v for v in versions}
    original = by_role["original"]
    meta, probe = original.metadata, original.metadata.get("probe", {})
    path = system.assets.path_of(original)
    runs = system.orch.runs_for_subject(asset["asset_id"])
    return {
        "asset_id": asset["asset_id"], "name": asset.get("title") or path.name, "file_name": path.name, "title": asset.get("title"), "path": str(path), "origin": asset["origin"],
        "privacy_class": asset["privacy_class"], "created_at": asset["created_at"], "online": path.is_file(),
        "size": original.size, "checksum": original.checksum, "duplicate_of": meta.get("duplicate_of"),
        "duration": probe.get("duration"), "width": probe.get("width"), "height": probe.get("height"),
        "frame_rate": probe.get("frame_rate"), "has_audio": probe.get("has_audio"),
        "usable_ranges": meta.get("usable_ranges", []), "black_ranges": meta.get("black_ranges", []),
        "frozen_ranges": meta.get("frozen_ranges", []), "scene_cuts": meta.get("scene_cuts", []),
        "angles": [{"asset_id": other, "offset": shift} for other, shift in meta.get("angles", {}).items()],
        "rejected": bool(asset.get("rejected")), "reference_only": bool(asset.get("reference_only")), "consent": asset.get("consent"), "speech": meta.get("speech"), "session": asset.get("session") or f"{path.parent.name}, {str(probe.get('created') or '')[:10]}".rstrip(", "),
        "session_set": asset.get("session"), "trashed_at": asset.get("trashed_at"),
        "used_in": [{"project_id": pid, "title": (system.projects.project(pid) or {}).get("title", "")} for pid in (used if used is not None else system.projects.used_assets()).get(asset["asset_id"], [])],
        "transcribe": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.transcribe"), None),
        "enhance": next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.enhance"), None),
        "enhanced": by_role["enhanced"].metadata if "enhanced" in by_role else None,
        "enhanced_url": f"/media/{by_role['enhanced'].version_id}" if "enhanced" in by_role else None,
        # An enhanced copy made from a recipe that is no longer the approved one: shown as old, and never cut from.
        "enhanced_stale": enhanced_stale(system, asset["asset_id"], by_role["enhanced"].metadata) if "enhanced" in by_role else False,
        "music": meta.get("music"),
        "note": asset.get("note"), "rating": asset.get("rating", 0), "collections": json.loads(asset.get("collections") or "[]"),
        "still": bool(probe.get("still")), "kind": asset.get("kind"), "mean_db": probe.get("mean_db"),
        "thumbnail_url": f"/media/{by_role['thumbnail'].version_id}" if "thumbnail" in by_role else f"/media/{original.version_id}" if probe.get("still") else None,
        "proxy_url": f"/media/{by_role['proxy'].version_id}" if "proxy" in by_role else None,
        # The camera's own file, played where the browser can decode it (HEVC and H.264 on a Mac); the proxy is the stand-in.
        "original_url": f"/media/{original.version_id}", "codec": probe.get("codec"), "pixel_format": probe.get("pixel_format"),
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

    STOCK_SOURCES = {"archive_org": "Internet Archive", "nasa": "NASA", "wikimedia": "Wikimedia Commons"}       # libraries that need no key

    @app.get("/api/v1/generators")
    def generators():
        chosen = json.loads(system.orch.setting("stock_sources", "[]"))
        return {"generators": system.generation.available(), "stock": {"available": any(c.name == "stock" for c in system.adapters.describe()),
                                                                       "sources": [{"key": k, "label": v, "on": not chosen or k in chosen} for k, v in STOCK_SOURCES.items()]}}

    @app.post("/api/v1/control/stock-sources")
    def set_stock_sources(body: dict):
        """Which stock libraries are searched when a line has no picture. At least one stays on."""
        chosen = [k for k in body.get("sources") or [] if k in STOCK_SOURCES]
        if not chosen:
            raise HTTPException(422, "Giữ ít nhất một nguồn stock")
        system.orch.set_setting("stock_sources", json.dumps(chosen))
        return generators()

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
        try:
            system.library.annotate(asset_id, rating=body.get("rating"), collections=body.get("collections"), note=body.get("note"),
                                    rejected=body.get("rejected") if "rejected" in body else None, title=body.get("title"), session=body.get("session"),
                                    reference_only=body.get("reference_only") if "reference_only" in body else None, consent=body.get("consent"))
        except ValueError as err:
            raise HTTPException(422, str(err))
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

    @app.post("/api/v1/runs/dismiss")
    def dismiss_runs(body: dict):
        """Set failures aside once the operator has seen them: {"run_ids": [...]}, or {"pipeline": "library."} for every
        failure of that kind of work."""
        ids = list(body.get("run_ids") or [])
        prefix = str(body.get("pipeline") or "")
        if prefix:
            ids += [r for r in system.orch.runs() if system.orch.pipeline_of(r).startswith(prefix) and system.orch.run_status(r).value == "failed"]
        return {"dismissed": system.orch.dismiss(ids)}

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        if system.orch.run_info(run_id) is None:
            raise HTTPException(404, "no such run")
        system.orch.cancel_run(run_id)
        return run_view(system, run_id)

    def renders_in_use() -> set[str]:
        every = system.projects.projects(include_trashed=True)            # a project in the Trash may still come back with its cuts
        return {r["path"] for p in every for r in system.projects.renders(p["project_id"])} | \
               {r["path"] for p in every for r in system.projects.renders(p["project_id"], previews=True)[:1]}      # only the newest preview is worth keeping

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
                      "pronounce": {str(k).strip(): str(v).strip() for k, v in (t.get("pronounce") or {}).items() if str(k).strip() and str(v).strip()},
                      **({"style": t["style"]} if isinstance(t.get("style"), dict) else {})} for t in body["templates"] if str(t.get("name", "")).strip()]
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
            if view["status"] in ("waiting_review", "blocked", "failed") and not view["cleared"]:
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
                                        critique=bool(body.get("critique", True)), find_sources=bool(body.get("find_sources", False)))
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
        run_id = system.intelligence.understand(asset_id, force=True)
        if run_id is None:
            raise HTTPException(409, "Máy này chưa có mô hình để mô tả footage, hoặc đây là bản trùng")
        return {"run_id": run_id}

    @app.post("/api/v1/assets/{asset_id}/transcribe", status_code=202)
    def transcribe(asset_id: str):
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        run_id = system.intelligence.transcribe(asset_id, force=True)
        if run_id is None:
            raise HTTPException(409, "Footage này không có tiếng, hoặc máy chưa có công cụ nhận dạng giọng nói")
        return {"run_id": run_id}

    @app.post("/api/v1/moments/{moment_id}/deepen")
    def deepen(moment_id: str):
        """Describe one stretch frame by frame."""
        if not system.intelligence.understands or system.index.by_id(moment_id) is None:
            raise HTTPException(404, "no such moment, or no model to look with")
        try:
            made = system.intelligence.deepen(moment_id)
        except ValueError:
            raise HTTPException(422, "Chỉ xem kỹ được một đoạn đã mô tả")
        except AdapterError as err:
            raise HTTPException(503, f"Mô hình không trả lời: {err.message or err.code.value}")
        return {"frames": [moment_view(system.index.by_id(m)) for m in made]}

    @app.get("/api/v1/library/search")
    def search(q: str, limit: int = 24):
        # Pictures, speech and the operator's own notes are searched together; assets set aside are left out.
        # What the words ask to see ("cận cảnh", "không có người", "trong nhà") is held against the fields that have proved
        # accurate (design group 15): an agreeing stretch moves up, a disagreeing one down, and the reason is shown.
        from nexora.modules.sourcing.match import asked
        wanted, released = asked(q), system.fields.released()
        found = system.vi.find(q, limit=limit, levels=("segment", "speech", "note", "frame", "text", "sound", "event", "scene"), wanted=wanted,
                               exclude_assets=system.assets.rejected())
        return {"asked": wanted, "used": sorted(f for f in wanted if f in released or f"model.{f}" in released),
                "hits": [{**moment_view(m, score), "asset": asset_brief(m.asset_id), "fits": why} for score, m, why in found]}

    @app.get("/api/v1/assets/{asset_id}/moments")
    def asset_moments(asset_id: str):
        moments = system.index.moments(asset_id)
        return {"video": next((moment_view(m) | {"title": m.data.get("detail", {}).get("tieu_de")} for m in moments if m.level == "video"), None),
                "segments": [moment_view(m) for m in moments if m.level == "segment"],
                "frames": [moment_view(m) for m in moments if m.level == "frame"],
                "speech": [moment_view(m) | {"words": m.data.get("words", [])} for m in moments if m.level == "speech"]}

    # ------------------------------------------------------------------ shots and beats
    def structure_view(asset_id: str) -> dict:
        from nexora.core.timebase import to_seconds
        from nexora.modules.intelligence.structure import boundaries
        asset = need_asset(asset_id)
        made = system.intelligence.analysis.structure(asset_id)
        runs = system.orch.runs_for_subject(asset_id)
        run = next((run_view(system, r) for r in runs if system.orch.pipeline_of(r) == "library.structure"), None)
        base = {"asset_id": asset_id, "measured": made is not None, "run": run, "reference": asset_id in system.evaluation.references(),
                "duration": system.assets.original(asset_id).metadata.get("probe", {}).get("duration"), "kind": asset.get("kind")}
        if made is None:
            return {**base, "shots": [], "beats": [], "transitions": [], "marks": [], "faults": [], "bars": None, "boundaries": {"shot": [], "beat": []}}
        said = {(m.t_start, m.t_end): m for m in system.index.moments(asset_id, level="segment")}
        golden = system.fields.labels(asset_id)
        known = system.vi.observations(asset_id)                      # everything learnt about this recording, from the canonical model
        beats = []
        for beat in made["beats"]:
            t0, t1 = to_seconds(beat["start"], 2), to_seconds(beat["end"], 2)
            m = said.get((t0, t1))
            here = [o for o in known if abs(o.t_start - t0) < 0.02 and abs(o.t_end - t1) < 0.02]
            label = lambda o: {"value": o.value, "source": o.source, "confidence": o.confidence, **o.evidence}
            beats.append({"t_start": t0, "t_end": t1, "shot": beat["shot"], "pinned": beat["pinned"], "labels": beat["labels"], "frames": beat["frames"],
                          "moment": moment_view(m) if m else None,
                          "profile": {o.field: label(o) for o in here if o.source in ("measured", "recognized") and o.field not in ("flags",) and o.analyzer.startswith(("look", "listen", "telemetry"))},
                          "model_labels": {o.field: label(o) for o in here if o.source == "model" and o.field in ("shot_size", "people", "place", "angle")},
                          "flags": next((o.value for o in here if o.field == "flags"), []),
                          "new_things": (m.data.get("new_things") if m else None) or [],
                          "golden": [g for g in golden if t0 <= (g["t_start"] + g["t_end"]) / 2 < t1]})
        return {**base, "beats": beats, "bars": made["bars"], "faults": system.intelligence.analysis.faults(asset_id), "marks": system.intelligence.analysis.pinned(asset_id),
                "shots": [{"t_start": to_seconds(s["start"], 2), "t_end": to_seconds(s["end"], 2), "transition_in": s["transition_in"], "pinned": s["pinned"]} for s in made["shots"]],
                "transitions": [[to_seconds(a, 2), to_seconds(b, 2)] for a, b in made["transitions"]], "boundaries": boundaries(made)}

    def need_asset(asset_id: str) -> dict:
        asset = system.assets.asset(asset_id)
        if asset is None:
            raise HTTPException(404, "no such asset")
        return asset

    @app.delete("/api/v1/assets/{asset_id}")
    def delete_asset(asset_id: str):
        """Put an asset in NEXORA's Trash. It is deleted for good from there."""
        need_asset(asset_id)
        return to_trash({"assets": [asset_id]})

    @app.get("/api/v1/trash")
    def trash():
        from nexora.app import trash_view
        return trash_view(system)

    @app.post("/api/v1/trash")
    def to_trash(body: dict):
        """Put assets and projects in the Trash: {"assets": [...], "projects": [...]}."""
        from nexora.app import trash_items
        try:
            return trash_items(system, assets=list(body.get("assets") or []), projects=list(body.get("projects") or []))
        except LookupError as e:
            raise HTTPException(404, f"not found: {e}") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/api/v1/trash/restore")
    def from_trash(body: dict):
        from nexora.app import restore_items
        try:
            return restore_items(system, assets=list(body.get("assets") or []), projects=list(body.get("projects") or []))
        except LookupError as e:
            raise HTTPException(404, f"not found: {e}") from None

    @app.post("/api/v1/trash/purge")
    def purge(body: dict):
        """Delete for good: the items named, or everything in the Trash when none are. `discard_files` also moves the
        footage's own files to the computer's Trash."""
        from nexora.app import purge_trash
        named = "assets" in body or "projects" in body
        return purge_trash(system, assets=list(body.get("assets") or []) if named else None, projects=list(body.get("projects") or []) if named else None,
                           older_than_days=None if named else 0, discard_files=bool(body.get("discard_files")))

    @app.get("/api/v1/assets/{asset_id}/structure")
    def asset_structure(asset_id: str):
        return structure_view(asset_id)

    @app.post("/api/v1/assets/{asset_id}/structure/marks")
    def mark_structure(asset_id: str, body: dict):
        """Place a boundary, take one away, move one, or let a mark go. Every later division of this footage keeps what was marked."""
        need_asset(asset_id)
        kind, op = str(body.get("kind", "beat")), str(body.get("op", ""))
        try:
            t = float(body["t"])
            duration = float(system.assets.original(asset_id).metadata.get("probe", {}).get("duration") or 0.0)
            if not 0.0 < t < duration:
                raise ValueError
            if op == "move":
                to = float(body["to"])
                if not 0.0 < to < duration:
                    raise ValueError
                system.intelligence.analysis.pin(asset_id, kind=kind, op="remove", t=t)
                made = system.intelligence.mark_boundary(asset_id, kind=kind, op="add", t=to)
            else:
                made = system.intelligence.mark_boundary(asset_id, kind=kind, op=op, t=t)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "a mark needs a kind (shot or beat), an op (add, remove, move or clear) and a time inside the footage") from None
        if made is None:
            raise HTTPException(409, "this footage has not been measured yet")
        if asset_id in system.evaluation.references():                   # an answer that was put right is still the answer
            system.evaluation.set_reference(asset_id, structure_view(asset_id)["boundaries"])
        return structure_view(asset_id)

    @app.post("/api/v1/assets/{asset_id}/structure/reference")
    def reference_structure(asset_id: str, body: dict):
        """Keep the boundaries of this footage, as the operator has left them, as the answer the dividing rules are measured against."""
        need_asset(asset_id)
        view = structure_view(asset_id)
        if not view["measured"]:
            raise HTTPException(409, "this footage has not been measured yet")
        if body.get("on", True):
            system.evaluation.set_reference(asset_id, view["boundaries"])
        else:
            system.evaluation.clear_reference(asset_id)
        return structure_view(asset_id)

    @app.post("/api/v1/assets/{asset_id}/structure/analyse", status_code=202)
    def analyse_structure(asset_id: str):
        need_asset(asset_id)
        return {"run_id": system.intelligence.analyse(asset_id)}

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
                                     "speed": float(sel.extras.get("speed") or 1.0), "stabilise": bool(sel.extras.get("stabilise")), "live_sound": bool(sel.extras.get("live_sound")), "sfx": sel.extras.get("sfx"), "lipsync": bool(sel.extras.get("lipsync")), "upscale_ml": bool(sel.extras.get("upscale_ml")),
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
                "remote": sorted({c.name.partition(".")[0] for c in system.adapters.describe() if c.name.startswith(("lipsync", "upscale"))}),
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
            return system.intelligence.sync(str(body["a"]), str(body["b"]), media_dir=system.data_dir / "media")
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
            system.edit.set_shot_options(shot_id, **{k: body[k] for k in ("speed", "stabilise", "live_sound", "sfx", "lipsync", "upscale_ml") if k in body})
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
            if body.get("vq"):
                return {"run_id": system.library.enhance(asset_id, from_vq=True)}
            return {"run_id": system.library.enhance(asset_id, upscale=int(body.get("upscale") or 1), smooth_fps=body.get("smooth_fps"))}
        except ValueError as e:
            if body.get("vq"):
                raise HTTPException(409, "Chưa có công thức chất lượng hình nào được duyệt") from e
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

    @app.post("/api/v1/projects/{project_id}/characters/train", status_code=202)
    def train_character(project_id: str, body: dict):
        """Train a model of one character from pictures in the library, on the operator's training endpoint."""
        need_project(project_id)
        if not any(c.name == "train" or c.name.startswith("train.") for c in system.adapters.describe()):
            raise HTTPException(409, "Máy này chưa nối với endpoint huấn luyện nào (runpod_train_endpoint trong nexora.toml)")
        try:
            return {"run_id": system.generation.start_training(project_id, str(body.get("name", "")), [str(a) for a in body.get("assets") or []])}
        except ValueError:
            raise HTTPException(422, "Cần một nhân vật của dự án và ít nhất 4 ảnh trong thư viện")

    @app.post("/api/v1/shots/{shot_id}/variation")
    def vary_shot(shot_id: str):
        """Ask for another picture of the same thing; it is made the next time generation runs."""
        if system.projects.shot(shot_id) is None:
            raise HTTPException(404, "no such shot")
        return {"attempt": system.generation.vary(shot_id)}

    @app.get("/api/v1/projects/{project_id}/match/report")
    def match_report(project_id: str, format: str = "json"):
        """How well the footage serves the script: each line, each recording, and how much has a picture (design 2026-10-15, 9 C)."""
        from fastapi.responses import PlainTextResponse
        from nexora.modules.sourcing import report
        names = {a["asset_id"]: Path(system.assets.original(a["asset_id"]).relative_path).name for a in system.assets.assets() if a["kind"] == "video"}
        made = report.build(system.projects, system.vi, current_script_id(project_id), names=names)
        if format == "md":
            return PlainTextResponse(report.markdown(made, title=need_project(project_id)["title"]), media_type="text/markdown; charset=utf-8")
        return made

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
            if err.code is ErrorCode.AUTH and "privacy mode" in (err.message or ""):
                raise HTTPException(409, "Chế độ riêng tư đang bật nên hệ thống không đọc trang web. Tắt ở mục Hệ thống, hoặc tự nhập nguồn.")
            if err.code in (ErrorCode.AUTH, ErrorCode.QUOTA_EXHAUSTED):
                raise HTTPException(409, f"Dịch vụ bên ngoài từ chối: {err.message or err.code.value}")
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

    @app.post("/api/v1/projects/{project_id}/sources/find")
    def find_sources(project_id: str, body: dict):
        """Look the subject up in an encyclopedia and read what is found into the project's sources."""
        project = need_project(project_id)
        found = planning_call(lambda: system.planning.find_sources(project_id, str(body.get("query") or project["title"]).strip()))
        return {**project_view(need_project(project_id)), "found": len(found)}

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

    def channel_list() -> list[dict]:
        return json.loads(system.orch.setting("channels", "[]"))

    @app.get("/api/v1/channels")
    def channels():
        """Channels: where videos go out, who for, and how often. A project belongs to at most one."""
        return {"channels": channel_list()}

    @app.post("/api/v1/channels")
    def save_channels(body: dict):
        from nexora.app import templates
        names, out = {t["name"] for t in templates(system)}, []
        for raw in body.get("channels") or []:
            name = str(raw.get("name", "")).strip()
            if not name or name in [c["name"] for c in out]:
                continue
            try:
                cadence = max(0, min(21, int(raw.get("per_week") or 0)))
            except (TypeError, ValueError):
                cadence = 0
            out.append({"name": name, "platform": str(raw.get("platform") or "").strip(), "audience": str(raw.get("audience") or "").strip(), "per_week": cadence,
                        "template": raw.get("template") if raw.get("template") in names else None})
        system.orch.set_setting("channels", json.dumps(out, ensure_ascii=False))
        return {"channels": out}

    def cadence_gaps(rows: list[dict], today: str) -> list[dict]:
        """For each channel with a cadence: the coming four weeks, and how many videos each is short of what the channel promises."""
        import datetime
        start = datetime.date.fromisoformat(today)
        start -= datetime.timedelta(days=start.weekday())
        out = []
        for channel in channel_list():
            if not channel["per_week"]:
                continue
            weeks = []
            for k in range(4):
                first = start + datetime.timedelta(weeks=k)
                last = first + datetime.timedelta(days=6)
                planned = sum(1 for r in rows if r["channel"] == channel["name"] and r["due_date"] and first.isoformat() <= r["due_date"] <= last.isoformat())
                weeks.append({"from": first.isoformat(), "to": last.isoformat(), "planned": planned, "short": max(0, channel["per_week"] - planned)})
            out.append({"channel": channel["name"], "per_week": channel["per_week"], "weeks": weeks, "short": sum(w["short"] for w in weeks)})
        return out

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
            rows.append({"project_id": p["project_id"], "title": p["title"], "format": p["format"], "due_date": p.get("due_date"), "stage": stage, "ready": bool(approved), "channel": p.get("channel")})
        today = time.strftime("%Y-%m-%d")
        return {"projects": rows, "today": today, "channels": channel_list(), "cadence": cadence_gaps(rows, today)}

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
        if "channel" in fields:                  # the channel a video is for; choosing one also brings that channel's template when the project has none
            wanted = next((c for c in channel_list() if c["name"] == fields["channel"]), None)
            fields["channel"] = wanted["name"] if wanted else None
        if "options" in fields:                  # treatments applied to the whole cut
            current = json.loads(need_project(project_id).get("options") or "{}")
            fields["options"] = json.dumps({**current, **{k: bool(v) for k, v in (fields["options"] or {}).items() if k in ("clean_audio", "match_colour", "music_cleared", "footage_may_leave")}})
        if "bible" in fields:                    # how the project's characters, places and props look, so that every shot shows them the same way
            kinds = ("character", "setting", "prop", "style")
            kept = {e["name"]: e for e in json.loads(need_project(project_id).get("bible") or "[]")}          # a trained model stays with its character through edits
            fields["bible"] = json.dumps([{**{k: kept.get(str(e.get("name", "")).strip(), {}).get(k) for k in ("model", "training") if kept.get(str(e.get("name", "")).strip(), {}).get(k)}, "name": str(e.get("name", "")).strip(), "kind": e.get("kind") if e.get("kind") in kinds else "character", "voice": str(e.get("voice") or "").strip() or None,
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

    @app.delete("/api/v1/projects/{project_id}")
    def delete_project(project_id: str):
        """Put a project in NEXORA's Trash. Refused once a video of it has been published."""
        need_project(project_id)
        return to_trash({"projects": [project_id]})

    @app.post("/api/v1/projects/{project_id}/duplicate", status_code=201)
    def duplicate_project(project_id: str):
        """A copy of the project in the same shape, with the same script and the same clips chosen."""
        source = need_project(project_id)
        return project_view(need_project(system.projects.clone(project_id, title=f"{source['title']} (bản sao)", format=source["format"])))

    @app.delete("/api/v1/renders/{render_id}")
    def delete_render(render_id: str):
        """Delete one cut. Its file, when NEXORA made it, goes to the computer's Trash. A cut that has been published stays."""
        from nexora.app import remove_render
        try:
            return remove_render(system, render_id)
        except LookupError:
            raise HTTPException(404, "no such render") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

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
            if n["kind"] in ("model_fallback", "autonomy_lowered"):
                name, link = n["reason"], "/he-thong"
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

    @app.get("/api/v1/campaigns")
    def campaigns():
        return {"campaigns": system.publishing.campaigns()}

    @app.post("/api/v1/campaigns", status_code=201)
    def save_campaign(body: dict):
        try:
            return system.publishing.save_campaign(str(body.get("name", "")), metric=str(body.get("metric") or "views"), target=float(body.get("target") or 0), starts=body.get("starts") or None,
                                                   ends=body.get("ends") or None, project_ids=[str(p) for p in body.get("projects") or []], campaign_id=body.get("campaign_id") or None)
        except (TypeError, ValueError):
            raise HTTPException(422, "Chiến dịch cần tên, một con số mục tiêu không âm và ngày dạng năm-tháng-ngày")

    @app.delete("/api/v1/campaigns/{campaign_id}")
    def delete_campaign(campaign_id: str):
        system.publishing.delete_campaign(campaign_id)
        return campaigns()

    @app.get("/api/v1/publishing/change")
    def effect_of_change(on: str, metric: str = "views"):
        try:
            return system.publishing.effect_of_change(on, metric=metric if metric in ("views", "likes", "comments", "shares", "watch_seconds") else "views")
        except ValueError:
            raise HTTPException(422, "Ngày phải có dạng năm-tháng-ngày")

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

    @app.get("/api/v1/projects/{project_id}/music/suggest")
    def suggest_music(project_id: str, energy: str | None = None):
        """Tracks from the library that would sit under this project's cut, with why each is where it is in the list."""
        project = need_project(project_id)
        script = system.projects.current_script(project_id)
        renders = system.projects.renders(project_id)
        seconds = renders[0]["qc"]["duration"] if renders else sum(max(2.0, len(s.text.split()) / 2.6) + 0.4 for s in (script["shots"] if script else []))
        return {"seconds": round(seconds, 1), "tracks": system.library.suggest_music(seconds=seconds, energy=energy if energy in ("êm", "vừa", "sôi động") else None), "current": project.get("music_path")}

    @app.get("/api/v1/sourcing/feedback")
    def match_feedback():
        return {"counts": system.projects.feedback_counts()}

    @app.get("/api/v1/renders/{render_id}/otio")
    def render_otio(render_id: str):
        if system.projects.render(render_id) is None:
            raise HTTPException(404, "Không tìm thấy bản dựng")
        return FileResponse(system.distribution.export_otio(render_id), media_type="application/json", filename="cut.otio")

    @app.get("/api/v1/renders/{render_id}/lineage")
    def render_lineage(render_id: str):
        if system.projects.render(render_id) is None:
            raise HTTPException(404, "Không tìm thấy bản dựng")
        return system.distribution.lineage(render_id)

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

    # ---------------------------------------------------------------- how right each field is (design 2026-10-14, section 8)
    @app.get("/api/v1/fields")
    def fields_report():
        from nexora.modules.quality.fields import FIELDS, MIN_LABELS
        runs = system.fields.runs(5)
        last = runs[0]["results"] if runs else {}
        return {"fields": [{"field": f, "name": spec["name"], "source": spec["source"], "bar": spec["bar"], "values": list(spec["values"]),
                            "status": system.fields.status(f), **{k: v for k, v in (last.get(f) or {}).items() if k not in ("name", "source", "bar", "status")}}
                           for f, spec in FIELDS.items()],
                "min_labels": MIN_LABELS, "labels": len(system.fields.labels()), "runs": [{"run_id": r["run_id"], "created_at": r["created_at"]} for r in runs],
                "regressions": system.fields.regressions()}

    @app.post("/api/v1/fields/measure")
    def measure_fields():
        from nexora.app import structure_config
        system.fields.measure({"structure": structure_config(system), "model": system.orch.setting("model_routes", "{}")})
        return fields_report()

    @app.get("/api/v1/assets/{asset_id}/golden")
    def golden_labels(asset_id: str):
        return {"labels": system.fields.labels(asset_id), "history": system.fields.history(asset_id)}

    @app.post("/api/v1/assets/{asset_id}/golden", status_code=201)
    def add_golden_labels(asset_id: str, body: dict):
        """What the operator says is true of stretches of this footage: [{t_start, t_end, field, value}, ...]."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        made = []
        try:
            for item in body.get("labels") or []:
                made.append(system.fields.label(asset_id, float(item["t_start"]), float(item["t_end"]), str(item["field"]), str(item["value"]),
                                                by=str(body.get("by") or "operator")))
        except (KeyError, ValueError) as err:
            raise HTTPException(422, str(err))
        return {"made": made, "labels": system.fields.labels(asset_id)}

    @app.delete("/api/v1/golden/{label_id}")
    def remove_golden_label(label_id: str):
        system.fields.unlabel(label_id)
        return {"ok": True}

    @app.get("/api/v1/flags")
    def open_flags(state: str = "open", limit: int = 200):
        """The review queue (design 10-13, section 10): beats where a model's description disagrees with what was measured."""
        names = {a["asset_id"]: (a.get("title") or Path(system.assets.path_of(system.assets.original(a["asset_id"]))).name) for a in system.assets.assets()}
        out = []
        for asset_id in names:
            said = {(round(m.t_start, 2), round(m.t_end, 2)): m for m in system.index.moments(asset_id, level="segment")}
            for o in system.vi.observations(asset_id, "flags"):
                m = said.get((round(o.t_start, 2), round(o.t_end, 2)))
                if m is None:
                    continue
                for k, flag in enumerate(o.value or []):
                    if flag.get("state", "open") == state:
                        out.append({"moment_id": m.moment_id, "index": k, "asset_id": asset_id, "name": names[asset_id], "t_start": o.t_start, "t_end": o.t_end,
                                    "rule": flag.get("rule"), "message": flag.get("message"), "state": flag.get("state", "open"), "frame": m.data.get("frame"), "text": m.text})
        counts: dict[str, int] = {}
        for f in out:
            counts[f["rule"]] = counts.get(f["rule"], 0) + 1
        return {"flags": out[:limit], "total": len(out), "by_rule": counts}

    @app.post("/api/v1/flags")
    def settle_flag(body: dict):
        """Close a flag: "resolved" (the operator put it right, or the model was right after all) or "ignored"."""
        try:
            flags = system.intelligence.settle_flag(str(body.get("moment_id", "")), int(body.get("index", -1)), str(body.get("state", "")), str(body["note"]) if body.get("note") else None)
        except ValueError:
            raise HTTPException(422, "Cần một cảnh có thật và một trạng thái: open, resolved, ignored")
        except LookupError:
            raise HTTPException(404, "no such flag")
        return {"flags": flags}

    @app.post("/api/v1/assets/{asset_id}/profile", status_code=202)
    def profile_again(asset_id: str):
        """Measure and recognise the footage again (people, size of frame, light, colour, text, sound), then describe it."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        run_id = system.intelligence.profile(asset_id)
        if run_id is None:
            raise HTTPException(409, "Đây là bản trùng của một footage đã có")
        return {"run_id": run_id}

    @app.get("/api/v1/assets/{asset_id}/dossier")
    def asset_dossier(asset_id: str, format: str = "json"):
        """Everything learnt about a recording in one place, with a word on every beat (design 2026-10-15, section 9 B)."""
        from fastapi.responses import PlainTextResponse
        from nexora.modules.intelligence import dossier
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        made = dossier.build(system.vi, asset_id, name=Path(system.assets.original(asset_id).relative_path).name)
        if made is None:
            raise HTTPException(404, "Footage này chưa được phân tích")
        if format == "md":
            return PlainTextResponse(dossier.markdown(made), media_type="text/markdown; charset=utf-8")
        return made

    # --------------------------------------------------------------------------------- Visual Quality (design 2026-10-16)
    def vq_view(subject: str) -> dict:
        shown = system.vq_reader.summary(subject)
        for preview in shown.get("previews", []):
            preview["urls"] = {k: f"/api/v1/vq/files/{subject}/{Path(v).parent.name}/{Path(v).name}" for k, v in preview.get("files", {}).items()}
        return shown

    def vq_out(subject: str, asked: str | None, *, master: bool) -> str:
        """Where an export through the API is written: always inside the subject's own exports folder. A path from a request is
        taken only if it resolves there, so no request can make the server write anywhere else on the disk."""
        root = (system.data_dir / "vq" / subject / "exports").resolve()
        if not asked:
            return str(system.vq.export_path(subject, master=master))
        given = Path(asked)
        if not given.is_absolute() and given.name != asked:      # a bare file name, or an absolute path: nothing in between
            raise HTTPException(422, "Chỉ xuất được vào thư mục exports của mục này")
        path = (root / asked if not given.is_absolute() else given).resolve()
        if root not in path.parents:
            raise HTTPException(422, "Chỉ xuất được vào thư mục exports của mục này")
        return str(path)

    @app.get("/api/v1/assets/{asset_id}/vq")
    def asset_vq(asset_id: str):
        """What Visual Quality knows of an asset: its source profile, defects, the current recipe, previews and measures."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        return vq_view(asset_id)

    @app.post("/api/v1/assets/{asset_id}/vq/plan", status_code=202)
    def asset_vq_plan(asset_id: str, body: dict | None = None):
        """Profile, assess and propose a recipe. `body`: target_height, target_fps, denoise, sharpen, stabilise, exposure, approve."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        subject = system.vq.subject_for_asset(asset_id)
        return {"subject": subject, "run_id": system.vq.analyse(subject, **(body or {}))}

    @app.post("/api/v1/assets/{asset_id}/vq/preview", status_code=202)
    def asset_vq_preview(asset_id: str, body: dict | None = None):
        b = body or {}
        return {"run_id": system.vq.preview(asset_id, t=b.get("t"), seconds=float(b.get("seconds", 3.0)), recipe_id=b.get("recipe_id"))}

    @app.post("/api/v1/assets/{asset_id}/vq/apply", status_code=202)
    def asset_vq_apply(asset_id: str, body: dict | None = None):
        b = body or {}
        if system.vq_reader.recipe(asset_id, status="approved") is None:
            raise HTTPException(409, "Chưa có công thức nào được duyệt")
        out = vq_out(asset_id, b.get("out"), master=bool(b.get("master"))) if (b.get("out") or b.get("export")) else None
        return {"run_id": system.vq.apply(asset_id, out=out, master=bool(b.get("master"))), "out": out}

    @app.post("/api/v1/vq/recipes/{recipe_id}/approve")
    def vq_approve(recipe_id: str):
        if system.vq_reader.by_id(recipe_id) is None:
            raise HTTPException(404, "no such recipe")
        system.vq.approve(recipe_id)
        return {"ok": True}

    @app.post("/api/v1/vq/recipes/{recipe_id}/reject")
    def vq_reject(recipe_id: str):
        if system.vq_reader.by_id(recipe_id) is None:
            raise HTTPException(404, "no such recipe")
        system.vq.reject(recipe_id)
        return {"ok": True}

    @app.patch("/api/v1/vq/recipes/{recipe_id}/shots/{shot}/steps/{step}")
    def vq_edit_step(recipe_id: str, shot: int, step: int, body: dict):
        """The operator changes a step's parameters or turns it off: a new proposed version of the recipe."""
        try:
            return {"recipe_id": system.vq.edit_step(recipe_id, shot, step, params=body.get("params"), off=body.get("off"))}
        except (LookupError, IndexError):
            raise HTTPException(404, "no such step")

    @app.post("/api/v1/vq/recipes/{recipe_id}/shots/{shot}/remove")
    def vq_remove(recipe_id: str, shot: int, body: dict):
        """The operator marks what to take out of a shot: `regions`, rectangles [x, y, w, h] in the source's pixels. A new
        proposed version of the recipe, with the removal by ProPainter, to preview and approve like any other step."""
        regions = body.get("regions") or ([body["region"]] if body.get("region") else [])
        if not regions:
            raise HTTPException(422, "regions are needed")
        try:
            return {"recipe_id": system.vq.add_removal(recipe_id, shot, regions)}
        except (LookupError, IndexError):
            raise HTTPException(404, "no such shot")
        except AdapterError as e:
            raise HTTPException(409 if e.code == ErrorCode.UNAVAILABLE else 422, str(e))

    @app.post("/api/v1/vq/recipes/{recipe_id}/match")
    def vq_match(recipe_id: str, body: dict):
        """Match the subject's colour to another's: `reference` (a subject), `t` (where in it), `shot` (one shot; every shot when
        absent), `amount` (0..1) and `mode` (`look`: tone, white balance and saturation, for any two scenes; `scene`: the whole spread
        of colours, for two shots of one place). A new proposed version of the recipe, to preview and approve like any other step."""
        reference = body.get("reference")
        if not reference:
            raise HTTPException(422, "a reference is needed")
        shot = body.get("shot")
        try:
            return {"recipe_id": system.vq.add_match(recipe_id, str(reference), float(body.get("t") or 0.0),
                                                     shot=None if shot is None else int(shot), amount=float(body.get("amount", 1.0)),
                                                     mode=str(body.get("mode") or "look"))}
        except (LookupError, IndexError):
            raise HTTPException(404, "no such recipe or shot")
        except AdapterError as e:
            raise HTTPException(409 if e.code == ErrorCode.UNAVAILABLE else 422, str(e))

    @app.post("/api/v1/vq/jobs", status_code=201)
    def vq_job(body: dict):
        """Any file, not taken into the library: profiled, assessed and given a recipe. `options` as for an asset."""
        try:
            subject = system.vq.subject_for_file(str(body.get("path", "")))
        except FileNotFoundError:
            raise HTTPException(404, "Không tìm thấy file")
        return {"subject": subject, "run_id": system.vq.analyse(subject, **(body.get("options") or {}))}

    @app.get("/api/v1/vq/jobs/{subject}")
    def vq_job_view(subject: str):
        if system.vq_reader.subject(subject) is None:
            raise HTTPException(404, "no such job")
        return vq_view(subject)

    @app.post("/api/v1/vq/jobs/{subject}/preview", status_code=202)
    def vq_job_preview(subject: str, body: dict | None = None):
        b = body or {}
        return {"run_id": system.vq.preview(subject, t=b.get("t"), seconds=float(b.get("seconds", 3.0)), recipe_id=b.get("recipe_id"))}

    @app.post("/api/v1/vq/jobs/{subject}/apply", status_code=202)
    def vq_job_apply(subject: str, body: dict | None = None):
        b = body or {}
        if system.vq_reader.recipe(subject, status="approved") is None:
            raise HTTPException(409, "Chưa có công thức nào được duyệt")
        out = vq_out(subject, b.get("out"), master=bool(b.get("master")))
        return {"run_id": system.vq.apply(subject, out=out, master=bool(b.get("master"))), "out": out}

    @app.post("/api/v1/vq/subjects/{subject}/bench")
    def vq_bench(subject: str, body: dict | None = None):
        """The engine measured on a clean frame of this subject, damaged on purpose: is each damage found, and undone?"""
        if system.vq_reader.profile(subject) is None:
            raise HTTPException(404, "Chưa có hồ sơ nguồn của mục này")
        return system.vq.benchmark(subject, t=(body or {}).get("t"))

    @app.get("/api/v1/vq/files/{subject}/{folder}/{name}")
    def vq_file(subject: str, folder: str, name: str):
        root = (system.data_dir / "vq").resolve()
        path = (root / subject / "previews" / folder / name).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(path)

    # The Visual Quality screen: every source, library or not, in one list, and one set of actions for either.
    def vq_run(subject: str) -> dict | None:
        runs = [r for r in system.orch.runs_for_subject(subject) if system.orch.pipeline_of(r).startswith("vq.")]
        return run_view(system, runs[0]) if runs else None

    def vq_state(subject: str, recipe: dict | None) -> str:
        run = vq_run(subject)
        if run and run["status"] in ("queued", "running"):
            return "running"
        if run and run["status"] == "failed" and not run["cleared"]:
            return "failed"
        return (recipe or {}).get("status") or "none"

    def vq_ensure(subject: str) -> str:
        if system.vq_reader.subject(subject) is not None:
            return subject
        if system.assets.asset(subject) is not None:
            return system.vq.subject_for_asset(subject)
        raise HTTPException(404, "no such subject")

    @app.get("/api/v1/vq/subjects")
    def vq_subjects():
        """Every source the screen can work on: each asset of the library (analysed or not) and each file job, with its state."""
        known = {row["subject"]: row for row in system.vq_reader.subjects()}
        items = []
        for asset in system.assets.assets():
            if asset.get("trashed_at") or asset.get("kind") not in ("video", "image"):
                continue
            row = known.pop(asset["asset_id"], None)
            card = asset_view(system, asset)
            items.append({**(row or {"subject": asset["asset_id"], "recipe": None, "defects": 0, "worst": None, "steps": 0, "generative": 0, "verdict": None,
                                     "encoding_name": None, "content": None, "warnings": 0}),
                          "subject": asset["asset_id"], "in_library": True, "name": card.get("name") or asset["asset_id"], "file_name": card.get("file_name"), "still": bool(card.get("still")) or asset.get("kind") == "image", "thumbnail_url": card.get("thumbnail_url"),
                          "duration": card.get("duration"), "width": card.get("width"), "height": card.get("height")})
        for subject, row in known.items():
            items.append({**row, "in_library": False, "name": Path(row["path"]).name, "file_name": Path(row["path"]).name, "thumbnail_url": f"/api/v1/vq/subjects/{subject}/frame?t=0"})
        for item in items:
            item["state"] = vq_state(item["subject"], item.get("recipe"))
        return {"subjects": items}

    @app.get("/api/v1/vq/subjects/{subject}")
    def vq_subject(subject: str):
        """All the screen shows of one source: what it is, its profile and defects, every version of its recipe, previews
        with their checks, what is running, and what has been written out."""
        if system.vq_reader.subject(subject) is None and system.assets.asset(subject) is None:
            raise HTTPException(404, "no such subject")
        shown = vq_view(subject)
        known = system.vq_reader.subject(subject)
        if system.assets.asset(subject) is not None:
            card = asset_view(system, system.assets.asset(subject))
            info = {"name": card.get("name"), "file_name": card.get("file_name"), "in_library": True, "path": card.get("path"),
                    "still": bool(card.get("still")), "duration": card.get("duration"), "width": card.get("width"), "height": card.get("height"),
                    "frame_rate": card.get("frame_rate"), "thumbnail_url": card.get("thumbnail_url"), "proxy_url": card.get("proxy_url"),
                    # The library's enhanced copy: what the approved recipe made, where to see it, and whether it is still current.
                    "enhanced": {**(card.get("enhanced") or {}), "url": card.get("enhanced_url"), "stale": card.get("enhanced_stale")} if card.get("enhanced") else None,
                    "enhance_run": card.get("enhance")}
        else:
            tech = (shown.get("profile") or {}).get("technical", {})
            info = {"name": Path(known["path"]).name, "file_name": Path(known["path"]).name, "in_library": False, "path": known["path"], "still": tech.get("kind") == "still",
                    "duration": tech.get("duration"), "width": tech.get("display_width") or tech.get("width"), "height": tech.get("display_height") or tech.get("height"),
                    "frame_rate": tech.get("frame_rate"), "thumbnail_url": f"/api/v1/vq/subjects/{subject}/frame?t=0", "proxy_url": None}
        exports = sorted((system.data_dir / "vq" / subject / "exports").glob("*")) if (system.data_dir / "vq" / subject / "exports").is_dir() else []
        return {**shown, "info": info, "run": vq_run(subject), "state": vq_state(subject, shown.get("recipe")),
                "exports": [{"name": f.name, "size": f.stat().st_size, "at": f.stat().st_mtime, "url": f"/api/v1/vq/exports/{subject}/{f.name}"} for f in exports]}

    @app.post("/api/v1/vq/subjects/{subject}/plan", status_code=202)
    def vq_subject_plan(subject: str, body: dict | None = None):
        """Analyse (again) with options: target_height, target_fps, denoise, sharpen, stabilise, exposure, deblur, relight, faces,
        ai, allow_cloud."""
        subject = vq_ensure(subject)
        allowed = {"target_height", "target_fps", "denoise", "sharpen", "stabilise", "exposure", "deblur", "relight", "faces", "ai", "allow_cloud"}
        return {"subject": subject, "run_id": system.vq.analyse(subject, **{k: v for k, v in (body or {}).items() if k in allowed and v is not None})}

    @app.post("/api/v1/vq/subjects/{subject}/preview", status_code=202)
    def vq_subject_preview(subject: str, body: dict | None = None):
        b = body or {}
        if system.vq_reader.recipe(subject) is None:
            raise HTTPException(409, "Chưa có công thức để xem trước")
        return {"run_id": system.vq.preview(subject, t=b.get("t"), seconds=float(b.get("seconds", 3.0)), recipe_id=b.get("recipe_id"))}

    @app.post("/api/v1/vq/subjects/{subject}/apply", status_code=202)
    def vq_subject_apply(subject: str, body: dict | None = None):
        """Render the approved recipe: the prepared files cuts use, and with `export` the whole result as a file to download."""
        b = body or {}
        if system.vq_reader.recipe(subject, status="approved") is None:
            raise HTTPException(409, "Chưa có công thức nào được duyệt")
        out = vq_out(subject, b.get("out"), master=bool(b.get("master"))) if (b.get("out") or b.get("export")) else None
        return {"run_id": system.vq.apply(subject, out=out, master=bool(b.get("master"))), "out": out}

    @app.post("/api/v1/vq/subjects/{subject}/cancel")
    def vq_subject_cancel(subject: str):
        run = vq_run(subject)
        if not run or run["status"] not in ("queued", "running"):
            raise HTTPException(409, "Không có việc nào đang chạy")
        system.orch.cancel_run(run["run_id"])
        return {"ok": True}

    @app.get("/api/v1/vq/subjects/{subject}/frame")
    def vq_subject_frame(subject: str, t: float = 0.0, graded: int = 0):
        """A frame of the source at `t`, as it is or with its colour transform, for the viewer and for marking a region."""
        if system.vq_reader.subject(subject) is None:
            raise HTTPException(404, "no such subject")
        try:
            return FileResponse(system.vq.frame(subject, t, graded=bool(graded)))
        except AdapterError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/v1/vq/exports/{subject}/{name}")
    def vq_export_file(subject: str, name: str):
        root = (system.data_dir / "vq").resolve()
        path = (root / subject / "exports" / name).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(path, filename=name)

    @app.post("/api/v1/vq/tidy")
    def vq_tidy():
        """Remove what Visual Quality keeps that nothing will use again (preview intermediates and old previews, prepared files
        of recipes not approved, trial renders, cached frames). Recipes, exports and the approved recipe's files stay."""
        return system.vq.tidy()

    @app.get("/api/v1/vq/usage")
    def vq_usage():
        root = system.data_dir / "vq"
        return {"bytes": sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.is_dir() else 0}

    tools_seen: dict = {}

    @app.get("/api/v1/vq/tools")
    def vq_tools():
        """What this machine can do for Visual Quality, and what to run to set up what is missing. Asking every tool takes a few
        seconds, so the answer is kept for a minute."""
        if tools_seen.get("at", 0) > time.time() - 60:
            return tools_seen["answer"]
        have = sorted(system.vq._have())
        env = system.adapters.environment()
        names = {"apple_frames": "Apple (khử nhiễu, nội suy, siêu phân giải)", "gyroflow": "Gyroflow", "restore_local": "Real-ESRGAN", "restore_faces": "CodeFormer + Vision",
                 "deblur": "NAFNet (MLX)", "inpaint": "ProPainter", "stills": "HEIC / RAW", "local_tone": "Nâng sáng cục bộ", "color": "OpenColorIO / LUT", "model": "Qwen3-VL (giám khảo)"}
        def up(k: str) -> bool:
            e = env.get(k) or {}
            if k == "model":                                  # Ollama says whether it runs and which models it has
                return bool(e.get("running")) and all((e.get("models") or {}).values())
            return bool(e.get("available"))
        tools = [{"name": k, "label": label, "available": up(k), "fix": (env.get(k) or {}).get("fix") or ("ollama serve" if k == "model" else None)}
                 for k, label in names.items() if k in env]
        tools_seen.update(at=time.time(), answer={"have": have, "tools": tools})
        return tools_seen["answer"]

    @app.get("/api/v1/assets/{asset_id}/extracts")
    def extracts(asset_id: str):
        """What has been taken out of a recording: clips, stills and sound, each with its card."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        return {"extracts": [{**e, "urls": {k: f"/api/v1/assets/{asset_id}/extracts/{e['name']}/{f}" for k, f in e["files"].items()}}
                             for e in system.extractor.taken(asset_id)]}

    @app.post("/api/v1/assets/{asset_id}/extract", status_code=201)
    def extract(asset_id: str, body: dict):
        """Take pieces out of a recording (design 2026-10-15, section 9 F): `t_in` and `t_out` for one stretch, or `usable: true`
        for every beat whose picture was measured good; `kinds` among clip, still, audio."""
        from nexora.modules.library.extract import KINDS
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        kinds = tuple(k for k in body.get("kinds", KINDS) if k in KINDS) or KINDS
        try:
            if body.get("usable"):
                made = system.extractor.extract_usable(asset_id, kinds=kinds)
            else:
                made = [system.extractor.extract(asset_id, float(body["t_in"]), float(body["t_out"]), kinds=kinds, name=body.get("name"))]
        except (KeyError, ValueError):
            raise HTTPException(422, "Cần một đoạn có thật, dài không quá 120 giây")
        except FileNotFoundError:
            raise HTTPException(409, "File gốc không có trên máy (ổ đĩa chưa cắm?)")
        return {"extracts": [{"name": m["name"], "files": {k: Path(p).name for k, p in m["files"].items()}, "card": m["card"]} for m in made]}

    @app.get("/api/v1/assets/{asset_id}/extracts/{name}/{file}")
    def extract_file(asset_id: str, name: str, file: str):
        root = (system.data_dir / "exports" / "assets").resolve()
        path = (root / asset_id / name / file).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(path, filename=f"{name}_{file}")

    @app.get("/api/v1/assets/{asset_id}/story")
    def asset_story(asset_id: str, seconds: float = 30.0, format: str = "json"):
        """How a recording tells its story and a proposal for cutting it again (design 2026-10-15, section 9 G). `format`: json,
        md (a page) or edl (an edit decision list for Premiere, Resolve or Avid)."""
        from fastapi.responses import PlainTextResponse
        from nexora.modules.intelligence import story
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        name = Path(system.assets.original(asset_id).relative_path).name
        told = system.intelligence.story(system.vi, asset_id)
        if told is None:
            raise HTTPException(404, "Footage này chưa được phân tích")
        cut = system.intelligence.recut(system.vi, [asset_id], seconds=max(3.0, min(seconds, 600.0)), names={asset_id: name})
        if format == "edl":
            return PlainTextResponse(story.edl(system.vi, cut, title=Path(name).stem), media_type="text/plain; charset=utf-8",
                                     headers={"content-disposition": f'attachment; filename="{Path(name).stem}_{int(seconds)}s.edl"'})
        if format == "md":
            return PlainTextResponse(story.markdown(told, cut, name=name), media_type="text/markdown; charset=utf-8")
        return {"story": told, "recut": cut}

    @app.post("/api/v1/recut")
    def recut_many(body: dict):
        """A proposal for cutting several recordings together, in the order given, to `seconds`; `format` json or edl."""
        from fastapi.responses import PlainTextResponse
        from nexora.modules.intelligence import story
        ids = [a for a in body.get("assets", []) if system.assets.asset(a) is not None]
        if not ids:
            raise HTTPException(422, "Cần ít nhất một clip có thật")
        names = {a: Path(system.assets.original(a).relative_path).name for a in ids}
        cut = system.intelligence.recut(system.vi, ids, seconds=max(3.0, min(float(body.get("seconds", 30)), 600.0)), names=names)
        if body.get("format") == "edl":
            return PlainTextResponse(story.edl(system.vi, cut, title=str(body.get("title") or "NEXORA")), media_type="text/plain; charset=utf-8")
        return cut

    @app.post("/api/v1/assets/{asset_id}/follow")
    def follow(asset_id: str):
        """Follow what a recording shows into things, subjects and sound sources of the library again, from what is kept."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        return system.intelligence.follow(asset_id)

    @app.post("/api/v1/assets/{asset_id}/retell")
    def retell(asset_id: str):
        """Build the beats' texts again from what the model already said, after the way answers are cleaned has changed."""
        if system.assets.asset(asset_id) is None:
            raise HTTPException(404, "no such asset")
        return {"retold": system.intelligence.retell(asset_id)}

    @app.get("/api/v1/moments/{moment_id}/alike")
    def alike(moment_id: str, limit: int = 8):
        """Stretches anywhere in the library whose pictures look like this one (Apple's feature print, design group 15)."""
        moment = system.index.by_id(moment_id)
        if moment is None:
            raise HTTPException(404, "no such moment")
        out = []
        for score, asset_id, a, b in system.vi.alike(moment.asset_id, moment.t_start, moment.t_end, limit=limit):
            m = system.index.get(asset_id, "segment", a, b)
            if m is not None:
                out.append({**moment_view(m, score), "asset": asset_brief(asset_id)})
        return {"alike": out}

    @app.get("/api/v1/assets/{asset_id}/scenes")
    def shoot_scenes(asset_id: str):
        """The scenes this recording passes through, with the other recordings of its shoot each one spans (design group 03)."""
        need_asset(asset_id)
        scenes, seen = [], set()
        for seg in system.vi.segments(asset_id, "scene"):
            if seg.data["scene"] not in seen:
                seen.add(seg.data["scene"])
                scenes.append({"number": seg.data["scene"], "name": seg.data["name"], "why": seg.data["why"], "assets": seg.data["assets"],
                               "beats": [{"asset_id": asset_id, "start": seg.t_start, "end": seg.t_end}]})
        shoot = system.intelligence.profiler.shoot_of(asset_id) if system.intelligence.profiler else [asset_id]
        return {"assets": sorted(set(shoot) | {a for s in scenes for a in s["assets"]}), "scenes": scenes}

    @app.get("/api/v1/insights/footage")
    def insights_footage():
        from nexora.app import footage_insights
        return footage_insights(system)

    def entity_view(e: dict) -> dict:
        return {"key": e["key"], "name": e["name"] or (e["data"].get("name") if e["kind"] == "place" else None), "faces": len(e["appearances"]), "beats": len(e["appearances"]),
                "assets": sorted({a["asset_id"] for a in e["appearances"]}), "appearances": e["appearances"][:40], "confidence": e["data"].get("confidence", "medium")}

    @app.get("/api/v1/people")
    def people():
        """The people of the library, faces grouped by likeness, with the names the operator gave (design group 06)."""
        return {"people": sorted((entity_view(e) for e in system.vi.entities("person")), key=lambda p: -p["faces"])}

    @app.get("/api/v1/places")
    def places():
        """Places seen in the library, grouped across shots and recordings by how alike their pictures look (design group 06)."""
        return {"places": sorted((entity_view(e) for e in system.vi.entities("place")), key=lambda p: (-len(p["assets"]), -p["beats"]))}

    @app.post("/api/v1/people/name")
    def name_person(body: dict):
        system.intelligence.name_person(str(body.get("key", "")), str(body.get("name", "")))
        return people()

    @app.get("/api/v1/assets/{asset_id}/profile")
    def asset_profile(asset_id: str):
        known = system.vi.recording(asset_id)
        whole = ((known or {}).get("summary") or {}).get("profile")
        if not whole:
            raise HTTPException(404, "Footage này chưa được đo và nhận diện")
        spans = [s.data for s in system.vi.segments(asset_id, "span") if s.data.get("type") == "text"]
        return {"asset": whole, "text_spans": spans, "recognised": bool(system.vi.observations(asset_id, "people")),
                "beats": [{"start": b.t_start, "end": b.t_end} for b in system.vi.segments(asset_id, "beat")], "analysed": system.vi.analysed(asset_id)}

    @app.get("/api/v1/evaluation")
    def evaluation():
        names = {a["asset_id"]: Path(system.assets.path_of(system.assets.original(a["asset_id"]))).name for a in system.assets.assets()}
        marked = [{"asset_id": asset_id, "name": names.get(asset_id, asset_id), "shots": len(marks["shot"]), "beats": len(marks["beat"])}
                  for asset_id, marks in system.evaluation.references().items()]
        return {"cases": system.evaluation.cases(), "runs": system.evaluation.runs(), "structure": {"references": marked, "runs": system.evaluation.structure_runs()}}

    @app.post("/api/v1/evaluation/structure/run")
    def run_structure_evaluation():
        from nexora.app import structure_config
        system.evaluation.run_structure(structure_config(system))
        return evaluation()

    @app.post("/api/v1/evaluation/cases", status_code=201)
    def add_case(body: dict):
        """Keep an accepted clip as a known right answer: the line of a shot and the stretch chosen for it."""
        if body.get("moment_id"):                 # chosen by hand: "for these words, this is the right stretch", whatever the system would have proposed
            moment, line = system.index.by_id(str(body["moment_id"])), str(body.get("line", "")).strip()
            if moment is None or not line:
                raise HTTPException(422, "Cần một câu và một cảnh có thật")
            return {"case_id": system.evaluation.add_case(line, moment.asset_id, moment.t_start, moment.t_end), "cases": len(system.evaluation.cases()), "by_hand": True}
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

    from nexora.api.notes import add_notes
    add_notes(app, system.data_dir)                  # notes pinned to a moment of a recording or a cut
    from nexora.api.catalog import add_catalog
    add_catalog(app, system)                         # one code and one name for every item in the library

    if web_dir and Path(web_dir).is_dir():
        app.mount("/assets", StaticFiles(directory=Path(web_dir) / "assets"), name="web-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            # The page names the build's script files, so it is asked for afresh every time: a new build shows at the next load.
            # The script files themselves carry their content's hash in their name and may be kept.
            return FileResponse(Path(web_dir) / "index.html", headers={"cache-control": "no-cache"})

    return app
