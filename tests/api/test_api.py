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


def test_registering_a_folder_ingests_every_video_in_it(client_and_system, tmp_path):
    from tests.conftest import make_video
    client, system = client_and_system
    folder = tmp_path / "shoot"; folder.mkdir()
    make_video(folder / "a.mp4", picture=1); make_video(folder / "b.mp4", picture=1); (folder / "notes.txt").write_text("x")
    r = client.post("/api/v1/assets/register", json={"path": str(folder)})
    assert r.status_code == 202 and len(r.json()["registered"]) == 2


def test_library_lists_assets_with_what_the_screen_needs_and_serves_their_media(client_and_system, clip_with_black_tail):
    client, system = client_and_system
    client.post("/api/v1/assets/register", json={"path": str(clip_with_black_tail)})
    while system.worker.run_once():
        pass
    item = client.get("/api/v1/library").json()["assets"][0]
    assert item["name"] == "tail.mp4" and item["ingest"]["status"] == "succeeded" and item["online"] is True
    assert item["duration"] > 3 and len(item["black_ranges"]) == 1 and len(item["ingest"]["stages"]) == 5
    thumb = client.get(item["thumbnail_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    part = client.get(item["proxy_url"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert client.get("/media/ver_missing").status_code == 404


def test_environment_reports_tools_and_free_disk(client_and_system):
    client, _ = client_and_system
    env = client.get("/api/v1/environment").json()
    assert env["ffmpeg"]["filters"]["blackdetect"] is True and env["disk"]["free_bytes"] > 0
