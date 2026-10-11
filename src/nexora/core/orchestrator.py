"""The orchestrator: runs, stages, attempts, and the rules that move them (design v4.0, section 6).

It decides operational matters only — what may run, whether to retry, what is blocked. It knows
nothing about video. Every state change and its event are written in the same transaction.
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nexora.core import db
from nexora.core.ids import new_id
from nexora.core.pipeline import PipelineDefinition
from nexora.core.states import DONE, TERMINAL, AttemptOutcome, EffectClass, RunStatus, StageStatus

KILL_SWITCH = "kill_switch"


@dataclass(frozen=True)
class Stage:
    stage_id: str
    run_id: str
    stage_key: str
    depends_on: tuple[str, ...]
    status: StageStatus
    effect_class: EffectClass
    costly: bool
    gate: bool
    max_attempts: int
    outputs: dict | None
    blocked_reason: str | None


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    stage_id: str
    number: int
    outcome: AttemptOutcome | None
    worker_id: str
    claim_expires_at: float
    heartbeat_at: float
    external_ref: str | None
    error_code: str | None


@dataclass(frozen=True)
class Claim:
    """What a worker receives when it claims a stage."""
    attempt_id: str
    stage_id: str
    run_id: str
    stage_key: str
    attempt_number: int
    worker_id: str


@dataclass(frozen=True)
class Event:
    kind: str
    stage_id: str | None
    attempt_id: str | None
    payload: dict
    actor: str
    occurred_at: float


def _stage(row) -> Stage:
    return Stage(row["stage_id"], row["run_id"], row["stage_key"], tuple(json.loads(row["depends_on"])),
                 StageStatus(row["status"]), EffectClass(row["effect_class"]), bool(row["costly"]), bool(row["gate"]),
                 row["max_attempts"], json.loads(row["outputs"]) if row["outputs"] else None, row["blocked_reason"])


def _attempt(row) -> Attempt:
    return Attempt(row["attempt_id"], row["stage_id"], row["number"],
                   AttemptOutcome(row["outcome"]) if row["outcome"] else None, row["worker_id"],
                   row["claim_expires_at"], row["heartbeat_at"], row["external_ref"], row["error_code"])


class Orchestrator:
    def __init__(self, path: str | Path, *, lease_seconds: float = 120.0, backoff_seconds: float = 30.0,
                 guard: Callable[[Stage], str | None] | None = None):
        self._db = db.LocalConnections(path)
        self._lease = lease_seconds
        self._backoff = backoff_seconds
        self._guard = guard            # policy and budget check at dispatch; returns a reason to block

    @property
    def _conn(self):
        return self._db.get()

    # ------------------------------------------------------------------ reads
    def stages(self, run_id: str) -> list[Stage]:
        rows = self._conn.execute("SELECT * FROM stages WHERE run_id = ? ORDER BY position", (run_id,))
        return [_stage(r) for r in rows]

    def attempts(self, stage_id: str) -> list[Attempt]:
        rows = self._conn.execute("SELECT * FROM attempts WHERE stage_id = ? ORDER BY number", (stage_id,))
        return [_attempt(r) for r in rows]

    def attempt_rows(self, stage_id: str) -> list[dict]:
        """Attempts with their times and error text, for the run detail screen."""
        return [dict(r) for r in self._conn.execute("SELECT * FROM attempts WHERE stage_id = ? ORDER BY number", (stage_id,))]

    def events(self, run_id: str) -> list[Event]:
        rows = self._conn.execute("SELECT * FROM events WHERE run_id = ? ORDER BY event_id", (run_id,))
        return [Event(r["kind"], r["stage_id"], r["attempt_id"], json.loads(r["payload"] or "{}"), r["actor"], r["occurred_at"])
                for r in rows]

    def run_status(self, run_id: str) -> RunStatus:
        """Derived from the stages; never stored."""
        stages = self.stages(run_id)
        statuses = {s.status for s in stages}
        cancel = self._conn.execute("SELECT cancel_requested FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]
        if statuses <= TERMINAL:
            if cancel and StageStatus.CANCELLED in statuses:
                return RunStatus.CANCELLED
            if StageStatus.FAILED in statuses:
                return RunStatus.FAILED
            if StageStatus.CANCELLED in statuses:
                return RunStatus.CANCELLED
            return RunStatus.SUCCEEDED
        if statuses & {StageStatus.RUNNING, StageStatus.RETRY_WAIT}:
            return RunStatus.RUNNING
        if StageStatus.READY in statuses:
            started = self._conn.execute(
                "SELECT 1 FROM attempts a JOIN stages s USING (stage_id) WHERE s.run_id = ? LIMIT 1", (run_id,)).fetchone()
            any_done = statuses & TERMINAL
            return RunStatus.RUNNING if (started or any_done) else RunStatus.QUEUED
        if StageStatus.WAITING_REVIEW in statuses:
            return RunStatus.WAITING_REVIEW
        if StageStatus.BLOCKED in statuses:
            return RunStatus.BLOCKED
        if StageStatus.FAILED in statuses:
            return RunStatus.FAILED     # a stage failed and what remains can never run
        return RunStatus.QUEUED

    def run_info(self, run_id: str) -> dict | None:
        row = self._conn.execute("SELECT run_id, pipeline_id, project_id, subject_ref, budget_cap, created_at FROM runs "
                                 "WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def runs(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC, run_id DESC")]

    def runs_for_subject(self, subject_ref: str) -> list[str]:
        rows = self._conn.execute("SELECT run_id FROM runs WHERE subject_ref = ? ORDER BY created_at DESC, run_id DESC", (subject_ref,))
        return [r[0] for r in rows]

    def pipeline_of(self, run_id: str) -> str:
        return self._conn.execute("SELECT pipeline_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]

    def run_cost(self, run_id: str) -> float:
        return self._conn.execute("SELECT COALESCE(SUM(cost), 0) FROM cost_records WHERE run_id = ?", (run_id,)).fetchone()[0]

    def notifications(self, *, unread_only: bool = False, limit: int = 50) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM notifications WHERE (? = 0 OR read_at IS NULL) ORDER BY notification_id DESC LIMIT ?",
                                  (int(unread_only), limit))
        return [dict(r) for r in rows]

    def notify(self, kind: str, run_id: str, *, stage_key: str | None = None, reason: str | None = None) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO notifications (kind, run_id, stage_key, reason, created_at) VALUES (?,?,?,?,?)",
                      (kind, run_id, stage_key, reason, time.time()))

    def mark_notifications_read(self) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE notifications SET read_at = ? WHERE read_at IS NULL", (time.time(),))

    def notifications_after(self, notification_id: int) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM notifications WHERE notification_id > ? ORDER BY notification_id", (notification_id,))
        return [dict(r) for r in rows]

    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def record_call(self, entry: dict) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO calls (at, adapter, operation, runs, seconds, ok, error_code, attempt_id, units, cost) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (entry["at"], entry["adapter"], entry["operation"], entry["runs"], entry["seconds"], int(entry["ok"]), entry["error_code"],
                       entry["attempt_id"], entry["units"], entry["cost"]))

    def usage(self, *, since: float = 0.0) -> list[dict]:
        """What every tool and model was asked to do since `since`: how often, for how long, how often it failed, what it cost."""
        rows = self._conn.execute("SELECT adapter, operation, runs, COUNT(*) AS calls, SUM(seconds) AS seconds, SUM(1 - ok) AS failures, SUM(cost) AS cost "
                                  "FROM calls WHERE at >= ? GROUP BY adapter, operation ORDER BY seconds DESC", (since,))
        return [dict(r) for r in rows]

    def spent_since(self, since: float) -> float:
        return self._conn.execute("SELECT COALESCE(SUM(cost), 0) FROM cost_records WHERE recorded_at >= ?", (since,)).fetchone()[0]

    def spend_by_day(self, days: int = 14, *, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        rows = self._conn.execute("SELECT date(recorded_at, 'unixepoch', 'localtime') AS day, SUM(cost) AS cost FROM cost_records WHERE recorded_at >= ? GROUP BY day ORDER BY day",
                                  (now - days * 86400,))
        return [dict(r) for r in rows]

    def kill_switch(self) -> bool:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (KILL_SWITCH,)).fetchone()
        return bool(row and row[0] == "1")

    def should_stop(self, attempt_id: str) -> bool:
        """A worker calls this at its safe checkpoints."""
        row = self._conn.execute(
            "SELECT r.cancel_requested FROM attempts a JOIN stages s USING (stage_id) JOIN runs r USING (run_id) "
            "WHERE a.attempt_id = ?", (attempt_id,)).fetchone()
        return bool(row and row[0])

    # ------------------------------------------------------------------ writes
    def submit_run(self, pipeline: PipelineDefinition, *, project_id: str | None = None, subject_ref: str | None = None,
                   priority: int = 0, idempotency_key: str | None = None, budget_cap: float | None = None,
                   now: float | None = None) -> str:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            if idempotency_key is not None:
                row = c.execute("SELECT run_id FROM runs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if row:
                    return row[0]
            run_id = new_id("run", now)
            c.execute("INSERT INTO runs (run_id, pipeline_id, pipeline_version, project_id, subject_ref, priority, "
                      "idempotency_key, budget_cap, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (run_id, pipeline.pipeline_id, pipeline.version, project_id, subject_ref, priority, idempotency_key,
                       budget_cap, now))
            for position, s in enumerate(pipeline.stages):
                status = StageStatus.PENDING if s.depends_on else StageStatus.READY
                c.execute("INSERT INTO stages (stage_id, run_id, position, stage_key, depends_on, status, effect_class, costly, "
                          "gate, max_attempts, timeout_seconds, lane) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (new_id("stg", now), run_id, position, s.key, json.dumps(list(s.depends_on)), status, s.effect_class,
                           int(s.costly), int(s.gate), s.max_attempts, s.timeout_seconds, s.lane))
            self._event(c, run_id, "run.submitted", now, payload={"pipeline": pipeline.pipeline_id, "version": pipeline.version})
            return run_id

    def claim_next(self, worker_id: str, *, now: float | None = None, lanes: frozenset[str] | None = None) -> Claim | None:
        """Claim the next runnable stage, or return None. One write transaction: one claimer wins.
        A worker given `lanes` takes only stages of those lanes."""
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            killed = self.kill_switch()
            rows = c.execute(
                "SELECT s.* FROM stages s JOIN runs r USING (run_id) "
                "WHERE r.cancel_requested = 0 AND (s.status = 'ready' OR (s.status = 'retry_wait' AND s.next_retry_at <= ?)) "
                "ORDER BY r.priority DESC, r.created_at, s.position", (now,)).fetchall()
            for row in rows:
                stage = _stage(row)
                if lanes is not None and row["lane"] not in lanes:
                    continue
                if killed and (stage.costly or stage.effect_class is not EffectClass.PURE):
                    continue
                reason = self._guard(stage) if self._guard else None
                if not reason and stage.costly and self._over_budget(c, stage.run_id):
                    reason = "budget_exceeded"
                if not reason and stage.costly:
                    reason = self._over_period_budget(c, now)
                if reason:
                    self._set_status(c, stage, StageStatus.BLOCKED, now, blocked_reason=reason)
                    continue
                number = c.execute("SELECT COUNT(*) FROM attempts WHERE stage_id = ?", (stage.stage_id,)).fetchone()[0] + 1
                attempt_id = new_id("att", now)
                c.execute("INSERT INTO attempts (attempt_id, stage_id, number, worker_id, claim_expires_at, heartbeat_at, started_at) "
                          "VALUES (?,?,?,?,?,?,?)", (attempt_id, stage.stage_id, number, worker_id, now + self._lease, now, now))
                c.execute("UPDATE stages SET status = 'running', blocked_reason = NULL, next_retry_at = NULL WHERE stage_id = ?",
                          (stage.stage_id,))
                self._event(c, stage.run_id, "stage.claimed", now, stage.stage_id, attempt_id, {"worker": worker_id, "attempt": number},
                            actor=worker_id)
                return Claim(attempt_id, stage.stage_id, stage.run_id, stage.stage_key, number, worker_id)
            return None

    def heartbeat(self, attempt_id: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            c.execute("UPDATE attempts SET heartbeat_at = ?, claim_expires_at = ? WHERE attempt_id = ? AND outcome IS NULL",
                      (now, now + self._lease, attempt_id))

    def set_external_ref(self, attempt_id: str, external_ref: str, *, now: float | None = None) -> None:
        """Record a provider's job reference before waiting on it, so a crash cannot orphan the job."""
        with db.write(self._conn) as c:
            c.execute("UPDATE attempts SET external_ref = ? WHERE attempt_id = ?", (external_ref, attempt_id))

    def complete(self, attempt_id: str, *, outputs: dict | None = None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            attempt, stage = self._live(c, attempt_id)
            if self._cancel_requested(c, stage.run_id):
                self._end_attempt(c, attempt, stage, AttemptOutcome.CANCELLED, now)
                self._set_status(c, stage, StageStatus.CANCELLED, now)
                return
            self._end_attempt(c, attempt, stage, AttemptOutcome.SUCCEEDED, now)
            self._succeed(c, stage, outputs, now)

    def fail(self, attempt_id: str, error_code: str, *, retryable: bool, message: str = "", retry_after: float | None = None,
             now: float | None = None) -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            attempt, stage = self._live(c, attempt_id)
            if self._cancel_requested(c, stage.run_id):
                self._end_attempt(c, attempt, stage, AttemptOutcome.CANCELLED, now)
                self._set_status(c, stage, StageStatus.CANCELLED, now)
                return
            if not retryable:
                self._end_attempt(c, attempt, stage, AttemptOutcome.FAILED_PERMANENT, now, error_code, message)
                self._set_status(c, stage, StageStatus.FAILED, now)
                return
            self._end_attempt(c, attempt, stage, AttemptOutcome.FAILED_TRANSIENT, now, error_code, message)
            self._retry_or_block(c, stage, attempt.number, now, retry_after)

    def block(self, attempt_id: str, *, reason: str, message: str = "", now: float | None = None) -> None:
        """End an attempt on an error only the operator can fix; the stage waits for the operator."""
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            attempt, stage = self._live(c, attempt_id)
            self._end_attempt(c, attempt, stage, AttemptOutcome.FAILED_TRANSIENT, now, reason, message)
            self._set_status(c, stage, StageStatus.BLOCKED, now, blocked_reason=reason)

    def record_cost(self, attempt_id: str, *, provider: str, units: float, cost: float, currency: str = "USD",
                    now: float | None = None) -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            run_id = c.execute("SELECT s.run_id FROM attempts a JOIN stages s USING (stage_id) WHERE a.attempt_id = ?",
                               (attempt_id,)).fetchone()[0]
            c.execute("INSERT INTO cost_records (run_id, attempt_id, provider, units, cost, currency, recorded_at) "
                      "VALUES (?,?,?,?,?,?,?)", (run_id, attempt_id, provider, units, cost, currency, now))

    def recover(self, *, now: float | None = None, is_alive: Callable[[Attempt], bool] = lambda attempt: True) -> None:
        """Run at start-up and on wake. An attempt is lost when its worker is gone or its claim expired."""
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            rows = c.execute("SELECT a.* FROM attempts a JOIN stages s USING (stage_id) "
                             "WHERE a.outcome IS NULL AND s.status = 'running'").fetchall()
            for row in rows:
                attempt = _attempt(row)
                if is_alive(attempt) and attempt.claim_expires_at > now:
                    continue
                stage = _stage(c.execute("SELECT * FROM stages WHERE stage_id = ?", (attempt.stage_id,)).fetchone())
                if stage.effect_class is EffectClass.PURE:
                    self._end_attempt(c, attempt, stage, AttemptOutcome.CRASHED, now)
                    self._retry_or_block(c, stage, attempt.number, now, None)
                else:
                    # An external effect may have happened: never retry blindly. The stage stays
                    # running until its adapter reconciles the attempt.
                    self._end_attempt(c, attempt, stage, AttemptOutcome.UNKNOWN, now)

    def reconcile(self, attempt_id: str, *, completed: bool, outputs: dict | None = None, now: float | None = None) -> None:
        """Resolve an unknown attempt once the adapter has established what actually happened."""
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            row = c.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
            attempt = _attempt(row)
            if attempt.outcome is not AttemptOutcome.UNKNOWN:
                raise ValueError(f"attempt {attempt_id} is not unknown")
            stage = _stage(c.execute("SELECT * FROM stages WHERE stage_id = ?", (attempt.stage_id,)).fetchone())
            self._event(c, stage.run_id, "attempt.reconciled", now, stage.stage_id, attempt_id, {"completed": completed})
            if completed:
                self._succeed(c, stage, outputs, now)
            else:
                self._retry_or_block(c, stage, attempt.number, now, None)

    def decide_review(self, stage_id: str, *, approve: bool, now: float | None = None, actor: str = "operator") -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            stage = self._expect(c, stage_id, StageStatus.WAITING_REVIEW)
            self._event(c, stage.run_id, "review.decided", now, stage_id, payload={"approve": approve}, actor=actor)
            if approve:
                self._set_status(c, stage, StageStatus.SUCCEEDED, now)
                self._promote(c, stage.run_id, now)
            else:
                self._set_status(c, stage, StageStatus.READY, now)

    def resume(self, stage_id: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            stage = self._expect(c, stage_id, StageStatus.BLOCKED)
            self._set_status(c, stage, StageStatus.READY, now, actor="operator")

    def skip(self, stage_id: str, *, reason: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            stage = _stage(c.execute("SELECT * FROM stages WHERE stage_id = ?", (stage_id,)).fetchone())
            if stage.status not in (StageStatus.PENDING, StageStatus.READY):
                raise ValueError(f"cannot skip a stage that is {stage.status}")
            self._set_status(c, stage, StageStatus.SKIPPED, now, payload={"reason": reason})
            self._promote(c, stage.run_id, now)

    def cancel_run(self, run_id: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with db.write(self._conn) as c:
            c.execute("UPDATE runs SET cancel_requested = 1 WHERE run_id = ?", (run_id,))
            self._event(c, run_id, "run.cancel_requested", now, actor="operator")
            for row in c.execute("SELECT * FROM stages WHERE run_id = ?", (run_id,)).fetchall():
                stage = _stage(row)
                if stage.status not in TERMINAL and stage.status is not StageStatus.RUNNING:
                    self._set_status(c, stage, StageStatus.CANCELLED, now)

    def supersede(self, pipeline_id: str, subject_ref: str, *, now: float | None = None) -> int:
        """Before a new run of the same work on the same subject: withdraw the earlier ones that are still waiting on someone.
        Otherwise an old review nobody will ever answer keeps asking for attention."""
        withdrawn = 0
        for run_id in self.runs_for_subject(subject_ref):
            if self.pipeline_of(run_id) == pipeline_id and self.run_status(run_id) in (RunStatus.WAITING_REVIEW, RunStatus.BLOCKED, RunStatus.QUEUED):
                self.cancel_run(run_id, now=now)
                withdrawn += 1
        return withdrawn

    def set_kill_switch(self, on: bool, *, now: float | None = None) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (KILL_SWITCH, "1" if on else "0"))

    # ------------------------------------------------------------------ internals
    def _event(self, c, run_id, kind, now, stage_id=None, attempt_id=None, payload=None, actor="core"):
        c.execute("INSERT INTO events (run_id, stage_id, attempt_id, kind, payload, actor, occurred_at) VALUES (?,?,?,?,?,?,?)",
                  (run_id, stage_id, attempt_id, kind, json.dumps(payload or {}), actor, now))

    def _set_status(self, c, stage: Stage, status: StageStatus, now, *, blocked_reason=None, next_retry_at=None,
                    payload=None, actor="core"):
        c.execute("UPDATE stages SET status = ?, blocked_reason = ?, next_retry_at = ? WHERE stage_id = ?",
                  (status, blocked_reason, next_retry_at, stage.stage_id))
        body = dict(payload or {})
        if blocked_reason:
            body["reason"] = blocked_reason
        self._event(c, stage.run_id, f"stage.{status}", now, stage.stage_id, payload=body, actor=actor)
        if status in (StageStatus.BLOCKED, StageStatus.FAILED, StageStatus.WAITING_REVIEW):
            c.execute("INSERT INTO notifications (kind, run_id, stage_key, reason, created_at) VALUES (?,?,?,?,?)",
                      (str(status), stage.run_id, stage.stage_key, blocked_reason, now))

    def _end_attempt(self, c, attempt: Attempt, stage: Stage, outcome: AttemptOutcome, now, error_code=None, message=None):
        c.execute("UPDATE attempts SET outcome = ?, ended_at = ?, error_code = ?, error_message = ? WHERE attempt_id = ?",
                  (outcome, now, error_code, message, attempt.attempt_id))
        self._event(c, stage.run_id, f"attempt.{outcome}", now, stage.stage_id, attempt.attempt_id,
                    {"error": error_code} if error_code else None)

    def _succeed(self, c, stage: Stage, outputs, now):
        if outputs is not None:
            c.execute("UPDATE stages SET outputs = ? WHERE stage_id = ?", (json.dumps(outputs), stage.stage_id))
        if stage.gate:
            self._set_status(c, stage, StageStatus.WAITING_REVIEW, now)
        else:
            self._set_status(c, stage, StageStatus.SUCCEEDED, now)
            self._promote(c, stage.run_id, now)

    def _retry_or_block(self, c, stage: Stage, attempts_made: int, now, retry_after):
        if attempts_made >= stage.max_attempts:
            self._set_status(c, stage, StageStatus.BLOCKED, now, blocked_reason="retry_limit")
        else:
            delay = retry_after if retry_after is not None else self._backoff * (2 ** (attempts_made - 1))
            self._set_status(c, stage, StageStatus.RETRY_WAIT, now, next_retry_at=now + delay)

    def _promote(self, c, run_id, now):
        """Move pending stages to ready once everything they depend on is done."""
        stages = [_stage(r) for r in c.execute("SELECT * FROM stages WHERE run_id = ? ORDER BY position", (run_id,))]
        done = {s.stage_key for s in stages if s.status in DONE}
        for stage in stages:
            if stage.status is StageStatus.PENDING and set(stage.depends_on) <= done:
                self._set_status(c, stage, StageStatus.READY, now)

    def _live(self, c, attempt_id) -> tuple[Attempt, Stage]:
        row = c.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        attempt = _attempt(row)
        if attempt.outcome is not None:
            raise ValueError(f"attempt {attempt_id} already ended as {attempt.outcome}; attempts are immutable")
        return attempt, _stage(c.execute("SELECT * FROM stages WHERE stage_id = ?", (attempt.stage_id,)).fetchone())

    def _expect(self, c, stage_id, status: StageStatus) -> Stage:
        stage = _stage(c.execute("SELECT * FROM stages WHERE stage_id = ?", (stage_id,)).fetchone())
        if stage.status is not status:
            raise ValueError(f"stage {stage_id} is {stage.status}, expected {status}")
        return stage

    @staticmethod
    def _over_period_budget(c, now: float) -> str | None:
        """Budgets for the day and the month, set by the operator; a paid stage does not start once one is used up."""
        t = time.localtime(now)
        day_start = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
        month_start = time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        for key, start, reason in (("budget_day", day_start, "daily_budget_exceeded"), ("budget_month", month_start, "monthly_budget_exceeded")):
            row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row and row[0] not in (None, ""):
                spent = c.execute("SELECT COALESCE(SUM(cost), 0) FROM cost_records WHERE recorded_at >= ?", (start,)).fetchone()[0]
                if spent >= float(row[0]):
                    return reason
        return None

    @staticmethod
    def _over_budget(c, run_id) -> bool:
        cap = c.execute("SELECT budget_cap FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]
        if cap is None:
            return False
        spent = c.execute("SELECT COALESCE(SUM(cost), 0) FROM cost_records WHERE run_id = ?", (run_id,)).fetchone()[0]
        return spent >= cap

    @staticmethod
    def _cancel_requested(c, run_id) -> bool:
        return bool(c.execute("SELECT cancel_requested FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0])
