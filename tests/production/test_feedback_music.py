"""What the operator's choices teach the matcher, and what is measured about a music track."""
import math
import struct
import wave

import pytest
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.modules.library.music import analyse, rank

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeVoice


def drain(system):
    while system.worker.run_once():
        pass


def test_a_clip_turned_down_for_a_line_is_not_offered_for_it_again_and_a_chosen_one_comes_first(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=False)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=40)); drain(system)
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["chợ rau củ"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)
    shot = client.get(f"/api/v1/projects/{pid}").json()["shots"][0]
    first, alternates = shot["selection"]["moment_id"], [a["moment_id"] for a in shot["selection"]["alternates"]]
    assert len(alternates) >= 2
    client.post(f"/api/v1/shots/{shot['shot_id']}/swap", json={"alternate": 1})                  # the operator prefers the second alternate
    assert client.get("/api/v1/sourcing/feedback").json()["counts"] == {"accepted": 1, "rejected": 1}

    other = client.post("/api/v1/projects", json={"title": "Chợ lần hai", "lines": ["Chợ rau củ", "cá tươi trên sạp"]}).json()["project_id"]       # the same words in another video
    client.post(f"/api/v1/projects/{other}/match"); drain(system)
    again = client.get(f"/api/v1/projects/{other}").json()["shots"][0]["selection"]
    offered = [again["moment_id"]] + [a["moment_id"] for a in again["alternates"]]
    assert again["moment_id"] == alternates[1] and first not in offered                              # the chosen clip leads; the one turned down is gone

    shot2 = client.get(f"/api/v1/projects/{other}").json()["shots"][1]
    shown = [shot2["selection"]["moment_id"]] + [a["moment_id"] for a in shot2["selection"]["alternates"]]
    client.post(f"/api/v1/shots/{shot2['shot_id']}/gap")                                           # "no clip fits": every one shown was turned down
    client.post(f"/api/v1/projects/{other}/match"); drain(system)
    retry = client.get(f"/api/v1/projects/{other}").json()["shots"][1]["selection"]
    assert not set(shown) & set([retry["moment_id"]] + [a["moment_id"] for a in retry["alternates"]])


def tone(path, *, seconds, bpm=None, level=0.8):
    """A track for tests: clicks at a tempo, or a steady quiet hum when no tempo is given."""
    rate, frames = 8000, []
    for i in range(int(rate * seconds)):
        t = i / rate
        if bpm:
            beat = (t * bpm / 60) % 1.0
            v = level * math.sin(2 * math.pi * 220 * t) * (1.0 if beat < 0.12 else 0.05)
        else:
            v = 0.08 * math.sin(2 * math.pi * 110 * t)
        frames.append(struct.pack("<h", int(v * 30000)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(b"".join(frames))
    return path


def test_tempo_and_liveliness_are_measured_from_the_sound(tmp_path):
    system = build(tmp_path / "data", voice=FakeVoice())
    fast, _ = system.library.ingest(tone(tmp_path / "nhanh.wav", seconds=20, bpm=120))
    calm, _ = system.library.ingest(tone(tmp_path / "em.wav", seconds=60))
    drain(system)
    quick, quiet = (system.assets.original(a).metadata["music"] for a in (fast, calm))
    assert quick["tempo"] in range(116, 125) and quick["pulse"] > 0.3 and quiet["tempo"] is None and quiet["energy"] == "êm" and quick["energy"] != "êm"
    assert analyse([0.0] * 10, 100)["tempo"] is None                                              # too short to say anything

    client = TestClient(create_app(system))
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["một câu " * 12, "hai câu " * 12, "ba câu " * 12, "bốn câu " * 12, "năm câu " * 12]}).json()["project_id"]
    plain = client.get(f"/api/v1/projects/{pid}/music/suggest").json()
    assert plain["seconds"] > 20 and [t["name"] for t in plain["tracks"]] == ["em.wav", "nhanh.wav"] and "không phải lặp" in plain["tracks"][0]["why"] and "sẽ lặp" in plain["tracks"][1]["why"]
    lively = client.get(f"/api/v1/projects/{pid}/music/suggest", params={"energy": quick["energy"]}).json()["tracks"]
    assert lively[0]["name"] == "nhanh.wav" and "120 nhịp" in lively[0]["why"].replace("119", "120").replace("121", "120")
    client.patch(f"/api/v1/assets/{calm}", json={"rejected": True})
    assert [t["name"] for t in client.get(f"/api/v1/projects/{pid}/music/suggest").json()["tracks"]] == ["nhanh.wav"]
    assert rank([{"duration": 10, "energy": "vừa", "lead_in": 5.0, "rating": 4, "tempo": None}], seconds=30)[0]["why"] == "ngắn hơn video, sẽ lặp 3 lần, nhịp vừa, vào chậm, 5 giây đầu gần như im, bạn chấm 4 sao"


def test_tracks_taken_in_before_music_was_measured_are_listened_to_once_more(tmp_path):
    system = build(tmp_path / "data", voice=FakeVoice())
    track, _ = system.library.ingest(tone(tmp_path / "cu.wav", seconds=12, bpm=100))
    drain(system)
    original = system.assets.original(track)
    system.assets.update_metadata(original.version_id, music=None)             # as an older version left it
    assert system.library.suggest_music(seconds=10) == []
    assert len(system.library.measure_unmeasured_music()) == 1
    drain(system)
    assert system.assets.original(track).metadata["music"]["tempo"] in range(96, 105) and system.library.suggest_music(seconds=10)[0]["name"] == "cu.wav"
    assert system.library.measure_unmeasured_music() == []                     # nothing left to measure


def test_a_clip_is_moved_so_that_it_does_not_run_across_a_cut():
    from nexora.modules.sourcing.match import clear_of_cuts
    assert clear_of_cuts(2.0, 5.0, []) == (2.0, 5.0) and clear_of_cuts(2.0, 5.0, [1.0, 9.0]) == (2.0, 5.0)           # no cut inside: left alone
    assert clear_of_cuts(2.0, 5.0, [4.5]) == (1.35, 4.35)                       # most of it lies before the cut: it ends just before the cut
    assert clear_of_cuts(2.0, 5.0, [2.5], ceiling=20.0) == (2.65, 5.65)         # most of it lies after: it starts just after
    assert clear_of_cuts(2.0, 5.0, [4.5], floor=0.0) == (1.35, 4.35) and clear_of_cuts(0.5, 3.5, [3.0], ceiling=20.0) == (3.15, 6.15)   # no room before: it goes after
    assert clear_of_cuts(2.0, 5.0, [1.5, 4.0, 6.0], ceiling=20.0) == (2.0, 5.0)  # shots too short on both sides for the line: left where it was
    assert clear_of_cuts(2.0, 5.0, [4.95]) == (2.0, 5.0)                        # a cut at the very edge is not inside
