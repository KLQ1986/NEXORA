"""Behaviour of the state model: Run -> Stage -> Attempt (design v4.0, section 6)."""
import pytest

from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, StageDef
from nexora.core.states import AttemptOutcome, EffectClass, RunStatus, StageStatus

T0 = 1_000_000.0


def two_step():
    return PipelineDefinition("demo", "1", [
        StageDef("ingest"),
        StageDef("index", depends_on=("ingest",)),
    ])


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(tmp_path / "nexora.db", lease_seconds=60)


def stage(orch, run_id, key):
    return next(s for s in orch.stages(run_id) if s.stage_key == key)


def test_submitting_twice_with_the_same_key_creates_one_run(orch):
    a = orch.submit_run(two_step(), idempotency_key="k1", now=T0)
    b = orch.submit_run(two_step(), idempotency_key="k1", now=T0 + 5)
    assert a == b
    assert len(orch.stages(a)) == 2


def test_new_run_is_queued_and_only_stages_without_dependencies_are_ready(orch):
    run = orch.submit_run(two_step(), now=T0)
    assert orch.run_status(run) is RunStatus.QUEUED
    assert stage(orch, run, "ingest").status is StageStatus.READY
    assert stage(orch, run, "index").status is StageStatus.PENDING


def test_a_stage_is_claimed_by_exactly_one_worker(orch):
    run = orch.submit_run(two_step(), now=T0)
    first = orch.claim_next("w1", now=T0)
    second = orch.claim_next("w2", now=T0)
    assert first is not None and first.stage_key == "ingest"
    assert second is None
    assert stage(orch, run, "ingest").status is StageStatus.RUNNING
    assert orch.run_status(run) is RunStatus.RUNNING


