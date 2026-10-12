"""Edit: the rough cut from speech, clips that keep their own sound, per-shot treatment, previews."""
import subprocess

import pytest
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.core.states import RunStatus
from nexora.modules.edit.roughcut import plan

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeSpeech, FakeVoice
from tests.library.test_sync import camera, room_sound


def drain(system):
    while system.worker.run_once():
        pass


def probe(path, entries="format=duration", stream=None):
    args = ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0"] + (["-select_streams", stream] if stream else []) + [str(path)]
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def said(text, start):
    words, t = [], start
    for token in text.split():
        words.append({"text": token, "start": round(t, 2), "end": round(t + 0.4, 2), "p": 0.2 if token.strip(".,") == "ờ" else 0.9})
        t += 0.5
    return {"t_start": words[0]["start"], "t_end": words[-1]["end"], "text": text, "words": words}


def test_the_rough_cut_drops_fillers_and_earlier_takes_and_never_clips_a_word():
    entries = plan([said("ờ à", 0.5), said("hôm nay mình đi chợ", 2.0), said("hôm nay mình đi chợ Hội An.", 5.0), said("ờ cá ở đây rất tươi.", 9.0), said("cá", 12.0), said("cá ở chợ này rẻ lắm.", 13.0)], duration=16.0)
    assert [(e["keep"], e["reason"] and e["reason"][:12]) for e in entries] == [(False, "Chỉ có tiếng"), (False, "Câu này được"), (True, None), (True, None), (False, "Câu này được"), (True, None)]
    kept = [e for e in entries if e["keep"]]
    assert kept[1]["text"] == "cá ở đây rất tươi." and kept[1]["t_in"] == pytest.approx(9.5 - 0.12)          # the leading "ờ" is cut off with its time
    assert kept[0]["t_in"] == pytest.approx(4.88) and kept[0]["t_out"] == pytest.approx(8.6)                   # a handle before the first word and after the last
    assert kept[2]["t_out"] <= 16.0
    assert all(a["t_out"] <= b["t_in"] for a, b in zip(entries, entries[1:]))


@pytest.fixture
def talking(tmp_path):
    speech = FakeSpeech("hôm nay mình đi chợ | hôm nay mình đi chợ Hội An. | ờ cá ở đây rất tươi.")
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=4.0, speech=speech)
    asset, _ = system.library.ingest(camera(tmp_path / "noi.mp4", room_sound(tmp_path / "s.wav", 3), seconds=12))
    drain(system)
    return system, asset


def test_a_recording_is_cut_by_its_words_into_a_project_that_plays_its_own_sound(talking):
    system, asset = talking
    client = TestClient(create_app(system))
    outline = client.get(f"/api/v1/assets/{asset}/roughcut").json()
    assert [s["keep"] for s in outline["sentences"]] == [False, True, True] and outline["removed_seconds"] > 3
    view = client.post(f"/api/v1/assets/{asset}/roughcut", json={}).json()
    assert view["title"] == "Dựng thô: noi" and view["script"]["match_approved"]
    assert [(s["text"], s["selection"]["live_sound"], s["selection"]["status"]) for s in view["shots"]] == [("hôm nay mình đi chợ Hội An.", True, "accepted"), ("cá ở đây rất tươi.", True, "accepted")]
    assert client.post(f"/api/v1/projects/{view['project_id']}/render").status_code == 202
    drain(system)
    render = client.get(f"/api/v1/projects/{view['project_id']}").json()["renders"][0]
    ranges = [(s["selection"]["t_in"], s["selection"]["t_out"]) for s in view["shots"]]
    assert render["qc"]["passed"] and render["qc"]["duration"] == pytest.approx(sum(b - a for a, b in ranges), abs=0.3)      # as long as the kept speech, no padding
    assert [s["live_sound"] for s in render["qc"]["shots"]] == [True, True] and render["qc"]["mean_db"] > -60                # the room's sound is in the cut: no narration was made
    assert system.adapters.environment() is not None and not list((system.data_dir / "media" / "narration").glob("*.wav"))

    again = client.post(f"/api/v1/assets/{asset}/roughcut", json={"project_id": view["project_id"], "keep": [0, 2]}).json()   # the operator's own choice of sentences
    assert [s["text"] for s in again["shots"]] == ["hôm nay mình đi chợ", "cá ở đây rất tươi."] and again["script"]["version"] == 2
    assert client.post(f"/api/v1/assets/{asset}/roughcut", json={"keep": []}).status_code == 422


