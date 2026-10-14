"""Library: what the operator knows about silent footage, frame-level detail, speech with a time for every word,
shoots, footage set aside, and where each clip is used."""
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.core.states import RunStatus
from nexora.modules.library.transcribe import sentences

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeSpeech
from tests.library.test_sync import camera, room_sound


def drain(system):
    while system.worker.run_once():
        pass


class Recording(FakeModel):
    """Remembers every prompt it was shown."""

    def __init__(self):
        super().__init__()
        self.prompts = []

    def submit(self, request):
        self.prompts.append(request.params.get("prompt", ""))
        return super().submit(request)


def test_the_shoot_the_date_and_the_operators_note_reach_the_description_and_a_changed_note_asks_again(tmp_path):
    model = Recording()
    system = build(tmp_path / "data", model=model, segment_seconds=2.0)
    asset, _ = system.library.ingest(make_video(tmp_path / "Hoi An thang 3" / "C0012.mp4", picture=4))
    drain(system)
    described = [p for p in model.prompts if "khung hình liên tiếp" in p]
    assert len(described) == 2 and all("Tên file: C0012.mp4" in p and "Thư mục (buổi quay): Hoi An thang 3" in p for p in described)
    assert not any("Ghi chú của người quay" in p for p in described)

    system.library.annotate(asset, note="Bà Tư bán cao lầu ở chợ Hội An")
    assert system.index.search("cao lầu", level=("segment", "note"))[0].moment.level == "note"       # found by the note at once
    model.prompts.clear()
    system.library.understand(asset, force=True)
    drain(system)
    again = [p for p in model.prompts if "khung hình liên tiếp" in p]
    assert len(again) == 2 and all("Ghi chú của người quay: Bà Tư bán cao lầu" in p for p in again)       # the old answers were to another question
    model.prompts.clear()
    system.library.understand(asset, force=True)
    drain(system)
    assert not [p for p in model.prompts if "khung hình liên tiếp" in p]                                  # same note: cached

    system.library.annotate(asset, note="")
    assert system.index.moments(asset, level="note") == []


def test_one_stretch_can_be_looked_at_frame_by_frame(tmp_path):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, segment_seconds=4.0)
    asset, _ = system.library.ingest(make_video(tmp_path / "a.mp4", picture=8))
    drain(system)
    segment = system.index.moments(asset, level="segment")[0]
    looked = model.calls["describe"]
    made = system.library.deepen(segment.moment_id)
    frames = system.index.moments(asset, level="frame")
    assert len(made) == len(frames) == len(segment.data["frames"]) == model.calls["describe"] - looked
    assert all(segment.t_start <= f.t_start < f.t_end <= segment.t_end for f in frames) and [f.t_start for f in frames] == sorted(f.t_start for f in frames)
    assert system.index.without_vectors(asset) == []
    assert system.index.search("cá tươi", level="frame") and len(system.index.moments(asset, level="segment")) == 2      # segments untouched
    with pytest.raises(ValueError):
        system.library.deepen(frames[0].moment_id)


def test_words_are_grouped_into_sentences_at_a_stop_a_pause_or_when_they_run_long():
    word = lambda text, start: {"text": text, "start": start, "end": start + 0.3, "p": 0.9}
    made = sentences([word("một", 0.0), word("hai.", 0.4), word("ba", 0.8), word("bốn", 2.5), *[word("năm", 3.0 + i * 0.4) for i in range(30)]])
    assert [s["text"] for s in made[:3]] == ["một hai.", "ba", "bốn " + " ".join(["năm"] * 19)]
    assert (made[0]["t_start"], made[0]["t_end"]) == (0.0, 0.7) and len(made) == 4
    clause = sentences([word("a,", 0.0), *[word("b", 0.4 * i) for i in range(1, 8)], word("c,", 3.2), word("d", 3.6)])
    assert [len(s["words"]) for s in clause] == [9, 1]                  # an early comma does not split; one after eight words does


