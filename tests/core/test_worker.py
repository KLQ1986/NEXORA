"""The worker runs stage handlers and turns their results into state changes (design v4.0, sections 5-7)."""
import pytest

from nexora.core.adapter import AdapterError, ErrorCode
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.states import AttemptOutcome, RunStatus, StageStatus
from nexora.core.worker import Worker

T0 = 2_000_000.0
PIPE = PipelineDefinition("demo", "1", [StageDef("probe"), StageDef("describe", depends_on=("probe",), costly=True)])


def make(tmp_path, handlers, pipeline=PIPE):
    orch = Orchestrator(tmp_path / "n.db")
    registry = PipelineRegistry()
    registry.register(pipeline, handlers)
    return orch, Worker(orch, registry, worker_id="w1")


def stage(orch, run, key):
    return next(s for s in orch.stages(run) if s.stage_key == key)


def test_worker_runs_a_pipeline_and_passes_outputs_to_dependent_stages(tmp_path):
    seen = {}
    def probe(ctx):
        return {"duration": 12.5}
    def describe(ctx):
        seen.update(ctx.inputs["probe"])
        return {"text": "ok"}
    orch, worker = make(tmp_path, {"probe": probe, "describe": describe})
    run = orch.submit_run(PIPE, now=T0)
    assert worker.run_once(now=T0) is True
    assert worker.run_once(now=T0 + 1) is True
    assert worker.run_once(now=T0 + 2) is False                  # nothing left to do
    assert seen == {"duration": 12.5}
    assert orch.run_status(run) is RunStatus.SUCCEEDED
    assert stage(orch, run, "describe").outputs == {"text": "ok"}


def test_a_retryable_adapter_error_schedules_a_retry(tmp_path):
    def probe(ctx):
        raise AdapterError(ErrorCode.UNAVAILABLE, "provider down")
    orch, worker = make(tmp_path, {"probe": probe, "describe": lambda ctx: None})
    run = orch.submit_run(PIPE, now=T0)
    worker.run_once(now=T0)
    assert stage(orch, run, "probe").status is StageStatus.RETRY_WAIT


def test_a_permanent_adapter_error_fails_the_stage(tmp_path):
    def probe(ctx):
        raise AdapterError(ErrorCode.MISSING_INPUT, "no such file")
    orch, worker = make(tmp_path, {"probe": probe, "describe": lambda ctx: None})
    run = orch.submit_run(PIPE, now=T0)
    worker.run_once(now=T0)
    s = stage(orch, run, "probe")
    assert s.status is StageStatus.FAILED
    assert orch.attempts(s.stage_id)[0].error_code == "missing_input"


@pytest.mark.parametrize("code", [ErrorCode.AUTH, ErrorCode.QUOTA_EXHAUSTED])
def test_errors_only_the_operator_can_fix_block_the_stage(tmp_path, code):
    def probe(ctx):
        raise AdapterError(code, "needs the operator")
    orch, worker = make(tmp_path, {"probe": probe, "describe": lambda ctx: None})
    run = orch.submit_run(PIPE, now=T0)
    worker.run_once(now=T0)
    s = stage(orch, run, "probe")
    assert s.status is StageStatus.BLOCKED and s.blocked_reason == code.value


def test_an_unexpected_exception_is_treated_as_a_retryable_internal_error(tmp_path):
    def probe(ctx):
        raise RuntimeError("bug")
    orch, worker = make(tmp_path, {"probe": probe, "describe": lambda ctx: None})
    run = orch.submit_run(PIPE, now=T0)
    worker.run_once(now=T0)
    s = stage(orch, run, "probe")
    assert s.status is StageStatus.RETRY_WAIT
    assert orch.attempts(s.stage_id)[0].error_code == "internal"


def test_costs_are_recorded_and_a_costly_stage_is_blocked_when_the_budget_is_spent(tmp_path):
    def probe(ctx):
        ctx.record_cost(provider="vision", units=10, cost=1.5)
        return {}
    orch, worker = make(tmp_path, {"probe": probe, "describe": lambda ctx: {}})
    run = orch.submit_run(PIPE, budget_cap=1.0, now=T0)
    worker.run_once(now=T0)
    assert orch.run_cost(run) == 1.5
    assert worker.run_once(now=T0 + 1) is False
    s = stage(orch, run, "describe")
    assert s.status is StageStatus.BLOCKED and s.blocked_reason == "budget_exceeded"


def test_a_handler_can_stop_at_a_safe_point_when_the_run_is_cancelled(tmp_path):
    def probe(ctx):
        orch.cancel_run(ctx.claim.run_id, now=T0 + 1)
        assert ctx.should_stop()
        return {}
    orch, worker = make(tmp_path, {"probe": probe, "describe": lambda ctx: {}})
    run = orch.submit_run(PIPE, now=T0)
    worker.run_once(now=T0)
    assert orch.run_status(run) is RunStatus.CANCELLED


