"""The adapter contract: one shape for every external capability (design v4.0, section 7).

An adapter reports; the core decides. An adapter holds no business state, writes no records and
never decides whether to retry.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    MISSING_INPUT = "missing_input"
    AUTH = "auth"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CONTENT_REJECTED = "content_rejected"
    OUTPUT_INVALID = "output_invalid"
    CANCELLED = "cancelled"
    INTERNAL = "internal"
    INSUFFICIENT_STORAGE = "insufficient_storage"


RETRYABLE = frozenset({ErrorCode.RATE_LIMITED, ErrorCode.UNAVAILABLE, ErrorCode.TIMEOUT, ErrorCode.OUTPUT_INVALID, ErrorCode.INTERNAL})
NEEDS_OPERATOR = frozenset({ErrorCode.AUTH, ErrorCode.QUOTA_EXHAUSTED, ErrorCode.INSUFFICIENT_STORAGE})   # the stage is blocked, not retried


class AdapterError(Exception):
    def __init__(self, code: ErrorCode, message: str = "", *, retryable: bool | None = None, retry_after: float | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = (code in RETRYABLE) if retryable is None else retryable
        self.retry_after = retry_after


class PrivacyClass(StrEnum):
    LOCAL_ONLY = "local_only"
    CLOUD_ALLOWED = "cloud_allowed"


@dataclass(frozen=True)
class Capability:
    name: str
    operations: tuple[str, ...]
    runs: str = "local"                # "local" or "cloud"
    supports_cancel: bool = False
    supports_reconcile: bool = False
    concurrency: int = 1


@dataclass(frozen=True)
class Usage:
    units: float = 0.0
    cost: float = 0.0
    currency: str = "USD"
    measured: bool = True


@dataclass(frozen=True)
class Request:
    operation: str
    inputs: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    privacy_class: PrivacyClass = PrivacyClass.LOCAL_ONLY
    idempotency_key: str | None = None
    deadline_seconds: float | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class Result:
    outputs: dict = field(default_factory=dict)
    files: tuple[str, ...] = ()        # paths in the staging area; the core validates and registers them
    usage: Usage = field(default_factory=Usage)
    external_ref: str | None = None
    done: bool = True                  # False: long work was started; poll with external_ref


class Adapter(ABC):
    @abstractmethod
    def describe(self) -> Capability: ...

    @abstractmethod
    def submit(self, request: Request) -> Result: ...

    def environment(self) -> dict | None:
        """What this adapter found on the machine, for the environment check; None if it has nothing to report."""
        return None

    def estimate(self, request: Request) -> Usage:
        return Usage(measured=False)

    def poll(self, external_ref: str) -> Result:
        raise AdapterError(ErrorCode.INVALID_REQUEST, "this adapter completes work inside submit")

    def cancel(self, external_ref: str) -> bool:
        return False

    def reconcile(self, request: Request) -> Result | None:
        """What actually happened to a request whose outcome is unknown; None if it never started."""
        raise AdapterError(ErrorCode.INVALID_REQUEST, "this adapter does not support reconcile")


class AdapterRegistry:
    """The single path to every adapter. Enforces what no adapter may be trusted to enforce itself."""

    def __init__(self):
        self._adapters: dict[str, Adapter] = {}

    def register(self, adapter: Adapter) -> None:
        self._adapters[adapter.describe().name] = adapter

    def describe(self) -> list[Capability]:
        return [a.describe() for a in self._adapters.values()]

    def environment(self) -> dict:
        found = {name: a.environment() for name, a in self._adapters.items()}
        return {name: value for name, value in found.items() if value is not None}

    def submit(self, name: str, request: Request) -> Result:
        adapter = self._adapters.get(name)
        if adapter is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"no adapter named {name}")
        cap = adapter.describe()
        if request.operation not in cap.operations:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"{name} does not support {request.operation}")
        if cap.runs == "cloud" and request.privacy_class is PrivacyClass.LOCAL_ONLY:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"a local-only request may not be sent to cloud adapter {name}")
        return adapter.submit(request)