def test_success_promotes_dependents_and_finishes_the_run(orch):
    run = orch.submit_run(two_step(), now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.complete(c1.attempt_id, outputs={"asset": "ast_1"}, now=T0 + 1)
    assert stage(orch, run, "ingest").status is StageStatus.SUCCEEDED
    assert stage(orch, run, "index").status is StageStatus.READY
    c2 = orch.claim_next("w1", now=T0 + 2)
    assert c2.stage_key == "index"
    orch.complete(c2.attempt_id, now=T0 + 3)
    assert orch.run_status(run) is RunStatus.SUCCEEDED


def test_transient_failure_retries_with_backoff_then_blocks_at_the_limit(orch):
    pipe = PipelineDefinition("demo", "1", [StageDef("ingest", max_attempts=2)])
    run = orch.submit_run(pipe, now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.fail(c1.attempt_id, "unavailable", retryable=True, now=T0 + 1)
    assert stage(orch, run, "ingest").status is StageStatus.RETRY_WAIT
    assert orch.claim_next("w1", now=T0 + 2) is None            # still backing off
    c2 = orch.claim_next("w1", now=T0 + 3600)
    assert c2 is not None and c2.attempt_number == 2
    orch.fail(c2.attempt_id, "unavailable", retryable=True, now=T0 + 3601)
    blocked = stage(orch, run, "ingest")
    assert blocked.status is StageStatus.BLOCKED and blocked.blocked_reason == "retry_limit"
    assert orch.run_status(run) is RunStatus.BLOCKED
    assert [a.outcome for a in orch.attempts(blocked.stage_id)] == [AttemptOutcome.FAILED_TRANSIENT] * 2


def test_resuming_a_blocked_stage_creates_a_new_attempt(orch):
    pipe = PipelineDefinition("demo", "1", [StageDef("ingest", max_attempts=1)])
    run = orch.submit_run(pipe, now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.fail(c1.attempt_id, "unavailable", retryable=True, now=T0 + 1)
    orch.resume(stage(orch, run, "ingest").stage_id, now=T0 + 2)
    c2 = orch.claim_next("w1", now=T0 + 3)
    assert c2.attempt_number == 2


def test_permanent_failure_fails_the_stage_and_the_run(orch):
    run = orch.submit_run(two_step(), now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.fail(c1.attempt_id, "invalid_request", retryable=False, now=T0 + 1)
    assert stage(orch, run, "ingest").status is StageStatus.FAILED
    assert orch.run_status(run) is RunStatus.FAILED


def test_a_gated_stage_waits_for_review_and_approval_releases_dependents(orch):
    pipe = PipelineDefinition("demo", "1", [StageDef("script", gate=True), StageDef("match", depends_on=("script",))])
    run = orch.submit_run(pipe, now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.complete(c1.attempt_id, now=T0 + 1)
    assert stage(orch, run, "script").status is StageStatus.WAITING_REVIEW
    assert stage(orch, run, "match").status is StageStatus.PENDING
    assert orch.run_status(run) is RunStatus.WAITING_REVIEW
    orch.decide_review(stage(orch, run, "script").stage_id, approve=True, now=T0 + 2)
    assert stage(orch, run, "script").status is StageStatus.SUCCEEDED
    assert stage(orch, run, "match").status is StageStatus.READY


def test_rejecting_a_review_sends_the_stage_back_for_another_attempt(orch):
    pipe = PipelineDefinition("demo", "1", [StageDef("script", gate=True)])
    run = orch.submit_run(pipe, now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.complete(c1.attempt_id, now=T0 + 1)
    orch.decide_review(stage(orch, run, "script").stage_id, approve=False, now=T0 + 2)
    assert stage(orch, run, "script").status is StageStatus.READY
    assert orch.claim_next("w1", now=T0 + 3).attempt_number == 2


def test_recovery_retries_a_pure_stage_whose_worker_died(orch):
    run = orch.submit_run(two_step(), now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.recover(now=T0 + 120, is_alive=lambda claim: False)
    s = stage(orch, run, "ingest")
    assert s.status is StageStatus.RETRY_WAIT
    assert orch.attempts(s.stage_id)[0].outcome is AttemptOutcome.CRASHED


def test_recovery_leaves_a_live_worker_with_a_fresh_heartbeat_alone(orch):
    run = orch.submit_run(two_step(), now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.heartbeat(c1.attempt_id, now=T0 + 100)
    orch.recover(now=T0 + 120, is_alive=lambda claim: True)
    assert stage(orch, run, "ingest").status is StageStatus.RUNNING


def test_recovery_never_retries_an_external_effect_automatically(orch):
    pipe = PipelineDefinition("demo", "1", [StageDef("publish", effect_class=EffectClass.NON_IDEMPOTENT_EXTERNAL)])
    run = orch.submit_run(pipe, now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.recover(now=T0 + 120, is_alive=lambda claim: False)
    s = stage(orch, run, "publish")
    assert s.status is StageStatus.RUNNING                       # held until reconciled
    assert orch.attempts(s.stage_id)[0].outcome is AttemptOutcome.UNKNOWN
    assert orch.claim_next("w2", now=T0 + 4000) is None
    orch.reconcile(c1.attempt_id, completed=True, now=T0 + 4001)
    assert stage(orch, run, "publish").status is StageStatus.SUCCEEDED


def test_kill_switch_stops_costly_and_external_stages_but_not_pure_ones(orch):
    pipe = PipelineDefinition("demo", "1", [StageDef("probe"), StageDef("describe", costly=True)])
    orch.submit_run(pipe, now=T0)
    orch.set_kill_switch(True, now=T0)
    claimed = orch.claim_next("w1", now=T0 + 1)
    assert claimed.stage_key == "probe"
    assert orch.claim_next("w1", now=T0 + 2) is None
    orch.set_kill_switch(False, now=T0 + 3)
    assert orch.claim_next("w1", now=T0 + 4).stage_key == "describe"


def test_dispatch_guard_blocks_a_stage_with_the_reason(tmp_path):
    orch = Orchestrator(tmp_path / "n.db", guard=lambda s: "budget_exceeded" if s.costly else None)
    run = orch.submit_run(PipelineDefinition("demo", "1", [StageDef("describe", costly=True)]), now=T0)
    assert orch.claim_next("w1", now=T0) is None
    s = stage(orch, run, "describe")
    assert s.status is StageStatus.BLOCKED and s.blocked_reason == "budget_exceeded"


def test_cancelling_a_run_cancels_waiting_stages_and_stops_the_running_one(orch):
    run = orch.submit_run(two_step(), now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.cancel_run(run, now=T0 + 1)
    assert orch.should_stop(c1.attempt_id)
    assert stage(orch, run, "index").status is StageStatus.CANCELLED
    orch.complete(c1.attempt_id, now=T0 + 2)                     # worker reaches its safe point
    assert stage(orch, run, "ingest").status is StageStatus.CANCELLED
    assert orch.run_status(run) is RunStatus.CANCELLED


def test_a_skipped_stage_counts_as_done_for_its_dependents(orch):
    pipe = PipelineDefinition("demo", "1", [StageDef("speech"), StageDef("index", depends_on=("speech",))])
    run = orch.submit_run(pipe, now=T0)
    orch.skip(stage(orch, run, "speech").stage_id, reason="no speech", now=T0)
    assert stage(orch, run, "index").status is StageStatus.READY


def test_every_state_change_is_recorded_as_an_event(orch):
    run = orch.submit_run(two_step(), now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.complete(c1.attempt_id, now=T0 + 1)
    kinds = [e.kind for e in orch.events(run)]
    assert kinds[:4] == ["run.submitted", "stage.claimed", "attempt.succeeded", "stage.succeeded"]
    assert "stage.ready" in kinds


def test_state_survives_reopening_the_database(tmp_path):
    path = tmp_path / "n.db"
    run = Orchestrator(path).submit_run(two_step(), now=T0)
    again = Orchestrator(path)
    assert [s.stage_key for s in again.stages(run)] == ["ingest", "index"]
    assert again.claim_next("w1", now=T0 + 1).stage_key == "ingest"


def test_two_processes_sharing_the_database_cannot_claim_the_same_stage(tmp_path):
    path = tmp_path / "n.db"
    a, b = Orchestrator(path), Orchestrator(path)
    a.submit_run(PipelineDefinition("demo", "1", [StageDef("ingest")]), now=T0)
    claims = [a.claim_next("w1", now=T0), b.claim_next("w2", now=T0)]
    assert sum(c is not None for c in claims) == 1


def test_an_ended_attempt_cannot_be_changed(orch):
    orch.submit_run(two_step(), now=T0)
    c1 = orch.claim_next("w1", now=T0)
    orch.complete(c1.attempt_id, now=T0 + 1)
    with pytest.raises(ValueError):
        orch.fail(c1.attempt_id, "internal", retryable=True, now=T0 + 2)


def test_a_pipeline_cannot_depend_on_a_stage_declared_later():
    with pytest.raises(ValueError):
        PipelineDefinition("bad", "1", [StageDef("a", depends_on=("b",)), StageDef("b")])
