"""The HTTP API (design v4.0, section 25). It holds no business logic: it validates and delegates."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class RegisterRequest(BaseModel):
    path: str


def run_view(system, run_id: str) -> dict:
    info = system.orch.run_info(run_id)
    return {
        "run_id": run_id,
        "pipeline": info["pipeline_id"],
        "subject_ref": info["subject_ref"],
        "status": system.orch.run_status(run_id).value,
        "cost": system.orch.run_cost(run_id),
        "stages": [{"stage_key": s.stage_key, "status": s.status.value, "blocked_reason": s.blocked_reason,
                    "attempts": len(system.orch.attempts(s.stage_id)), "outputs": s.outputs}
                   for s in system.orch.stages(run_id)],
    }


def create_app(system) -> FastAPI:
    app = FastAPI(title="NEXORA", version="0.1.0")

    @app.post("/api/v1/assets/register", status_code=202)
    def register_asset(body: RegisterRequest):
        if not Path(body.path).is_file():
            raise HTTPException(404, f"no such file: {body.path}")
        asset_id, run_id = system.library.ingest(body.path)
        return {"asset_id": asset_id, "run_id": run_id}

    @app.get("/api/v1/assets")
    def list_assets():
        out = []
        for asset in system.assets.assets():
            versions = system.assets.versions(asset["asset_id"])
            original = next(v for v in versions if v.role == "original")
            out.append({**asset, "roles": [v.role for v in versions], "path": str(system.assets.path_of(original)),
                        "checksum": original.checksum, "metadata": original.metadata})
        return out

    @app.get("/api/v1/runs")
    def list_runs():
        return [run_view(system, run_id) for run_id in system.orch.runs()]

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        if system.orch.run_info(run_id) is None:
            raise HTTPException(404, f"no such run: {run_id}")
        return run_view(system, run_id)

    return app
