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


def test_every_adapter_of_the_installation_describes_itself_within_the_contract(tmp_path):
    """Adapters added since the first two: each names itself, lists its operations, says where it runs, and refuses an operation it does not have."""
    from nexora.adapters.claude import ClaudeText
    from nexora.adapters.desktop import DesktopNotifier
    from nexora.adapters.graphics import CaptionAdapter
    from nexora.adapters.motion import StillMotion
    from nexora.adapters.ollama import OllamaAdapter
    from nexora.adapters.openmontage import OpenMontageStock
    from nexora.adapters.outbox import FolderPublisher
    from nexora.adapters.pollinations import PollinationsImage
    from nexora.adapters.speech import WhisperCpp
    from nexora.adapters.voice import SayVoice
    from nexora.adapters.web import WebReader
    from nexora.adapters.runpod import RunPodImage, RunPodLipSync, RunPodTrainer, RunPodUpscale, RunPodVideo
    from nexora.adapters.youtube import YouTubePublisher
    rented = [cls("k", "ep") for cls in (RunPodImage, RunPodVideo, RunPodLipSync, RunPodUpscale, RunPodTrainer)] + [YouTubePublisher("c", "s", "r")]
    adapters = [*rented, ClaudeText("k"), DesktopNotifier(), CaptionAdapter(), StillMotion(), OllamaAdapter(), OpenMontageStock(tmp_path / "none"), FolderPublisher(tmp_path / "out"),
                PollinationsImage(), WhisperCpp(tmp_path / "none.bin"), SayVoice(), WebReader()]
    registry, cloud = AdapterRegistry(), set()
    for adapter in adapters:
        cap = adapter.describe()
        assert isinstance(cap, Capability) and cap.name and cap.operations and cap.runs in ("local", "cloud")
        registry.register(adapter)
        cloud |= {cap.name} if cap.runs == "cloud" else set()
        with pytest.raises(AdapterError) as unsupported:
            registry.submit(cap.name, Request("no-such-operation", privacy_class=PrivacyClass.CLOUD_ALLOWED))
        assert unsupported.value.code is ErrorCode.INVALID_REQUEST
    assert len({a.describe().name for a in adapters}) == len(adapters)
    # Everything that reaches outside this machine says so, and so falls under privacy mode.
    assert cloud == {"model.claude", "stock", "image_gen.pollinations", "web", "image_gen.runpod", "video_gen.runpod", "lipsync.runpod", "upscale.runpod", "train.runpod", "publish.youtube"}
    registry.local_only = lambda: True
    for name in cloud:
        with pytest.raises(AdapterError) as kept_in:
            registry.submit(name, Request(registry._adapters[name].describe().operations[0], privacy_class=PrivacyClass.CLOUD_ALLOWED))
        assert kept_in.value.code is ErrorCode.AUTH


def test_the_model_adapter_sends_each_kind_of_work_to_the_model_chosen_for_it():
    from nexora.adapters.ollama import OllamaAdapter
    from nexora.core.adapter import Request
    one = OllamaAdapter()
    assert one.model_for(Request("chat", params={"prompt": "x"})) == one.vision_model                 # nothing chosen: one model does all
    many = OllamaAdapter(vision_model="see", judge_model="judge", writer_model="write")
    assert many.model_for(Request("describe", params={"prompt": "x"})) == "see"
    assert many.model_for(Request("describe", params={"prompt": "x", "task": "focus"})) == "judge"
    assert many.model_for(Request("chat", params={"prompt": "x"})) == "write"


def test_stock_searches_pexels_and_pixabay_once_their_keys_are_given_and_hands_the_keys_to_the_child(tmp_path, monkeypatch):
    import json as _json
    from nexora.adapters import openmontage
    from nexora.core.adapter import Request
    from nexora.core.process import Completed
    (tmp_path / "om").mkdir()
    seen = {}

    def fake(cmd, *, timeout, cwd=None, stdin=None, env=None):
        seen.update(payload=_json.loads(stdin), env=env)
        return Completed(0, "@@NEXORA@@" + _json.dumps({"success": True, "data": {"clips": []}, "artifacts": [], "error": None, "cost_usd": 0}), "")
    monkeypatch.setattr(openmontage, "run_process", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "never-passed")

    assert openmontage.OpenMontageStock(tmp_path / "om").sources() == ["archive_org", "nasa", "wikimedia"]
    stock = openmontage.OpenMontageStock(tmp_path / "om", keys={"pexels": "pk", "pixabay_video": ""})
    stock.submit(Request("search", inputs={"queries": ["chợ nổi"]}, params={"out_dir": str(tmp_path / "out")}))
    assert seen["payload"]["inputs"]["sources"] == ["pexels", "archive_org", "nasa", "wikimedia"]
    assert seen["env"]["PEXELS_API_KEY"] == "pk" and "PIXABAY_API_KEY" not in seen["env"] and "ANTHROPIC_API_KEY" not in seen["env"]