def test_speed_stabilising_colour_and_a_sound_effect_change_the_segment_and_only_that_segment(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=False)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20))
    effect, _ = system.library.ingest(room_sound(tmp_path / "clap.wav", 5, seconds=3))
    drain(system)
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["chợ rau củ", "cá tươi trên sạp"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)
    client.post(f"/api/v1/projects/{pid}/match/approve")
    client.post(f"/api/v1/projects/{pid}/render"); drain(system)
    segments = system.data_dir / "media" / "segments"
    before = {p.name for p in segments.glob("*.mp4")}
    quiet = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["qc"]["mean_db"]

    shots = client.get(f"/api/v1/projects/{pid}").json()["shots"]
    assert client.patch(f"/api/v1/shots/{shots[0]['shot_id']}/treatment", json={"speed": 1.9, "stabilise": True, "sfx": effect}).json() == {"ok": True}
    sel = client.get(f"/api/v1/projects/{pid}").json()["shots"][0]["selection"]
    assert (sel["speed"], sel["stabilise"], sel["sfx"]) == (2.0, True, effect)                    # speed snaps to the steps on offer
    client.patch(f"/api/v1/projects/{pid}", json={"options": {"clean_audio": True, "bogus": True}})
    assert client.get(f"/api/v1/projects/{pid}").json()["options"] == {"clean_audio": True}
    client.post(f"/api/v1/projects/{pid}/render"); drain(system)
    after = {p.name for p in segments.glob("*.mp4")}
    render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]
    assert render["qc"]["passed"] and render["qc"]["shots"][0]["speed"] == 2.0 and render["qc"]["mean_db"] > quiet + 6          # the effect is heard
    assert len(after - before) == 2                                                               # the treated shot, and its neighbour because cleaning applies to every shot

    client.patch(f"/api/v1/projects/{pid}", json={"options": {"match_colour": True}})
    client.post(f"/api/v1/projects/{pid}/render"); drain(system)
    assert client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["qc"]["passed"]
    assert client.patch("/api/v1/shots/sht_missing/treatment", json={"speed": 2}).status_code == 409


def test_a_preview_is_quick_small_ungated_and_is_not_a_cut_to_approve(tmp_path):
    voice = FakeVoice()
    system = build(tmp_path / "data", model=FakeModel(), voice=voice, segment_seconds=2.0, judge=False)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20))
    drain(system)
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "format": "portrait", "lines": ["chợ rau củ", "tên lửa phóng lên quỹ đạo"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)                                    # not approved, and one line has no picture
    run = client.post(f"/api/v1/projects/{pid}/preview").json()["run_id"]
    drain(system)
    assert system.orch.run_status(run) is RunStatus.SUCCEEDED                                     # no gate
    view = client.get(f"/api/v1/projects/{pid}").json()
    assert view["renders"] == [] and view["render"] is None and view["preview"]["status"] == "succeeded"
    preview = view["previews"][0]
    assert preview["gaps"] == 1 and probe(system.projects.render(preview["render_id"])["path"], "stream=width,height,r_frame_rate", "v:0") == "360,640,15/1"
    assert not list((system.data_dir / "media" / "narration").glob("*.wav"))                      # no narration was recorded for it
    assert client.get("/api/v1/calendar").json()["projects"][0]["stage"] == "Có kịch bản"
    assert client.get(preview["url"]).status_code == 200
