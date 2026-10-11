"""The minimal API of slice 2."""
import pytest
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build


@pytest.fixture
def client_and_system(tmp_path):
    system = build(tmp_path / "data")
    return TestClient(create_app(system)), system


def test_register_starts_an_ingest_run_and_the_run_can_be_followed(client_and_system, plain_clip):
    client, system = client_and_system
    r = client.post("/api/v1/assets/register", json={"path": str(plain_clip)})
    assert r.status_code == 202
    body = r.json()
    run = client.get(f"/api/v1/runs/{body['run_id']}").json()
    assert run["status"] == "queued" and [s["stage_key"] for s in run["stages"]][0] == "checksum"
    while system.worker.run_once():
        pass
    run = client.get(f"/api/v1/runs/{body['run_id']}").json()
    assert run["status"] == "succeeded" and all(s["status"] == "succeeded" for s in run["stages"])
    assets = client.get("/api/v1/assets").json()
    assert assets[0]["asset_id"] == body["asset_id"] and "proxy" in assets[0]["roles"]


def test_registering_a_path_that_does_not_exist_is_rejected(client_and_system, tmp_path):
    client, _ = client_and_system
    assert client.post("/api/v1/assets/register", json={"path": str(tmp_path / "nope.mp4")}).status_code == 404


def test_an_unknown_run_is_not_found(client_and_system):
    client, _ = client_and_system
    assert client.get("/api/v1/runs/run_missing").status_code == 404
