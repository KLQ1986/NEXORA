"""The worker: claims a stage, runs its handler, and reports the result to the orchestrator."""
import time
from dataclasses import dataclass, field
from typing import Callable

from nexora.core.adapter import NEEDS_OPERATOR, AdapterError, ErrorCode
from nexora.core.orchestrator import Claim, Orchestrator
from nexora.core.pipeline import PipelineRegistry
from nexora.core.states import RunStatus


@dataclass
class StageContext:
    """What a stage handler receives."""
    claim: Claim
    inputs: dict[str, dict]                      # outputs of the stages this one depends on, by stage key
    subject_ref: str | None                      # what the run is about, for example an asset id
    _orch: Orchestrator = field(repr=False)

    def should_stop(self) -> bool:
        return self._orch.should_stop(self.claim.attempt_id)

    def heartbeat(self) -> None:
        self._orch.heartbeat(self.claim.attempt_id)

    def record_cost(self, *, provider: str, units: float, cost: float, currency: str = "USD") -> None:
        self._orch.record_cost(self.claim.attempt_id, provider=provider, units=units, cost=cost, currency=currency)

    def set_external_ref(self, external_ref: str) -> None:
        self._orch.set_external_ref(self.claim.attempt_id, external_ref)


class Worker:
    def __init__(self, orch: Orchestrator, registry: PipelineRegistry, *, worker_id: str, lanes: frozenset[str] | None = None, log: Callable[[dict], None] | None = None):
        self._orch, self._registry, self.worker_id, self._lanes, self._log = orch, registry, worker_id, lanes, log

    def recover(self, *, now: float | None = None, is_alive: Callable = lambda attempt: False) -> None:
        """Run once at start-up and on wake, before claiming work."""
        self._orch.recover(now=now, is_alive=is_alive)

    def run_once(self, *, now: float | None = None) -> bool:
        """Claim and run one stage. Returns False when there was nothing to claim."""
        claim = self._orch.claim_next(self.worker_id, now=now, lanes=self._lanes)
        if claim is None:
            return False
        end = (lambda: None) if now is None else (lambda: now)
        handler = self._registry.handler(self._orch.pipeline_of(claim.run_id), claim.stage_key)
        deps = {s.stage_key: (s.outputs or {}) for s in self._orch.stages(claim.run_id)}
        me = next(s for s in self._orch.stages(claim.run_id) if s.stage_id == claim.stage_id)
        ctx = StageContext(claim, {k: deps[k] for k in me.depends_on}, self._orch.run_info(claim.run_id)["subject_ref"], self._orch)
        began, result = time.time(), "succeeded"
        try:
            outputs = handler(ctx)
        except AdapterError as err:
            result = f"{err.code.value}: {err.message}"
            if err.code in NEEDS_OPERATOR:
                self._orch.block(claim.attempt_id, reason=err.code.value, message=err.message, now=end())
            else:
                self._orch.fail(claim.attempt_id, err.code.value, retryable=err.retryable, message=err.message,
                                retry_after=err.retry_after, now=end())
        except Exception as err:                 # a bug in a handler must not take the worker down
            result = f"internal: {err!r}"
            self._orch.fail(claim.attempt_id, ErrorCode.INTERNAL.value, retryable=True, message=repr(err), now=end())
        else:
            self._orch.complete(claim.attempt_id, outputs=outputs or {}, now=end())
            if (outputs or {}).get("auto_approve") is True:       # a gate set to confidence-based acceptance, and the handler vouches for the result
                self._orch.decide_review(claim.stage_id, approve=True, now=end(), actor="policy")
            follow_up = self._registry.on_success(self._orch.pipeline_of(claim.run_id))
            if self._orch.run_status(claim.run_id) is RunStatus.SUCCEEDED:
                self._orch.notify("succeeded", claim.run_id)
                if follow_up:
                    follow_up(claim.run_id, ctx.subject_ref)
        if self._log:
            self._log({"at": round(began, 3), "seconds": round(time.time() - began, 3), "worker": self.worker_id, "run_id": claim.run_id,
                       "pipeline": self._orch.pipeline_of(claim.run_id), "stage": claim.stage_key, "attempt": claim.attempt_number, "result": result})
        return True

    def run_forever(self, *, idle_seconds: float = 2.0, stop: Callable[[], bool] = lambda: False, recover: bool = True) -> None:
        if recover:
            self.recover()
        while not stop():
            if not self.run_once():
                time.sleep(idle_seconds)
