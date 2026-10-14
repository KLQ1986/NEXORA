"""The producer agent, schedules and project budgets."""
import pytest

from nexora.app import build
from nexora.core.schedule import in_window, parse_window
from nexora.core.states import RunStatus, StageStatus

from tests.conftest import make_video
from tests.fakes import FakeImageGen, FakeModel, FakeStock, FakeVideoGen, FakeVoice


def settle(system):
    """Let the workers and the agent run until neither has anything left to do."""
    for _ in range(200):
        worked = False
        while system.worker.run_once():
            worked = True
        if not system.producer.tick() and not worked:
            return
    raise AssertionError("the agent never came to rest")


def test_the_producer_carries_a_goal_to_a_cut_and_stops_at_each_human_gate(tmp_path):
    model = FakeModel(); model.script = ["cá tươi trên sạp", "bàn phím máy tính"]
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=2.0, stock=FakeStock())
    system.library.ingest(make_video(tmp_path / "footage.mp4", picture=20))
    while system.worker.run_once():
        pass
    task_id = system.producer.start("một buổi sáng ở chợ")
    settle(system)
    task = system.producer.task(task_id)
    assert (task["status"], task["step"]) == ("waiting_operator", "review")          # it does not approve its own choices
    sels = system.projects.selections(system.projects.current_script(task["project_id"])["script_id"])
    # Stock was fetched for the gap, watched, and withdrawn again: the clip that came back does not show a keyboard.
    assert [s.status for s in sels] == ["proposed", "gap"] and "không có đoạn nào" in sels[1].reason and "Clip stock" in sels[1].reason
    assert [e["role"] for e in task["log"]] == ["Điều phối", "Biên kịch", "Phản biện", "Kiểm chứng", "Tìm hình", "Tìm hình", "Tìm stock", "Điều phối"]

    script = system.projects.current_script(task["project_id"])["script_id"]
    system.sourcing.approve(system.orch.runs_for_subject(script)[0])
    settle(system)
    task = system.producer.task(task_id)
    assert (task["status"], task["step"]) == ("waiting_operator", "cutting") and system.projects.renders(task["project_id"])[0]["qc"]["passed"]
    render = next(r for r in system.orch.runs_for_subject(script) if system.orch.pipeline_of(r) == "edit.render")
    gate = next(s for s in system.orch.stages(render) if s.status is StageStatus.WAITING_REVIEW)
    system.orch.decide_review(gate.stage_id, approve=True)
    settle(system)
    assert system.producer.task(task_id)["status"] == "done"


def test_a_producer_with_nothing_to_write_from_says_so_and_stops(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    task_id = system.producer.start("chủ đề không có footage")
    settle(system)
    task = system.producer.task(task_id)
    assert task["status"] == "failed" and "Không viết được" in task["log"][-1]["text"]


def test_background_work_waits_for_its_hours():
    assert in_window("", hour=14) and in_window("22-7", hour=23) and in_window("22-7", hour=3)
    assert not in_window("22-7", hour=14) and in_window("9-17", hour=9) and not in_window("9-17", hour=17)
    with pytest.raises(ValueError):
        parse_window("7-7")


def test_footage_analysis_is_held_outside_the_window_while_other_work_goes_on(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    hour = __import__("time").localtime().tm_hour
    system.orch.set_setting("background_window", f"{(hour + 2) % 24}-{(hour + 3) % 24}")        # a window that is not now
    asset_id, ingest = system.library.ingest(make_video(tmp_path / "f.mp4", picture=6))
    interactive, background = system.workers
    while interactive.run_once() or background.run_once():
        pass
    profile = next(r for r in system.orch.runs_for_subject(asset_id) if system.orch.pipeline_of(r) == "library.profile")
    assert system.orch.run_status(ingest) is RunStatus.SUCCEEDED
    assert {s.stage_key: s.status.value for s in system.orch.stages(profile)}["look"] == "ready"         # waiting for its hours
    system.orch.set_setting("background_window", "")
    while interactive.run_once() or background.run_once():
        pass
    understand = next(r for r in system.orch.runs_for_subject(asset_id) if system.orch.pipeline_of(r) == "library.understand")
    assert system.orch.run_status(profile) is RunStatus.SUCCEEDED and system.orch.run_status(understand) is RunStatus.SUCCEEDED


def test_a_project_budget_already_spent_stops_paid_generation_before_it_starts(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), generators=[FakeImageGen(), FakeVideoGen()])
    pid = system.planning.create_project("Hoạt hình")
    system.projects.update_project(pid, budget_cap=0.0)
    script = system.planning.save_script(pid, ["một con mèo"])
    run = system.generation.start(script)
    while system.worker.run_once():
        pass
    stage = system.orch.stages(run)[0]
    assert stage.status is StageStatus.BLOCKED and stage.blocked_reason == "budget_exceeded"