def test_footage_with_sound_is_listened_to_and_what_was_said_is_searchable_while_silent_footage_is_left_alone(tmp_path):
    speech = FakeSpeech()
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=4.0, speech=speech)
    talking, _ = system.library.ingest(camera(tmp_path / "noi.mp4", room_sound(tmp_path / "s.wav", 1), seconds=8))
    silent, _ = system.library.ingest(make_video(tmp_path / "im.mp4", picture=4))
    drain(system)
    assert speech.calls == 1 and system.library.transcribe(silent) is None
    run = next(r for r in system.orch.runs_for_subject(talking) if system.orch.pipeline_of(r) == "library.transcribe")
    assert system.orch.run_status(run) is RunStatus.SUCCEEDED
    said = system.index.moments(talking, level="speech")
    assert [m.text for m in said] == ["chợ hội an buổi sáng rất đông.", "ờ cá tươi nằm trên sạp.", "cá tươi nằm trên sạp."]
    assert said[0].data["words"][0] == {"text": "chợ", "start": 0.5, "end": 0.9, "p": 0.95} and said[1].t_start == pytest.approx(6.0)
    assert system.assets.original(talking).metadata["speech"] == {"words": 18, "sentences": 3, "seconds": pytest.approx(6.4), "doubtful": 1,      # words brought in to where their sound is
                                                                   "language": "vi", "dropped": [], "voice_checked": False}
    hits = system.index.search("hội an buổi sáng", level=("segment", "speech"))
    assert hits[0].moment.level == "speech" and hits[0].moment.asset_id == talking
    assert system.index.search("hội an buổi sáng") == [] or all(h.moment.level == "segment" for h in system.index.search("hội an buổi sáng"))   # matching to pictures is unchanged

    speech.text = "một bản ghi khác."
    system.library.transcribe(talking, force=True)
    drain(system)
    assert [m.text for m in system.index.moments(talking, level="speech")] == ["một bản ghi khác."]         # listening again replaces, never piles up


