"""Pieces of a recording taken out to be used elsewhere: a clip, its best still and its sound, each with a card."""
import json
import subprocess

from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.fakes import FakeModel, FakePictures, FakeSound, FakeSpeech, FakeVision
from tests.library.test_sync import camera, room_sound


def drain(system):
    while system.worker.run_once():
        pass


def _seconds(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def test_a_stretch_is_taken_out_as_a_clip_a_still_and_its_sound_with_a_card_of_what_it_shows(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()], speech=FakeSpeech(), pictures=FakePictures())
    asset, _ = system.library.ingest(camera(tmp_path / "talk.mp4", room_sound(tmp_path / "s.wav", 1), seconds=6))
    drain(system)
    client = TestClient(create_app(system))

    made = client.post(f"/api/v1/assets/{asset}/extract", json={"t_in": 1.0, "t_out": 3.5}).json()["extracts"][0]
    assert set(made["files"]) == {"clip", "still", "audio"}
    folder = system.data_dir / "exports" / "assets" / asset / made["name"]
    assert abs(_seconds(folder / "clip.mp4") - 2.5) < 0.2 and abs(_seconds(folder / "audio.wav") - 2.5) < 0.1
    tags = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_primaries", "-of", "csv=p=0",
                           str(folder / "clip.mp4")], capture_output=True, text=True).stdout.strip()
    original = system.assets.original(asset).metadata["probe"].get("color_primaries")
    assert not original or tags == original                              # the colour description travels with the clip
    assert (folder / "still.jpg").stat().st_size > 0
    card = json.loads((folder / "card.json").read_text())
    assert card["source"]["t_in"] == 1.0 and card["source"]["checksum"] and card["picture"]["grade"] and card["description"]
    assert 1.0 <= card["still_at"] < 3.5

    listed = client.get(f"/api/v1/assets/{asset}/extracts").json()["extracts"]
    assert listed[0]["name"] == made["name"] and client.get(listed[0]["urls"]["still"]).status_code == 200
    assert client.get(f"/api/v1/assets/{asset}/extracts/..%2F..%2F/nexora.db").status_code == 404
    assert client.post(f"/api/v1/assets/{asset}/extract", json={"t_in": 3.0, "t_out": 3.0}).status_code == 422

    good = [b for b in client.get(f"/api/v1/assets/{asset}/dossier").json()["beats"] if b["picture"]["grade"] == "dùng được"]
    usable = client.post(f"/api/v1/assets/{asset}/extract", json={"usable": True, "kinds": ["still"]}).json()["extracts"]
    assert len(usable) == len(good) and all(set(u["files"]) == {"still"} and u["card"]["picture"]["grade"] == "dùng được" for u in usable)
