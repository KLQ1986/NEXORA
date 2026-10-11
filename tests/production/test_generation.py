"""Pipeline A: AI-generated shots, keyframe first (design v4.0, sections 15.3 and 18.4-18.6)."""
import pytest

from nexora.app import build
from nexora.core.states import RunStatus
from nexora.modules.sourcing.generate import PromptSpec, compile_prompt, split_duration

from tests.fakes import FakeImageGen, FakeModel, FakeVideoGen, FakeVoice


def drain(system):
    while system.worker.run_once():
        pass


def test_the_prompt_compiler_is_deterministic_and_carries_the_style():
    spec = PromptSpec(subject="Một chú mèo cam ngồi bên cửa sổ.", style="hoạt hình màu nước", aspect="9:16")
    assert compile_prompt(spec, kind="image") == compile_prompt(spec, kind="image")
    assert "hoạt hình màu nước" in compile_prompt(spec, kind="image") and "9:16" in compile_prompt(spec, kind="image")
    assert "camera" in compile_prompt(spec, kind="video") and "camera" not in compile_prompt(spec, kind="image")


def test_a_shot_longer_than_the_provider_limit_is_split_evenly():
    assert split_duration(5.0, 8.0) == [5.0]
    assert split_duration(18.0, 8.0) == [6.0, 6.0, 6.0]


def test_without_a_provider_generation_waits_for_the_operator_instead_of_failing(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    pid = system.planning.create_project("Mèo cam")
    run = system.generation.start(system.planning.save_script(pid, ["Một chú mèo cam ngồi bên cửa sổ."]))
    drain(system)
    stage = system.orch.stages(run)[0]
    assert stage.status.value == "blocked" and stage.blocked_reason == "auth"
    assert system.generation.available() == {"image": False, "video": False}


def test_stills_are_approved_before_any_video_is_generated_and_the_result_renders(tmp_path):
    image, video = FakeImageGen(), FakeVideoGen()
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), generators=[image, video])
    pid = system.planning.create_project("Mèo cam")
    system.projects.update_project(pid, style="hoạt hình màu nước")
    script = system.planning.save_script(pid, ["Một chú mèo cam ngồi bên cửa sổ.", "Chú mèo nhìn mưa rơi ngoài hiên."])
    run = system.generation.start(script)
    drain(system)
    assert system.orch.run_status(run) is RunStatus.WAITING_REVIEW
    assert len(image.requests) == 2 and video.requests == []                       # nothing spent on video before the stills are approved
    assert all("hoạt hình màu nước" in r.inputs["prompt"] for r in image.requests)

    system.generation.approve(run)                                                # stills approved
    drain(system)
    assert len(video.requests) == 2 and system.orch.run_status(run) is RunStatus.WAITING_REVIEW
    shots = system.projects.script(script)["shots"]
    records = system.projects.generations(shots[0].shot_id)
    assert [r["kind"] for r in records] == ["keyframe", "clip"] and records[0]["seed"] == records[1]["seed"] is not None
    assert video.requests[0].inputs["first_frame"].endswith("_key.png")            # the approved still is the first frame
    assert system.orch.run_cost(run) == pytest.approx(0.04 + 0.1 * sum(r.params["duration"] for r in video.requests))

    system.generation.approve(run)                                                # clips approved
    assert system.orch.run_status(run) is RunStatus.SUCCEEDED
    system.edit.start_render(script)
    drain(system)
    qc = system.projects.renders(pid)[0]["qc"]
    assert qc["passed"] and qc["gaps"] == 0
    package = system.distribution.build_package(system.projects.renders(pid)[0]["render_id"])
    assert package["synthetic_content"] is True                                    # generated picture is disclosed
