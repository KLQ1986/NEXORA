"""States of the state model (design v4.0, section 6)."""
from enum import StrEnum


class StageStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    RETRY_WAIT = "retry_wait"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset({StageStatus.SUCCEEDED, StageStatus.SKIPPED, StageStatus.FAILED, StageStatus.CANCELLED})
DONE = frozenset({StageStatus.SUCCEEDED, StageStatus.SKIPPED})   # satisfies a dependency


class AttemptOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED_TRANSIENT = "failed_transient"
    FAILED_PERMANENT = "failed_permanent"
    CRASHED = "crashed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class EffectClass(StrEnum):
    PURE = "pure"
    IDEMPOTENT_EXTERNAL = "idempotent_external"
    NON_IDEMPOTENT_EXTERNAL = "non_idempotent_external"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
