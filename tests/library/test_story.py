"""How a recording tells its story, and a proposal for cutting it again, as a plan and an edit decision list."""
import re

from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.modules.intelligence import story

from tests.fakes import FakeModel, FakePictures, FakeSound, FakeSpeech, FakeVision
from tests.library.test_sync import camera, room_sound


def drain(system):
    while system.worker.run_once():
        pass


def test_a_beat_is_trimmed_to_its_action_or_around_its_best_frame():
    beat = {"t_start": 0.0, "t_end": 10.0, "moving": (2.0, 4.5), "best_frame": 8.0}
    assert story._window(beat, 4.0) == (2.0, 4.5)
    assert story._window({**beat, "moving": None}, 4.0) == (6.0, 10.0)               # around the best frame, kept inside the beat
    assert story._window({**beat, "moving": None, "best_frame": None}, 4.0) == (3.0, 7.0)


def test_a_recording_has_a_story_and_a_recut_that_opens_on_its_strongest_moment_and_reads_in_an_editor(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()], speech=FakeSpeech(), pictures=FakePictures())
    asset, _ = system.library.ingest(camera(tmp_path / "talk.mp4", room_sound(tmp_path / "s.wav", 1), seconds=6))
    drain(system)
    client = TestClient(create_app(system))
    made = client.get(f"/api/v1/assets/{asset}/story", params={"seconds": 4}).json()
    told, cut = made["story"], made["recut"]
    assert told["beats"] and all(b["role"] in story.ROLES for b in told["beats"]) and told["beats"][0]["role"] in ("mở đầu", "thiết lập")
    assert len(told["arc"]) == len(told["beats"]) and max(told["arc"]) == told["beats"][told["peak"] - 1]["energy"]
    assert cut["plan"] and cut["plan"][0]["role"] == "mở (hook)" and cut["plan"][0]["seconds"] <= story.HOOK_SECONDS + 0.01
    assert cut["plan"][-1]["role"] == "kết" and cut["dropped"]                     # 4 seconds do not need every beat
    assert all(p["seconds"] <= cut["longest_shot"] + 0.01 for p in cut["plan"]) and [p["order"] for p in cut["plan"]] == list(range(1, len(cut["plan"]) + 1))
    assert abs(sum(p["seconds"] for p in cut["plan"]) - cut["seconds"]) < 0.05
    edl = client.get(f"/api/v1/assets/{asset}/story", params={"seconds": 4, "format": "edl"})
    assert edl.status_code == 200 and edl.text.startswith("TITLE: ") and "FCM: " in edl.text
    events = [l for l in edl.text.splitlines() if re.match(r"^\d{3}  ", l)]
    assert len(events) == len(cut["plan"])
    assert all(re.match(r"^\d{3}  AX       AA/V  C        (\d\d:\d\d:\d\d[:;]\d\d ){3}\d\d:\d\d:\d\d[:;]\d\d$", l) for l in events)
    page = client.get(f"/api/v1/assets/{asset}/story", params={"format": "md"}).text
    assert page.startswith("# Kể chuyện và dựng lại") and "## Câu chuyện của clip" in page
    assert client.post("/api/v1/recut", json={"assets": ["nope"]}).status_code == 422
    together = client.post("/api/v1/recut", json={"assets": [asset], "seconds": 4}).json()
    assert together["target"] == 4 and together["plan"] == cut["plan"]
