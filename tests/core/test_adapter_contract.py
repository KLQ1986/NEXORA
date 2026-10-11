"""The adapter contract and its rules (design v4.0, section 7)."""
import sys

import pytest

from nexora.core.adapter import Adapter, AdapterError, AdapterRegistry, Capability, ErrorCode, PrivacyClass, Request, Result
from nexora.core.process import run_process


class CloudEcho(Adapter):
    def describe(self):
        return Capability(name="cloud-echo", operations=("echo",), runs="cloud")

    def submit(self, request):
        return Result(outputs={"echo": request.inputs})


class LocalEcho(CloudEcho):
    def describe(self):
        return Capability(name="local-echo", operations=("echo",), runs="local")


def test_a_local_only_request_never_reaches_a_cloud_adapter():
    registry = AdapterRegistry()
    registry.register(CloudEcho())
    with pytest.raises(AdapterError) as err:
        registry.submit("cloud-echo", Request("echo", inputs={"x": 1}, privacy_class=PrivacyClass.LOCAL_ONLY))
    assert err.value.code is ErrorCode.INVALID_REQUEST and not err.value.retryable


def test_a_cloud_allowed_request_may_use_a_cloud_adapter_and_a_local_one():
    registry = AdapterRegistry()
    registry.register(CloudEcho()); registry.register(LocalEcho())
    req = Request("echo", inputs={"x": 1}, privacy_class=PrivacyClass.CLOUD_ALLOWED)
    assert registry.submit("cloud-echo", req).outputs == {"echo": {"x": 1}}
    assert registry.submit("local-echo", Request("echo", inputs={"x": 2})).outputs == {"echo": {"x": 2}}


def test_an_unsupported_operation_is_rejected_before_the_adapter_runs():
    registry = AdapterRegistry()
    registry.register(LocalEcho())
    with pytest.raises(AdapterError) as err:
        registry.submit("local-echo", Request("render", inputs={}))
    assert err.value.code is ErrorCode.INVALID_REQUEST


def test_retryable_follows_the_error_code_unless_stated():
    assert AdapterError(ErrorCode.RATE_LIMITED, "slow down", retry_after=30).retryable
    assert AdapterError(ErrorCode.UNAVAILABLE, "down").retryable
    assert not AdapterError(ErrorCode.CONTENT_REJECTED, "refused").retryable
    assert not AdapterError(ErrorCode.INVALID_REQUEST, "bad").retryable


def test_a_child_process_that_exceeds_its_time_limit_is_stopped_and_reported_as_timeout():
    with pytest.raises(AdapterError) as err:
        run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert err.value.code is ErrorCode.TIMEOUT


def test_a_child_process_returns_its_output_and_exit_status():
    done = run_process([sys.executable, "-c", "print('hello')"], timeout=10)
    assert done.returncode == 0 and done.stdout.strip() == "hello"
