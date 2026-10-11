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


def render_project(system, lines, **project):
    pid = system.planning.create_project("Thử", format=project.get("format", "landscape"))
    if project.get("music"):
        system.projects.update_project(pid, music_path=str(project["music"]))
    script = system.planning.save_script(pid, lines)
    system.sourcing.approve(system.sourcing.start_match(script, wait=lambda: drain(system)))
    system.edit.start_render(script)
    drain(system)
    return system.projects.renders(pid)[0]["qc"]


def test_a_portrait_project_renders_a_vertical_video_that_fills_the_frame(system):
    qc = render_project(system, ["cá tươi trên sạp", "chợ rau củ"], format="portrait")
    assert (qc["width"], qc["height"], qc["format"]) == (720, 1280, "portrait") and qc["passed"]


def test_music_is_mixed_under_the_narration(system, tmp_path):
    import subprocess
    music = tmp_path / "music.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=3", str(music)], check=True)
    silent = render_project(system, ["cá tươi trên sạp", "chợ rau củ"])
    with_music = render_project(system, ["cá tươi trên sạp", "chợ rau củ"], music=music)
    assert with_music["music"] and not silent["music"]
    assert with_music["mean_db"] > silent["mean_db"] + 20              # the fake narration is silence, so the music is what is heard
    assert with_music["checks"]["Âm thanh không bị vỡ"]


def test_the_cut_review_reports_gaps_with_the_shot_they_concern(system):
    qc = render_project(system, ["bàn phím máy tính", "cá tươi trên sạp"])
    checks = {(f["check"], f["shot"]) for f in qc["findings"]}
    assert ("Thiếu hình", 1) in checks and ("Mở đầu", 1) in checks


def test_the_operator_is_notified_when_a_decision_is_needed_and_when_a_run_ends(system):
    system.orch.mark_notifications_read()
    pid = system.planning.create_project("Thử")
    script = system.planning.save_script(pid, ["cá tươi trên sạp"])
    run = system.sourcing.start_match(script)
    drain(system)
    assert [(n["kind"], n["stage_key"]) for n in system.orch.notifications(unread_only=True)] == [("waiting_review", "match")]
    system.sourcing.approve(run)
    system.orch.notify("succeeded", run)
    system.orch.mark_notifications_read()
    assert system.orch.notifications(unread_only=True) == []


def test_the_publishing_package_holds_everything_a_manual_upload_needs(system):
    pid = system.planning.create_project("Chợ sáng")
    script = system.planning.save_script(pid, ["cá tươi trên sạp", "chợ rau củ"])
    system.sourcing.approve(system.sourcing.start_match(script, wait=lambda: drain(system)))
    system.edit.start_render(script); drain(system)
    render = system.projects.renders(pid)[0]
    package = system.distribution.build_package(render["render_id"])
    folder = __import__("pathlib").Path(package["folder"])
    assert package["title"] == "Chợ sáng" and package["synthetic_content"] is False and len(package["thumbnails"]) == 3
    assert all((folder / name).stat().st_size > 0 for name in [package["video"], package["captions"], *package["thumbnails"], "package.json"])
    captions = (folder / "captions.srt").read_text(encoding="utf-8")
    assert captions.startswith("1\n00:00:00,000 --> ") and "cá tươi trên sạp" in captions and "\n2\n" in captions
    assert system.distribution.choose_thumbnail(render["render_id"], package["thumbnails"][2])["thumbnail"] == package["thumbnails"][2]


def test_confidence_based_acceptance_skips_the_review_only_when_every_selection_is_strong(system):
    strong = system.planning.create_project("Tự duyệt")
    system.projects.update_project(strong, auto_accept=1)
    script = system.planning.save_script(strong, ["cá tươi trên sạp", "chợ rau củ"])
    run = system.sourcing.start_match(script)
    drain(system)
    assert system.orch.run_status(run) is RunStatus.SUCCEEDED and system.projects.script(script)["match_approved"]
    assert {s.decided_by for s in system.projects.selections(script)} == {"policy"}

    weak = system.planning.create_project("Có khoảng trống")
    system.projects.update_project(weak, auto_accept=1)
    script2 = system.planning.save_script(weak, ["cá tươi trên sạp", "bàn phím máy tính"])
    run2 = system.sourcing.start_match(script2)
    drain(system)
    assert system.orch.run_status(run2) is RunStatus.WAITING_REVIEW          # a gap always goes to the operator


def test_a_gap_is_filled_with_licensed_stock_that_enters_the_library_with_its_rights(tmp_path):
    from nexora.app import fill_gap_from_stock
    from tests.fakes import FakeStock
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, stock=FakeStock())
    system.library.ingest(make_video(tmp_path / "footage.mp4", picture=20)); drain(system)
    pid = system.planning.create_project("Biển")
    script = system.planning.save_script(pid, ["cá tươi trên sạp", "bàn phím máy tính"])
    run = system.sourcing.start_match(script); drain(system)
    gap = system.projects.selections(script)[1]
    assert gap.status == "gap"
    out = fill_gap_from_stock(system, gap.shot_id, "keyboard typing")
    drain(system)                                                                  # the stock clip is ingested and understood like any footage
    filled = system.projects.selections(script)[1]
    assert out["found"] and filled.status == "proposed" and "Public Domain" in filled.reason
    asset = next(a for a in system.assets.assets() if a["asset_id"] == filled.asset_id)
    assert asset["origin"] == "licensed" and system.assets.original(filled.asset_id).metadata["rights"]["license"] == "Public Domain"
    system.sourcing.approve(run)
    system.edit.start_render(script); drain(system)
    render = system.projects.renders(pid)[0]
    assert render["qc"]["gaps"] == 0
    assert system.distribution.build_package(render["render_id"])["credits"] == ["licensed"]
