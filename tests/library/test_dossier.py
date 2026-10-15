"""The dossier of a recording: everything learnt about it in one place, with a word on every beat."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.core.intelligence import Value
from nexora.modules.intelligence import dossier

from tests.fakes import FakeModel, FakePictures, FakeSound, FakeSpeech, FakeVision
from tests.library.test_sync import camera, room_sound


def drain(system):
    while system.worker.run_once():
        pass


def _v(field, value, source="measured", evidence=None):
    return Value(field, value, source, "high", True, evidence or {}, "test")


def test_a_beats_picture_is_graded_from_what_was_measured():
    assert dossier.picture_grade({"shake": _v("shake", "good"), "sharpness": _v("sharpness", "good")}) == ("dùng được", [])
    assert dossier.picture_grade({"shake": _v("shake", "fair")}) == ("dùng tạm", ["hơi rung"])
    assert dossier.picture_grade({"exposure": _v("exposure", "poor", evidence={"fault": "burnt"}), "horizon": _v("horizon", "nghiêng")}) == \
        ("lỗi", ["cháy sáng", "đường chân trời nghiêng"])
    assert dossier.sound_grade({"clipping": _v("clipping", True)}) == ("lỗi", ["tiếng bị méo"])
    assert dossier.sound_grade({"wind": _v("wind", True), "loudness": _v("loudness", -50.0)}) == ("dùng tạm", ["có tiếng gió", "tiếng rất nhỏ (-50 LUFS)"])


def test_what_a_beat_could_serve_as_follows_its_size_movement_and_words():
    wide_still = {"shot_size": _v("shot_size", "toàn"), "camera": _v("camera", "static")}
    assert "cảnh thiết lập (mở đầu một đoạn)" in dossier.uses_of(wide_still, first=True, last=False, speech=False)
    talking = {"shot_size": _v("shot_size", "trung"), "speaker": _v("speaker", "trong khung")}
    assert dossier.uses_of(talking, first=False, last=False, speech=True) == ["đoạn nói trước máy"]
    assert "dẫn vào chủ thể" in dossier.uses_of({"camera": _v("camera", "push_in")}, first=False, last=False, speech=False)
    said_by_a_model = {"shot_size": _v("shot_size", "cận", source="model")}
    assert "cảnh chèn chi tiết" not in dossier.uses_of(said_by_a_model, first=False, last=False, speech=False)


def test_the_dossier_of_an_analysed_recording_gathers_it_all_and_reads_as_a_page(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()], speech=FakeSpeech(), pictures=FakePictures())
    asset, _ = system.library.ingest(camera(tmp_path / "talk.mp4", room_sound(tmp_path / "s.wav", 1), seconds=6))
    drain(system)
    made = dossier.build(system.vi, asset, name="talk.mp4")
    assert made["recording"]["duration"] and made["recording"]["width"] and made["beats"]
    beat = made["beats"][0]
    assert beat["picture"]["grade"] in dossier.GRADES and beat["sound"]["grade"] in dossier.GRADES and beat["uses"]
    assert "Thấy:" not in beat["description"]                      # the lists have lines of their own
    assert made["speech"] and made["analysis"]["analysed"]["describe"] == "v4" and made["analysis"]["out_of_date"] == []
    v = made["verdict"]
    assert abs(v["usable_seconds"] + v["careful_seconds"] + v["unusable_seconds"] - sum(b["seconds"] for b in made["beats"])) < 0.01

    client = TestClient(create_app(system))
    assert client.get(f"/api/v1/assets/{asset}/dossier").json()["asset_id"] == asset
    page = client.get(f"/api/v1/assets/{asset}/dossier", params={"format": "md"})
    assert page.status_code == 200 and page.text.startswith("# Hồ sơ") and "## Từng nhịp" in page.text and "cỡ cảnh" in page.text
    assert client.get("/api/v1/assets/nope/dossier").status_code == 404