def test_footage_set_aside_is_never_proposed_and_each_clip_knows_where_it_is_used(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, judge=False)
    client = TestClient(create_app(system))
    first, _ = system.library.ingest(make_video(tmp_path / "Buoi 1" / "a.mp4", picture=6))
    second, _ = system.library.ingest(make_video(tmp_path / "Buoi 2" / "b.mp4", picture=6, size="322x180"))
    drain(system)
    project = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["chợ rau củ"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{project}/match")
    drain(system)
    chosen = client.get(f"/api/v1/projects/{project}").json()["shots"][0]["selection"]["asset"]["asset_id"]
    library = {a["asset_id"]: a for a in client.get("/api/v1/library").json()["assets"]}
    other = second if chosen == first else first
    assert library[chosen]["used_in"] == [{"project_id": project, "title": "Chợ"}] and library[other]["used_in"] == []
    assert {library[first]["session"].split(",")[0], library[second]["session"].split(",")[0]} == {"Buoi 1", "Buoi 2"}
    sessions = client.get("/api/v1/library/sessions").json()["sessions"]
    assert sorted(s["session"].split(",")[0] for s in sessions) == ["Buoi 1", "Buoi 2"] and all(len(s["assets"]) == 1 and s["seconds"] == pytest.approx(6, abs=0.5) for s in sessions)

    assert client.patch(f"/api/v1/assets/{chosen}", json={"rejected": True}).json()["rejected"] is True
    assert all(h["asset"]["asset_id"] == other for h in client.get("/api/v1/library/search", params={"q": "chợ rau củ"}).json()["hits"])
    client.post(f"/api/v1/projects/{project}/match")
    drain(system)
    assert client.get(f"/api/v1/projects/{project}").json()["shots"][0]["selection"]["asset"]["asset_id"] == other
    assert client.patch(f"/api/v1/assets/{chosen}", json={"rating": 4}).json()["rejected"] is True            # another mark does not undo it


def test_frames_speech_and_reruns_are_reachable_through_the_api(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=4.0, speech=FakeSpeech())
    client = TestClient(create_app(system))
    asset, _ = system.library.ingest(camera(tmp_path / "noi.mp4", room_sound(tmp_path / "s.wav", 2), seconds=8))
    drain(system)
    moments = client.get(f"/api/v1/assets/{asset}/moments").json()
    assert len(moments["speech"]) == 3 and moments["speech"][0]["words"][0]["text"] == "chợ" and moments["frames"] == []
    frames = client.post(f"/api/v1/moments/{moments['segments'][0]['moment_id']}/deepen").json()["frames"]
    assert frames and frames[0]["level"] == "frame" and client.get(f"/api/v1/assets/{asset}/moments").json()["frames"]
    assert client.post(f"/api/v1/moments/{frames[0]['moment_id']}/deepen").status_code == 422
    view = next(a for a in client.get("/api/v1/library").json()["assets"] if a["asset_id"] == asset)
    assert view["speech"]["words"] == 18 and view["transcribe"]["status"] == "succeeded"
    assert client.post(f"/api/v1/assets/{asset}/transcribe").status_code == 202 and client.post(f"/api/v1/assets/{asset}/understand").status_code == 202
    assert [h["level"] for h in client.get("/api/v1/library/search", params={"q": "hội an buổi sáng rất đông"}).json()["hits"]][0] == "speech"


@pytest.mark.skipif(not shutil.which("whisper-cli") or not shutil.which("say"), reason="needs whisper.cpp and the macOS voice")
def test_the_real_speech_tool_hears_vietnamese_with_a_time_for_every_word(tmp_path):
    from pathlib import Path
    from nexora.adapters.speech import WhisperCpp
    from nexora.core.adapter import Request
    model = Path(__file__).resolve().parents[2] / "data" / "models" / "ggml-large-v3-turbo-q5_0.bin"
    if not model.is_file():
        pytest.skip("the speech model has not been downloaded")
    subprocess.run(["say", "-v", "Linh", "-o", str(tmp_path / "noi.aiff"), "Chợ Hội An buổi sáng rất đông."], check=True)
    adapter = WhisperCpp(model)
    assert adapter.environment()["model_present"]
    words = adapter.submit(Request("transcribe", inputs={"path": str(tmp_path / "noi.aiff")})).outputs["words"]
    heard = " ".join(w["text"].lower().strip(".,") for w in words)
    assert "buổi sáng" in heard and "đông" in heard
    assert all(0 <= a["start"] <= a["end"] <= b["end"] for a, b in zip(words, words[1:]))


def test_a_sentence_the_speech_model_invents_in_silence_is_taken_out_with_its_reason():
    from nexora.modules.library.transcribe import drop_invented, sentences
    words, t = [], 0.0
    for text in ["em đi đâu anh đi theo đó.", *["hãy subscribe cho kênh la school để không bỏ lỡ những video hấp dẫn."] * 4, "cá tươi nằm trên sạp."]:
        for token in text.split():
            words.append({"text": token, "start": t, "end": t + 0.3, "p": 0.9}); t += 0.3
        t += 1.0
    made = sentences(words)
    kept, dropped = drop_invented(made)
    assert [s["text"] for s in kept] == ["em đi đâu anh đi theo đó.", "cá tươi nằm trên sạp."]
    assert len(dropped) == 4 and all(d["reason"] for d in dropped)


def test_a_sentence_said_twice_by_a_person_stays_and_one_heard_without_any_voice_goes_only_when_the_model_was_unsure():
    from nexora.modules.library.transcribe import drop_invented
    said = [{"t_start": 0.0, "t_end": 1.0, "text": "ngon quá.", "words": [{"p": 0.9}]}, {"t_start": 1.5, "t_end": 2.5, "text": "ngon quá.", "words": [{"p": 0.9}]},
            {"t_start": 10.0, "t_end": 11.0, "text": "trăng bí bên này.", "words": [{"p": 0.3}]}, {"t_start": 12.0, "t_end": 13.0, "text": "chào anh.", "words": [{"p": 0.95}]}]
    windows = [{"t": t / 2, "d": 1.0, "top": [["speech", 0.9]] if t < 6 else [["wind", 0.8]]} for t in range(0, 28)]
    kept, dropped = drop_invented(said, windows)
    assert [s["text"] for s in kept] == ["ngon quá.", "ngon quá.", "chào anh."]
    assert [d["text"] for d in dropped] == ["trăng bí bên này."]


def test_words_are_brought_in_to_where_their_sound_is():
    from nexora.modules.library.transcribe import tighten
    envelope = [5.0] * 100 + [3000.0] * 30 + [5.0] * 2000 + [3000.0] * 40 + [5.0] * 100      # 100 per second: voice at 1.0-1.3 s and 21.3-21.7 s
    words = [{"text": "phim", "start": 0.9, "end": 21.0, "p": 0.9}, {"text": "đẹp", "start": 21.0, "end": 23.0, "p": 0.9}]
    out = tighten(words, envelope, 100)
    assert out[0]["start"] == pytest.approx(1.0) and out[0]["end"] == pytest.approx(1.3)
    assert out[1]["start"] == pytest.approx(21.3) and out[1]["end"] == pytest.approx(21.7)
