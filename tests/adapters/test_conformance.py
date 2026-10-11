"""Checks every adapter must pass (design v4.0, section 7.6). New adapters are added to ADAPTERS."""
import pytest

from nexora.adapters.media import FFmpegAdapter, FFprobeAdapter
from nexora.core.adapter import AdapterError, AdapterRegistry, Capability, ErrorCode, PrivacyClass, Request

ADAPTERS = [(FFprobeAdapter, "probe"), (FFmpegAdapter, "blackdetect")]


@pytest.mark.parametrize("cls,operation", ADAPTERS)
def test_adapter_describes_itself_and_rejects_bad_requests(cls, operation, tmp_path):
    adapter = cls()
    cap = adapter.describe()
    assert isinstance(cap, Capability) and cap.name and operation in cap.operations and cap.runs in ("local", "cloud")
    registry = AdapterRegistry()
    registry.register(adapter)
    with pytest.raises(AdapterError) as unsupported:
        registry.submit(cap.name, Request("no-such-operation"))
    assert unsupported.value.code is ErrorCode.INVALID_REQUEST
    with pytest.raises(AdapterError) as missing:
        registry.submit(cap.name, Request(operation, inputs={"path": str(tmp_path / "missing.bin")}))
    assert missing.value.code is ErrorCode.MISSING_INPUT and not missing.value.retryable
    if cap.runs == "cloud":
        with pytest.raises(AdapterError):
            registry.submit(cap.name, Request(operation, privacy_class=PrivacyClass.LOCAL_ONLY))


def test_the_model_adapter_sends_each_kind_of_work_to_the_model_chosen_for_it():
    from nexora.adapters.ollama import OllamaAdapter
    from nexora.core.adapter import Request
    one = OllamaAdapter()
    assert one.model_for(Request("chat", params={"prompt": "x"})) == one.vision_model                 # nothing chosen: one model does all
    many = OllamaAdapter(vision_model="see", judge_model="judge", writer_model="write")
    assert many.model_for(Request("describe", params={"prompt": "x"})) == "see"
    assert many.model_for(Request("describe", params={"prompt": "x", "task": "focus"})) == "judge"
    assert many.model_for(Request("chat", params={"prompt": "x"})) == "write"
