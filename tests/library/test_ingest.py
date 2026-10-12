"""Slice 2: ingest a video (design v4.0, sections 15.1 and 17.1)."""
import pytest

from nexora.app import build
from nexora.core.assets import sha256_file
from nexora.core.states import RunStatus

from tests.conftest import make_video


@pytest.fixture
def system(tmp_path):
    return build(tmp_path / "data")


def drain(system):
    while system.worker.run_once():
        pass


def test_ingest_marks_the_unusable_black_tail_and_makes_a_proxy_and_thumbnail(system, clip_with_black_tail):
    before = sha256_file(clip_with_black_tail)
    asset_id, run_id = system.library.ingest(clip_with_black_tail)
    drain(system)
    assert system.orch.run_status(run_id) is RunStatus.SUCCEEDED
    original = system.assets.original(asset_id)
    assert original.checksum == before == sha256_file(clip_with_black_tail)      # the source is untouched
    assert original.metadata["probe"]["width"] == 320
    (start, end), = original.metadata["usable_ranges"]
    assert start == 0.0 and end == pytest.approx(2.0, abs=0.2)
    roles = {v.role: v for v in system.assets.versions(asset_id)}
    assert set(roles) == {"original", "proxy", "thumbnail"}
    assert system.assets.path_of(roles["proxy"]).is_file() and roles["proxy"].parents == (original.version_id,)
    assert roles["proxy"].created_by_attempt_id is not None


def test_a_fully_usable_clip_has_one_range_covering_it(system, plain_clip):
    asset_id, _ = system.library.ingest(plain_clip)
    drain(system)
    (start, end), = system.assets.original(asset_id).metadata["usable_ranges"]
    assert start == 0.0 and end == pytest.approx(2.0, abs=0.2)


def test_ingesting_the_same_file_again_does_not_start_a_second_run(system, plain_clip):
    assert system.library.ingest(plain_clip) == system.library.ingest(plain_clip)


def test_a_copy_of_an_ingested_file_is_linked_as_a_duplicate_not_processed_again(system, plain_clip, tmp_path):
    first, _ = system.library.ingest(plain_clip)
    drain(system)
    copy = tmp_path / "copy.mp4"; copy.write_bytes(plain_clip.read_bytes())
    second, run2 = system.library.ingest(copy)
    drain(system)
    assert system.orch.run_status(run2) is RunStatus.SUCCEEDED
    assert system.assets.original(second).metadata["duplicate_of"] == first
    assert [v.role for v in system.assets.versions(second)] == ["original"]         # no second proxy


def test_ingest_resumes_after_the_worker_dies_during_the_proxy_stage(system, plain_clip):
    asset_id, run_id = system.library.ingest(plain_clip)
    for _ in range(3):                                   # checksum, probe, usable ranges
        system.worker.run_once()
    system.orch.claim_next("dead", now=0)                # a worker takes the next stage and dies
    system.worker.recover(now=10**12)
    while system.worker.run_once(now=2 * 10**12):         # well past the retry backoff
        pass
    assert system.orch.run_status(run_id) is RunStatus.SUCCEEDED
    assert {v.role for v in system.assets.versions(asset_id)} == {"original", "proxy", "thumbnail"}


def test_a_missing_source_fails_the_run_with_a_clear_code(system, tmp_path):
    gone = make_video(tmp_path / "gone.mp4", picture=1)
    asset_id, run_id = system.library.ingest(gone)
    gone.unlink()
    drain(system)
    assert system.orch.run_status(run_id) is RunStatus.FAILED


def test_ingest_blocks_before_the_proxy_when_the_disk_is_nearly_full(tmp_path, plain_clip):
    system = build(tmp_path / "data", min_free_bytes=10**18)          # more than any disk has
    asset_id, run_id = system.library.ingest(plain_clip)
    drain(system)
    proxy = next(s for s in system.orch.stages(run_id) if s.stage_key == "proxy")
    assert proxy.status.value == "blocked" and proxy.blocked_reason == "insufficient_storage"
    assert system.orch.run_status(run_id) is RunStatus.BLOCKED


def test_frozen_stretches_are_recorded_but_stay_usable(system, tmp_path):
    import subprocess
    src = tmp_path / "frozen.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=2",
                    "-vf", "tpad=stop_mode=clone:stop_duration=3", "-pix_fmt", "yuv420p", str(src)], check=True)
    asset_id, _ = system.library.ingest(src)
    drain(system)
    meta = system.assets.original(asset_id).metadata
    assert len(meta["frozen_ranges"]) == 1 and meta["usable_ranges"] == [[0.0, pytest.approx(5.0, abs=0.2)]]


def test_the_places_where_the_picture_changes_outright_are_found(system, tmp_path):
    import subprocess
    out = tmp_path / "two_shots.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=4", "-f", "lavfi", "-i", "smptebars=size=320x180:rate=25:duration=3",
                    "-f", "lavfi", "-i", "mandelbrot=size=320x180:rate=25", "-filter_complex", "[2:v]trim=duration=3,setpts=PTS-STARTPTS[m];[0:v][1:v][m]concat=n=3:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", str(out)], check=True)
    asset, _ = system.library.ingest(out)
    while system.worker.run_once():
        pass
    cuts = system.assets.original(asset).metadata["scene_cuts"]
    assert len(cuts) == 2 and cuts[0] == pytest.approx(4.0, abs=0.1) and cuts[1] == pytest.approx(7.0, abs=0.1)
