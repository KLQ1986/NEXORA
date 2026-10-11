"""Steps 7 and 9: script, matching, review, render (design v4.0, sections 15.2, 18, 19)."""
import pytest

from nexora.app import build
from nexora.core.states import RunStatus, StageStatus

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeVoice


@pytest.fixture
def system(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, match_threshold=0.5)
    system.library.ingest(make_video(tmp_path / "footage.mp4", picture=20))       # ten segments: each subject appears twice
    drain(system)
    return system


def drain(system):
    while system.worker.run_once():
        pass


def test_saving_a_script_again_creates_a_new_version(system):
    project = system.planning.create_project("Chợ sáng")
    first = system.planning.save_script(project, ["cá tươi trên sạp", "chợ rau củ"])
    second = system.planning.save_script(project, ["cá tươi trên sạp"])
    current = system.projects.current_script(project)
    assert first != second and current["script_id"] == second and current["version"] == 2
    assert [s.text for s in current["shots"]] == ["cá tươi trên sạp"]


def test_matching_selects_a_range_for_lines_with_footage_and_reports_a_gap_for_the_rest(system):
    project = system.planning.create_project("Chợ sáng")
    script = system.planning.save_script(project, ["cá tươi trên sạp", "bàn phím máy tính", "chợ rau củ"])
    run = system.sourcing.start_match(script)
    drain(system)
    assert system.orch.run_status(run) is RunStatus.WAITING_REVIEW               # the operator reviews before anything is cut
    fish, keyboard, market = system.projects.selections(script)
    assert fish.status == "proposed" and "cá tươi" in fish.reason and fish.t_out > fish.t_in
    assert keyboard.status == "gap" and keyboard.asset_id is None
    assert market.status == "proposed" and market.moment_id != fish.moment_id        # a moment is not used twice


def test_the_operator_can_swap_to_an_alternate_and_approve(system):
    project = system.planning.create_project("Chợ")
    script = system.planning.save_script(project, ["chợ rau củ"])
    run = system.sourcing.start_match(script)
    drain(system)
    sel = system.projects.selections(script)[0]
    assert sel.alternates, "a second moment about the market exists"
    system.sourcing.swap(sel.shot_id, 0)
    swapped = system.projects.selections(script)[0]
    assert swapped.moment_id == sel.alternates[0]["moment_id"] and swapped.decided_by == "operator"
    system.sourcing.approve(run)
    assert system.orch.run_status(run) is RunStatus.SUCCEEDED


def test_render_produces_a_video_with_narration_and_captions_and_reuses_unchanged_segments(system):
    project = system.planning.create_project("Chợ sáng")
    script = system.planning.save_script(project, ["cá tươi trên sạp", "bàn phím máy tính", "chợ rau củ"])
    system.sourcing.approve(system.sourcing.start_match(script, wait=lambda: drain(system)))
    run = system.edit.start_render(script)
    drain(system)
    assert system.orch.run_status(run) is RunStatus.WAITING_REVIEW               # render review
    render = system.projects.renders(project)[0]
    qc = render["qc"]
    assert qc["passed"] and qc["has_audio"] and (qc["width"], qc["height"]) == (1280, 720)
    assert qc["duration"] == pytest.approx(sum(qc["shot_durations"]), abs=0.5) and len(qc["shot_durations"]) == 3
    segments = sorted(p for p in (system.data_dir / "media" / "segments").glob("*.mp4"))
    stamps = {p: p.stat().st_mtime_ns for p in segments}
    assert len(segments) == 3

    sel = system.projects.selections(script)[2]
    system.sourcing.swap(sel.shot_id, 0)                                          # change one shot only
    run2 = system.edit.start_render(script)
    drain(system)
    after = sorted((system.data_dir / "media" / "segments").glob("*.mp4"))
    assert len(after) == 4                                                        # exactly one new segment was rendered
    assert all(p.stat().st_mtime_ns == stamps[p] for p in segments)               # the others were reused untouched


def test_render_is_blocked_until_the_match_is_approved(system):
    project = system.planning.create_project("Chợ")
    script = system.planning.save_script(project, ["chợ rau củ"])
    system.sourcing.start_match(script)
    drain(system)
    with pytest.raises(ValueError):
        system.edit.start_render(script)


def test_the_judge_rejects_a_candidate_whose_frames_do_not_show_the_line(system):
    """Retrieval alone would accept this: the line shares one word with a moment. Looking at the frames rejects it."""
    project = system.planning.create_project("Chợ")
    script = system.planning.save_script(project, ["cá tươi trên sạp", "pha trà nóng"])     # "pha" also occurs in "pha cà phê"
    system.sourcing.start_match(script)
    drain(system)
    fish, tea = system.projects.selections(script)
    assert fish.status == "proposed" and "9/10" in fish.reason
    assert tea.status == "gap"


def test_the_clip_is_centred_on_the_frame_the_model_points_at(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=10.0)
    system.library.ingest(make_video(tmp_path / "f.mp4", picture=20))
    drain(system)
    project = system.planning.create_project("Chợ")
    script = system.planning.save_script(project, ["chợ rau củ"])
    system.sourcing.start_match(script)
    drain(system)
    sel = system.projects.selections(script)[0]
    assert (sel.t_in, sel.t_out) == (7.5, 10.0)             # the fake points at the last frame of a ten-second moment