def test_worker_recovers_lost_attempts_when_it_starts(tmp_path):
    orch, worker = make(tmp_path, {"probe": lambda ctx: {}, "describe": lambda ctx: {}})
    run = orch.submit_run(PIPE, now=T0)
    orch.claim_next("dead-worker", now=T0)                        # a previous worker died holding the claim
    worker.recover(now=T0 + 10_000)
    s = stage(orch, run, "probe")
    assert orch.attempts(s.stage_id)[0].outcome is AttemptOutcome.CRASHED
    assert s.status is StageStatus.RETRY_WAIT


def test_a_stage_without_a_handler_is_a_configuration_error(tmp_path):
    with pytest.raises(ValueError):
        PipelineRegistry().register(PIPE, {"probe": lambda ctx: {}})


def test_a_failure_stops_counting_once_put_right_or_set_aside(tmp_path):
    broken = {"now": True}
    def probe(ctx):
        if broken["now"]:
            raise AdapterError(ErrorCode.MISSING_INPUT, "no such file")
        return {}
    orch, worker = make(tmp_path, {"probe": probe, "describe": lambda ctx: {}})
    first = orch.submit_run(PIPE, subject_ref="ast_1", now=T0)
    other = orch.submit_run(PIPE, subject_ref="ast_2", now=T0 + 1)
    worker.run_once(now=T0 + 2)
    worker.run_once(now=T0 + 3)
    assert orch.run_status(first) is RunStatus.FAILED and orch.run_status(other) is RunStatus.FAILED
    assert not orch.cleared(first) and not orch.cleared(other)

    broken["now"] = False                                         # the same work on the same footage succeeds later
    again = orch.submit_run(PIPE, subject_ref="ast_1", now=T0 + 10)
    while worker.run_once(now=T0 + 20):
        pass
    assert orch.run_status(again) is RunStatus.SUCCEEDED
    assert orch.cleared(first) and not orch.cleared(other)        # the other footage has not been put right

    assert orch.dismiss([other]) == 1 and orch.cleared(other)     # the operator sets it aside
    assert orch.dismiss([other]) == 0


def test_a_stage_still_going_past_its_time_is_stopped_at_its_next_heartbeat(tmp_path):
    import time
    slow = PipelineDefinition("t.slow", "1", [StageDef("loop", timeout_seconds=0.05)])
    def loop(ctx):
        for _ in range(100):                               # going round, saying it is alive, never done
            time.sleep(0.01)
            ctx.heartbeat()
        return {}
    orch, worker = make(tmp_path, {"loop": loop}, pipeline=slow)
    run = orch.submit_run(slow)
    worker.run_once()
    s = stage(orch, run, "loop")
    assert s.status is StageStatus.FAILED and "0.05" in orch.why_stopped(s)


def test_a_run_may_be_done_in_a_lane_of_its_own(tmp_path):
    orch, worker = make(tmp_path, {"probe": lambda ctx: {}, "describe": lambda ctx: {}})
    run = orch.submit_run(PIPE, lane="agent")
    assert not Worker(orch, worker._registry, worker_id="w2", lanes=frozenset({"interactive"})).run_once()
    assert Worker(orch, worker._registry, worker_id="w3", lanes=frozenset({"agent"})).run_once()


def test_a_worker_keeps_the_claim_of_a_long_quiet_call_and_lets_it_go_past_the_stages_time(tmp_path):
    import time
    quiet = PipelineDefinition("t.quiet", "1", [StageDef("call", timeout_seconds=0.6)])
    seen = {}
    def call(ctx):                                         # one model call, saying nothing while it waits
        start = orch._conn.execute("SELECT heartbeat_at FROM attempts WHERE attempt_id = ?", (ctx.claim.attempt_id,)).fetchone()[0]
        time.sleep(0.35)
        seen["kept"] = orch._conn.execute("SELECT heartbeat_at FROM attempts WHERE attempt_id = ?", (ctx.claim.attempt_id,)).fetchone()[0] > start
        before = orch._conn.execute("SELECT heartbeat_at FROM attempts WHERE attempt_id = ?", (ctx.claim.attempt_id,)).fetchone()[0]
        time.sleep(0.6)                                    # past the stage's time: nobody vouches for it any more
        seen["let_go"] = orch._conn.execute("SELECT heartbeat_at FROM attempts WHERE attempt_id = ?", (ctx.claim.attempt_id,)).fetchone()[0] - before < 0.3
        return {}
    orch = Orchestrator(tmp_path / "n.db")
    registry = PipelineRegistry(); registry.register(quiet, {"call": call})
    worker = Worker(orch, registry, worker_id="w1", keep_alive=0.1)
    orch.submit_run(quiet)
    worker.run_once()
    assert seen == {"kept": True, "let_go": True}
