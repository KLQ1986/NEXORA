"""Golden labels and the gate each field must pass before matching and search may rely on it (design 2026-10-14, section 8)."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeSound, FakeVision


def drain(system):
    while system.worker.run_once():
        pass


def test_a_field_right_on_enough_labels_is_released_and_one_that_falls_back_is_withdrawn(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=12))
    drain(system)
    beats = system.index.moments(asset, level="segment")
    assert len(beats) >= 5
    for beat in beats:
        system.fields.label(asset, beat.t_start, beat.t_end, "people", "một")
        system.fields.label(asset, beat.t_start, beat.t_end, "shot_size", "cận")
        system.fields.label(asset, beat.t_start, beat.t_end, "place", "trong nhà")       # the recogniser says outdoors: wrong every time
    first = system.fields.measure({})["fields"]
    assert first["people"]["accuracy"] == 1.0 and first["place"]["accuracy"] == 0.0
    # Fewer than ten labels: right every time, still on trial.
    assert first["people"]["status"] == "trial" and first["people"]["answered"] == len(beats)
    for k in range(10 - len(beats)):
        system.fields.label(asset, beats[k % len(beats)].t_start + 0.01 * (k + 1), beats[k % len(beats)].t_end, "people", "một")
    second = system.fields.measure({})["fields"]
    assert second["people"]["status"] == "released" and system.fields.released() == {"people"} | ({"shot_size"} if second["shot_size"]["status"] == "released" else set())
    assert second["place"]["status"] == "trial" and second["place"]["mistakes"][0]["held"] == "ngoài trời"
    assert second["people"]["calibration"]["high"]["share"] == 1.0
    for row in system.fields.labels(asset):
        if row["field"] == "people":
            system.fields.label(asset, row["t_start"], row["t_end"], "people", "không")       # the operator corrects every label: now all wrong
    third = system.fields.measure({})["fields"]
    assert third["people"]["status"] == "withdrawn"
    assert {r["field"] for r in system.fields.regressions()} == {"people"}


def test_labels_are_given_and_read_through_the_api_and_an_unknown_value_is_refused(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=4))
    drain(system)
    api = TestClient(create_app(system))
    made = api.post(f"/api/v1/assets/{asset}/golden", json={"labels": [{"t_start": 0, "t_end": 2, "field": "shot_size", "value": "cận"}]})
    assert made.status_code == 201 and len(made.json()["labels"]) == 1
    assert api.post(f"/api/v1/assets/{asset}/golden", json={"labels": [{"t_start": 0, "t_end": 2, "field": "shot_size", "value": "rất gần"}]}).status_code == 422
    report = api.post("/api/v1/fields/measure").json()
    shot = next(f for f in report["fields"] if f["field"] == "shot_size")
    assert shot["accuracy"] == 1.0 and shot["status"] == "trial" and report["labels"] == 1
    assert api.get(f"/api/v1/assets/{asset}/profile").json()["beats"]
    assert api.post(f"/api/v1/assets/{asset}/profile").status_code == 202


def test_a_line_asking_for_a_close_shot_lifts_a_close_beat_only_once_the_field_is_released():
    from types import SimpleNamespace
    from nexora.modules.sourcing.match import asked, label_fit, spread
    assert asked("Cận cảnh tay pha cà phê") == {"shot_size": "cận"}
    assert asked("Toàn cảnh bãi biển vắng người") == {"shot_size": "toàn", "people": "không"}
    assert asked("Cô ấy nói trước camera trong phòng") == {"place": "trong nhà", "speaker": "trong khung"}
    close, wide = {"profile": {"shot_size": {"value": "cận"}}}, {"profile": {"shot_size": {"value": "toàn"}}}
    assert label_fit({"shot_size": "cận"}, close, set()) == (0.0, [])                       # on trial: not relied on
    assert label_fit({"shot_size": "cận"}, close, {"shot_size"})[0] > 0 > label_fit({"shot_size": "cận"}, wide, {"shot_size"})[0]
    hit = lambda asset, a, b: SimpleNamespace(moment=SimpleNamespace(asset_id=asset, t_start=a, t_end=b))
    kept = spread([hit("x", 0, 4), hit("x", 4, 8), hit("y", 0, 4), hit("x", 20, 24)], 3)
    assert [(h.moment.asset_id, h.moment.t_start) for h in kept] == [("x", 0), ("y", 0), ("x", 20)]


def test_a_field_that_gives_no_value_on_the_hard_cases_is_not_released(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=8))
    drain(system)
    beats = system.index.moments(asset, level="segment")
    for k in range(12):
        b = beats[k % len(beats)]
        system.fields.label(asset, b.t_start + 0.001 * k, b.t_end, "speaker", "trong khung")       # nobody speaks: the field never answers
    result = system.fields.measure({})["fields"]["speaker"]
    assert result["coverage"] == 0.0 and result["status"] == "trial"
    assert system.fields.measure({})["fields"]["model.co_canh"]["labels"] == 0


def test_pictures_alike_and_the_scenes_of_a_shoot_are_served(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    a, _ = system.library.ingest(make_video(tmp_path / "shoot" / "a.mp4", picture=4))
    b, _ = system.library.ingest(make_video(tmp_path / "shoot" / "b.mp4", picture=4))
    drain(system)
    api = TestClient(create_app(system))
    first = system.index.moments(a, level="segment")[0]
    alike = api.get(f"/api/v1/moments/{first.moment_id}/alike").json()["alike"]
    assert alike and alike[0]["score"] > 0.99
    scenes = api.get(f"/api/v1/assets/{a}/scenes").json()
    assert set(scenes["assets"]) == {a, b}
