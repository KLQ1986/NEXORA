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


def test_a_video_can_be_made_end_to_end_through_the_api(tmp_path):
    from tests.conftest import make_video
    from tests.fakes import FakeModel, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    client = TestClient(create_app(system))
    drain = lambda: [None for _ in iter(system.worker.run_once, False)]
    client.post("/api/v1/assets/register", json={"path": str(make_video(tmp_path / "f.mp4", picture=20))}); drain()

    hits = client.get("/api/v1/library/search", params={"q": "ca tuoi"}).json()["hits"]
    assert hits and "cá tươi" in hits[0]["text"] and client.get(hits[0]["frame_url"]).status_code == 200
    fixed = client.patch(f"/api/v1/moments/{hits[0]['moment_id']}", json={"text": "Mâm cá tươi trên sạp."}).json()
    assert fixed["source"] == "human"

    project = client.post("/api/v1/projects", json={"title": "Chợ sáng", "lines": ["cá tươi trên sạp", "bàn phím máy tính", "chợ rau củ"]}).json()
    pid = project["project_id"]
    assert client.post(f"/api/v1/projects/{pid}/render").status_code == 409            # nothing approved yet
    client.post(f"/api/v1/projects/{pid}/match"); drain()
    view = client.get(f"/api/v1/projects/{pid}").json()
    assert view["match"]["status"] == "waiting_review"
    assert [s["selection"]["status"] for s in view["shots"]] == ["proposed", "gap", "proposed"]
    third = view["shots"][2]
    assert client.post(f"/api/v1/shots/{third['shot_id']}/swap", json={"alternate": 0}).status_code == 200
    assert client.post(f"/api/v1/projects/{pid}/match/approve").json()["script"]["match_approved"] is True

    client.post(f"/api/v1/projects/{pid}/render"); drain()
    view = client.get(f"/api/v1/projects/{pid}").json()
    assert view["render"]["status"] == "waiting_review" and view["renders"][0]["qc"]["passed"]
    video = client.get(view["renders"][0]["url"], headers={"Range": "bytes=0-9"})
    assert video.status_code == 206
    assert client.post(f"/api/v1/projects/{pid}/render/decision", json={"approve": True}).json()["render"]["status"] == "succeeded"


def test_photographs_recorded_takes_and_desktop_notifications_are_reachable_through_the_api(tmp_path):
    import subprocess
    from PIL import Image
    from tests.fakes import FakeModel, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    client = TestClient(create_app(system))
    folder = tmp_path / "photos"; folder.mkdir()
    Image.new("RGB", (800, 600), (40, 90, 160)).save(folder / "one.png")
    assert len(client.post("/api/v1/assets/register", json={"path": str(folder)}).json()["registered"]) == 1
    [None for _ in iter(system.worker.run_once, False)]
    asset = client.get("/api/v1/library").json()["assets"][0]
    assert asset["still"] and client.get(asset["thumbnail_url"]).status_code == 200

    pid = client.post("/api/v1/projects", json={"title": "Giọng tôi", "lines": ["cá tươi trên sạp", "chợ rau củ"]}).json()["project_id"]
    assert client.patch(f"/api/v1/projects/{pid}", json={"narration_dir": str(tmp_path / "missing")}).status_code == 404
    takes = tmp_path / "takes"; takes.mkdir()
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", str(takes / "2.wav")], check=True)
    assert client.patch(f"/api/v1/projects/{pid}", json={"narration_dir": str(takes)}).json()["own_takes"] == [2]

    assert client.get("/api/v1/control").json()["desktop_notifications"] is True
    assert client.post("/api/v1/control/desktop-notifications", json={"on": False}).json()["desktop_notifications"] is False
