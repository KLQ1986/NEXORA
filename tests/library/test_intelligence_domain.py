"""Video Intelligence as a domain: what it learns about a recording is kept in the canonical model and read from there."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.conftest import make_video
from tests.fakes import FakeModel, FakePictures, FakeSound, FakeSpeech, FakeVision
from tests.library.test_sync import camera, room_sound


def drain(system):
    while system.worker.run_once():
        pass


def test_a_recording_taken_in_is_analysed_once_and_everything_learnt_is_in_the_canonical_model(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()], speech=FakeSpeech(), pictures=FakePictures())
    asset, _ = system.library.ingest(camera(tmp_path / "talk.mp4", room_sound(tmp_path / "s.wav", 1), seconds=6))
    drain(system)
    vi = system.vi
    assert vi.recording(asset)["technical"]["width"] and vi.recording(asset)["summary"]["profile"]["platforms"]
    assert vi.segments(asset, "shot") and len(vi.segments(asset, "beat")) >= 2 and vi.segments(asset, "sentence")
    assert {"text", "track"} <= {s.data["type"] for s in vi.segments(asset, "span")}
    beat = vi.segments(asset, "beat")[0]
    both = {o.source for o in vi.observations(asset, "shot_size", (beat.t_start, beat.t_end))}
    assert both == {"measured", "model"}                                       # one field, two sources
    assert vi.value(asset, (beat.t_start, beat.t_end), "shot_size").source == "measured"
    assert vi.value(asset, (beat.t_start, beat.t_end), "people").value == "một"
    assert vi.value(asset, (beat.t_start, beat.t_end), "description").value
    assert vi.stale(asset) == [] or set(vi.stale(asset)) <= {"telemetry", "events"}
    assert vi.entities("person") and vi.entities("person")[0]["appearances"][0]["asset_id"] == asset
    assert vi.analysed(asset)["pictures"] == "1" and vi.artifacts(asset)["pictures"].endswith("_pictures.npz")
    assert vi.search("chợ buổi sáng") and vi.search("chợ buổi sáng")[0].moment.asset_id == asset    # found by its pictures too


def test_a_library_analysed_before_the_canonical_model_is_moved_into_it_without_analysing_again(tmp_path):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=4))
    drain(system)
    system.intelligence.store.forget(asset)                                    # as if analysed before the canonical model existed
    assert system.vi.observations(asset) == []
    calls = dict(model.calls)
    done = system.intelligence.publish_existing(asset)
    assert done["structure"] and done["profile"] and done["descriptions"] and model.calls == calls        # no model asked anything
    assert system.vi.segments(asset, "beat") and system.vi.value(asset, 0.5, "description")


def test_deleting_a_recording_forgets_it_in_the_canonical_model(tmp_path):
    from nexora.app import remove_asset
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=4))
    drain(system)
    assert system.vi.observations(asset)
    remove_asset(system, asset)
    assert system.intelligence.store.forget(asset) == 0 and system.vi.recording(asset) is None
