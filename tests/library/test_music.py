"""Music as library material: measured on the way in, never sent for visual understanding."""
import subprocess

from nexora.app import build
from nexora.core.states import RunStatus
from tests.fakes import FakeModel


def test_a_music_file_is_measured_and_kept_out_of_the_footage_index(tmp_path):
    track = tmp_path / "theme.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=6", str(track)], check=True)
    system = build(tmp_path / "data", model=FakeModel())
    asset_id, run = system.library.ingest(track)
    while system.worker.run_once():
        pass
    assert system.orch.run_status(run) is RunStatus.SUCCEEDED
    probe = system.assets.original(asset_id).metadata["probe"]
    assert probe["audio_only"] and abs(probe["duration"] - 6) < 0.2 and probe["mean_db"] < 0
    assert system.index.moments(asset_id) == [] and len(system.orch.runs_for_subject(asset_id)) == 1
