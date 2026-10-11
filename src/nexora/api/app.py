"""The HTTP API (design v4.0, section 25). It holds no business logic: it validates and delegates."""
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".ogv"}


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
        "thumbnail_url": f"/media/{by_role['thumbnail'].version_id}" if "thumbnail" in by_role else None,
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
            files = sorted(f for f in root.rglob("*") if f.suffix.lower() in VIDEO_EXT and not f.name.startswith("."))
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
        return {"kill_switch": system.orch.kill_switch()}

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

    if web_dir and Path(web_dir).is_dir():
        app.mount("/assets", StaticFiles(directory=Path(web_dir) / "assets"), name="web-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            return FileResponse(Path(web_dir) / "index.html")

    return app
