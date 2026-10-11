"""The minimal API of slice 2."""
import json

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
    assert asset["ingest"]["status"] == "succeeded"                                # a photograph shows its progress like any footage

    pid = client.post("/api/v1/projects", json={"title": "Giọng tôi", "lines": ["cá tươi trên sạp", "chợ rau củ"]}).json()["project_id"]
    assert client.patch(f"/api/v1/projects/{pid}", json={"narration_dir": str(tmp_path / "missing")}).status_code == 404
    takes = tmp_path / "takes"; takes.mkdir()
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", str(takes / "2.wav")], check=True)
    assert client.patch(f"/api/v1/projects/{pid}", json={"narration_dir": str(takes)}).json()["own_takes"] == [2]

    assert client.get("/api/v1/control").json()["desktop_notifications"] is True
    assert client.post("/api/v1/control/desktop-notifications", json={"on": False}).json()["desktop_notifications"] is False


def test_inserts_framing_and_camera_angles_are_reachable_through_the_api(tmp_path):
    from tests.conftest import make_video
    from tests.fakes import FakeModel, FakeVoice
    from tests.library.test_sync import camera, room_sound
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    client = TestClient(create_app(system))
    drain = lambda: [None for _ in iter(system.worker.run_once, False)]
    sound = room_sound(tmp_path / "room.wav", 1)
    a = client.post("/api/v1/assets/register", json={"path": str(camera(tmp_path / "a.mp4", sound, seconds=20))}).json()["asset_id"]
    b = client.post("/api/v1/assets/register", json={"path": str(camera(tmp_path / "b.mp4", sound, skip=1.0, seconds=18))}).json()["asset_id"]
    drain()
    assert abs(client.post("/api/v1/assets/sync", json={"a": a, "b": b}).json()["offset"] + 1.0) < 0.1

    pid = client.post("/api/v1/projects", json={"title": "Hai máy", "lines": ["cá tươi trên sạp và con đường mòn"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain()
    shot = client.get(f"/api/v1/projects/{pid}").json()["shots"][0]
    sid, sel = shot["shot_id"], shot["selection"]
    assert client.post(f"/api/v1/shots/{sid}/inserts", json={"keyword": "máy bay"}).status_code == 422
    assert client.post(f"/api/v1/shots/{sid}/inserts", json={"keyword": "con đường mòn"}).status_code == 200
    client.post(f"/api/v1/shots/{sid}/focus", json={"x": 0.85})
    angle = sel["angles"][0]
    assert client.post(f"/api/v1/shots/{sid}/angle", json={"asset_id": angle["asset_id"]}).status_code == 200
    after = client.get(f"/api/v1/projects/{pid}").json()["shots"][0]["selection"]
    assert after["asset"]["asset_id"] == angle["asset_id"] and abs(after["t_in"] - angle["t_in"]) < 0.01
    assert [i["keyword"] for i in after["inserts"]] == ["con đường mòn"] and after["focus_x"] is None      # framing was for the other camera
    # A silent clip joins only now, so that the match above could only choose one of the two cameras.
    mute = client.post("/api/v1/assets/register", json={"path": str(make_video(tmp_path / "m.mp4", picture=4))}).json()["asset_id"]
    drain()
    assert client.post("/api/v1/assets/sync", json={"a": a, "b": mute}).status_code == 409


def test_the_operator_can_inspect_a_run_see_and_clean_storage_back_up_and_check_the_system(tmp_path):
    from tests.conftest import make_video
    from tests.fakes import FakeModel, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    client = TestClient(create_app(system))
    drain = lambda: [None for _ in iter(system.worker.run_once, False)]
    run_id = client.post("/api/v1/assets/register", json={"path": str(make_video(tmp_path / "f.mp4", picture=20))}).json()["run_id"]; drain()
    detail = client.get(f"/api/v1/runs/{run_id}/detail").json()
    assert [a["stage_key"] for a in detail["attempts"]][0] == "checksum" and all(a["seconds"] is not None for a in detail["attempts"])
    assert detail["events"][0]["kind"] == "run.submitted"

    pid = client.post("/api/v1/projects", json={"title": "Dọn", "lines": ["cá tươi trên sạp"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(); client.post(f"/api/v1/projects/{pid}/match/approve")
    client.post(f"/api/v1/projects/{pid}/render"); drain()
    stores = {s["key"]: s for s in client.get("/api/v1/storage").json()["stores"]}
    assert stores["segments"]["bytes"] > 0 and stores["renders"]["files"] == 1 and stores["orphan_renders"]["files"] == 0
    assert client.post("/api/v1/storage/clean", json={"keys": ["renders"]}).status_code == 422          # a project's render is never a cache
    assert client.post("/api/v1/storage/clean", json={"keys": ["segments", "orphan_renders"]}).json()["freed_bytes"] == stores["segments"]["bytes"]
    assert client.get(client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["url"]).status_code == 200
    client.post(f"/api/v1/projects/{pid}/render"); drain()                                               # the cache rebuilds itself
    assert client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["qc"]["passed"]

    assert client.post("/api/v1/storage/backup").json()["size"] > 0
    storage = client.get("/api/v1/storage").json()
    assert len(storage["backups"]) == 1 and storage["volumes"][0]["online"]
    assert client.post(f"/api/v1/volumes/{storage['volumes'][0]['volume_id']}/relink", json={"mount": str(tmp_path / "gone")}).status_code == 404
    names = [c["name"] for c in client.get("/api/v1/doctor").json()["checks"]]
    assert "Cơ sở dữ liệu" in names and "Công cụ ffmpeg" in names


def test_home_usage_capabilities_and_period_budgets(tmp_path):
    from tests.conftest import make_video
    from tests.fakes import FakeImageGen, FakeModel, FakeVideoGen, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, generators=[FakeImageGen(), FakeVideoGen()])
    client = TestClient(create_app(system))
    drain = lambda: [None for _ in iter(system.worker.run_once, False)]
    client.post("/api/v1/assets/register", json={"path": str(make_video(tmp_path / "f.mp4", picture=20))}); drain()
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["cá tươi trên sạp", "bàn phím máy tính"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain()

    home = client.get("/api/v1/home").json()
    assert [(a["name"], a["status"], a["link"]) for a in home["attention"]] == [("Chợ", "waiting_review", f"/du-an/{pid}")]
    assert home["attention"][0]["gaps"] == 1 and home["gaps"] == [] and home["counts"]["videos"] == 1 and home["counts"]["moments"] == 10
    caps = {c["pipeline"]: c for c in client.get("/api/v1/capabilities").json()["pipelines"]}
    assert caps["edit.render"]["available"] and caps["sourcing.generate"]["available"]

    tools = {(t["adapter"], t["operation"]): t for t in client.get("/api/v1/usage").json()["tools_all"]}
    assert tools[("model", "describe")]["calls"] >= 10 and tools[("ffmpeg", "proxy")]["failures"] == 0     # every call to a tool is on record

    client.post(f"/api/v1/projects/{pid}/match/approve"); client.post(f"/api/v1/projects/{pid}/render"); drain()
    assert client.post(f"/api/v1/projects/{pid}/render/decision", json={"approve": False, "comment": "0:03 cảnh cá bị rung"}).status_code == 200
    assert client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["review"]["comment"] == "0:03 cảnh cá bị rung"

    assert client.post("/api/v1/control/settings", json={"budget_day": -1}).status_code == 422
    assert client.post("/api/v1/control/settings", json={"budget_day": 0, "quiet_hours": "22-7", "notify_off": ["succeeded"]}).json()["budget_day"] == 0
    client.post(f"/api/v1/projects/{pid}/generate"); drain()
    run = client.get(f"/api/v1/projects/{pid}").json()["generate"]
    assert run["stages"][0]["blocked_reason"] == "daily_budget_exceeded"                                    # nothing paid starts once the day's budget is used
    assert any(a["reason"] == "daily_budget_exceeded" for a in client.get("/api/v1/home").json()["attention"])


def test_a_system_without_a_model_says_which_pipelines_it_cannot_run(tmp_path):
    client = TestClient(create_app(build(tmp_path / "data")))
    caps = {c["pipeline"]: c for c in client.get("/api/v1/capabilities").json()["pipelines"]}
    assert caps["library.ingest"]["available"] and caps["sourcing.match"]["missing"] == ["model"] and "voice" in caps["edit.render"]["missing"]


def test_ratings_collections_reordering_the_edit_list_and_the_change_stream(tmp_path):
    from tests.conftest import make_video
    from tests.fakes import FakeModel, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    client = TestClient(create_app(system))
    drain = lambda: [None for _ in iter(system.worker.run_once, False)]
    asset = client.post("/api/v1/assets/register", json={"path": str(make_video(tmp_path / "f.mp4", picture=20))}).json()["asset_id"]; drain()
    marked = client.patch(f"/api/v1/assets/{asset}", json={"rating": 9, "collections": ["Chợ", " chợ đêm ", "Chợ"]}).json()
    assert marked["rating"] == 5 and marked["collections"] == ["Chợ", "chợ đêm"]

    pid = client.post("/api/v1/projects", json={"title": "Đổi thứ tự", "lines": ["cá tươi trên sạp", "chợ rau củ", "bàn phím máy tính"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(); client.post(f"/api/v1/projects/{pid}/match/approve")
    before = client.get(f"/api/v1/projects/{pid}").json()
    ids = [s["shot_id"] for s in before["shots"]]
    assert client.post(f"/api/v1/projects/{pid}/reorder", json={"shot_ids": ids[:2]}).status_code == 422
    after = client.post(f"/api/v1/projects/{pid}/reorder", json={"shot_ids": [ids[1], ids[0], ids[2]]}).json()
    assert [s["text"] for s in after["shots"]] == ["chợ rau củ", "cá tươi trên sạp", "bàn phím máy tính"] and after["script"]["match_approved"]
    assert after["shots"][0]["selection"]["moment_id"] == before["shots"][1]["selection"]["moment_id"]      # each line kept its clip
    assert after["shots"][2]["selection"]["status"] == "gap" and after["script"]["version"] == before["script"]["version"] + 1

    client.post(f"/api/v1/projects/{pid}/render"); drain()
    render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]
    text = client.get(f"/api/v1/renders/{render['render_id']}/edl").text
    assert text.startswith("TITLE: Đổi thứ tự") and "001  AX       V     C" in text and "* FROM CLIP NAME: f.mp4" in text and "003  BL " in text
    assert text.splitlines()[3].endswith("00:00:00:00 " + "00:00:01:18") or " 00:00:00:00 " in text.splitlines()[3]

    assert client.get("/api/v1/events/stream", params={"once": True}).text.startswith("data: [")


def test_settings_templates_watch_folders_privacy_retry_notes_and_similar_moments(tmp_path):
    import os, time
    from nexora.app import scan_watch_folders
    from nexora.core.states import StageStatus
    from tests.conftest import make_video
    from tests.fakes import FakeModel, FakeStock, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, stock=FakeStock())
    client = TestClient(create_app(system))
    drain = lambda: [None for _ in iter(system.worker.run_once, False)]

    inbox = tmp_path / "inbox"; inbox.mkdir()
    assert client.post("/api/v1/settings", json={"watch_folders": [str(tmp_path / "nowhere")]}).status_code == 404
    assert client.post("/api/v1/settings", json={"watch_folders": [str(inbox)]}).json()["watch_folders"] == [str(inbox)]
    clip = make_video(inbox / "new.mp4", picture=20)
    assert scan_watch_folders(system) == []                                        # still fresh: it may be a copy in progress
    os.utime(clip, (time.time() - 60, time.time() - 60))
    assert scan_watch_folders(system) == [str(clip)] and scan_watch_folders(system) == []      # taken once
    drain()
    asset = client.get("/api/v1/library").json()["assets"][0]
    assert client.patch(f"/api/v1/assets/{asset['asset_id']}", json={"note": "Quay sáng thứ bảy ở chợ"}).json()["note"] == "Quay sáng thứ bảy ở chợ"
    first = client.get(f"/api/v1/assets/{asset['asset_id']}/moments").json()["segments"][1]
    alike = client.get(f"/api/v1/moments/{first['moment_id']}/similar").json()["hits"]
    assert alike and all(h["moment_id"] != first["moment_id"] for h in alike) and "cá tươi" in alike[0]["text"]

    names = [t["name"] for t in client.get("/api/v1/settings").json()["templates"]]
    pid = client.post("/api/v1/projects", json={"title": "Mẫu", "lines": ["cá tươi trên sạp", "bàn phím máy tính"]}).json()["project_id"]
    applied = client.post(f"/api/v1/projects/{pid}/template", json={"name": names[1]}).json()
    assert applied["format"] == "portrait" and applied["auto_accept"] and applied["template"] == names[1]

    client.post(f"/api/v1/projects/{pid}/match"); drain()
    kinds = [n["kind"] for n in client.get("/api/v1/notifications").json()["items"]]
    assert "gaps" in kinds                                                          # a script with a line nothing fits is announced
    gap = client.get(f"/api/v1/projects/{pid}").json()["shots"][1]["shot_id"]
    client.post("/api/v1/settings", json={"privacy_local_only": True})
    assert client.post(f"/api/v1/shots/{gap}/stock", json={"query": "keyboard"}).status_code == 503        # nothing leaves the machine in privacy mode
    client.post("/api/v1/settings", json={"privacy_local_only": False})
    assert client.post(f"/api/v1/shots/{gap}/stock", json={"query": "keyboard"}).json()["found"]

    from nexora.core.adapter import AdapterError, ErrorCode
    from nexora.core.pipeline import PipelineDefinition, StageDef
    broken = PipelineDefinition("t.broken", "1", [StageDef("only")])

    def refuse(ctx):
        raise AdapterError(ErrorCode.INVALID_REQUEST, "no", retryable=False)
    system.registry.register(broken, {"only": refuse})
    run = system.orch.submit_run(broken)
    drain()
    failed = next(s for s in system.orch.stages(run) if s.status is StageStatus.FAILED)
    assert client.post(f"/api/v1/stages/{failed.stage_id}/retry").status_code == 200
    assert next(s for s in system.orch.stages(run) if s.stage_id == failed.stage_id).status is StageStatus.READY


def test_structured_script_brand_profile_ideas_draft_and_health_notices(tmp_path):
    from nexora.app import watch_health
    from tests.conftest import make_video
    from tests.fakes import FakeModel, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    client = TestClient(create_app(system))
    drain = lambda: [None for _ in iter(system.worker.run_once, False)]
    footage = tmp_path / "card"; footage.mkdir()
    client.post("/api/v1/assets/register", json={"path": str(make_video(footage / "f.mp4", picture=20))}); drain()

    ideas = client.post("/api/v1/ideas").json()["ideas"]
    assert [i["title"] for i in ideas] == ["Cá tươi trên sạp buổi sớm", "Tàu vũ trụ"]                 # an idea with a stated risk goes last, whatever its score
    assert ideas[0]["scores"]["co_hinh"] >= 3 and ideas[1]["scores"]["co_hinh"] == 1                  # coverage is measured, not taken from the model
    assert client.get("/api/v1/ideas").json()["ideas"] == ideas

    pid = client.post("/api/v1/projects", json={"title": "Có cấu trúc", "lines": ["# Mở đầu", "con đường mòn", "# Ở chợ", "hàng hoá bày bán"]}).json()["project_id"]
    shots = client.get(f"/api/v1/projects/{pid}").json()["shots"]
    assert [(s["scene"], s["text"]) for s in shots] == [("Mở đầu", "con đường mòn"), ("Ở chợ", "hàng hoá bày bán")]
    client.patch(f"/api/v1/shots/{shots[1]['shot_id']}", json={"brief": "cá tươi trên sạp", "screen_text": "Chợ sáng"})
    client.post(f"/api/v1/projects/{pid}/match"); drain()
    after = client.get(f"/api/v1/projects/{pid}").json()["shots"]
    assert after[1]["brief"] == "cá tươi trên sạp" and after[1]["selection"]["status"] == "proposed" and "cá tươi" in after[1]["selection"]["reason"]   # the picture note found the clip
    kept = client.put(f"/api/v1/projects/{pid}/script", json={"lines": ["# Ở chợ", "hàng hoá bày bán", "con đường mòn"]}).json()["shots"]
    assert kept[0]["brief"] == "cá tươi trên sạp" and kept[0]["screen_text"] == "Chợ sáng"            # notes follow a line into the next version

    templates = client.get("/api/v1/settings").json()["templates"]
    templates[0].update(caption_scale=1.3, caption_position="top", pronounce={"sạp": "quầy"})
    client.post("/api/v1/settings", json={"templates": templates})
    assert json.loads(client.post(f"/api/v1/projects/{pid}/template", json={"name": templates[0]["name"]}).json()["profile"])["caption_position"] == "top"
    client.post(f"/api/v1/projects/{pid}/match"); drain(); client.post(f"/api/v1/projects/{pid}/match/approve")
    client.post(f"/api/v1/projects/{pid}/render"); drain()
    assert client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["qc"]["draft"] is False

    assert watch_health(system, min_free_bytes=0) == []
    (footage / "f.mp4").rename(tmp_path / "f.mp4"); footage.rmdir()                                   # the card is pulled out
    assert [k.split(":")[0] for k in watch_health(system, min_free_bytes=0)] == ["volume_offline"] and watch_health(system, min_free_bytes=0) == []
    assert client.get("/api/v1/notifications").json()["items"][0]["kind"] == "volume_offline"
    client.post(f"/api/v1/projects/{pid}/render"); drain()
    assert client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["qc"]["draft"] is True          # cut from proxies while the originals are away
