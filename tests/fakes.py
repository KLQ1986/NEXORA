"""A stand-in for a local model adapter, so tests need no model."""
import hashlib
import json

from nexora.core.adapter import Adapter, Capability, Request, Result

WORDS = ["chợ rau củ", "cá tươi trên sạp", "pha cà phê", "con đường mòn", "khung cảnh yên tĩnh"]


class FakeModel(Adapter):
    def __init__(self):
        self.calls = {"describe": 0, "chat": 0, "embed": 0}

    def describe(self) -> Capability:
        return Capability(name="model", operations=("describe", "chat", "embed"), runs="local")

    def submit(self, request: Request) -> Result:
        self.calls[request.operation] += 1
        if request.operation == "describe" and request.params.get("task") == "judge":
            line, text = set(request.params["line"].lower().split()), set(request.params["candidate_text"].lower().replace(".", "").replace(":", "").split())
            return Result(outputs={"json": {"phu_hop": 9 if len(line & text) >= 2 else 1, "ly_do": "giả lập"}})
        if request.operation == "describe" and request.params.get("task") == "locate":
            return Result(outputs={"json": {"khung": len(request.inputs["images"])}})
        if request.operation == "describe":
            index = request.params.get("index", 0)
            return Result(outputs={"json": {"mo_ta": f"Đoạn {index}: {WORDS[index % len(WORDS)]}.", "chu_the": [WORDS[index % len(WORDS)]],
                                            "hanh_dong": [], "boi_canh": "ngoài trời", "chu_tren_hinh": "", "co_canh": "trung"}})
        if request.operation == "chat":
            if request.params.get("json"):
                return Result(outputs={"json": {"tom_tat": "Video thử nghiệm.", "chu_de": ["thử nghiệm"], "tieu_de": "Video thử"}})
            return Result(outputs={"text": "Video thử nghiệm."})
        vectors = []
        for text in request.inputs["texts"]:
            v = [0.0] * 512
            for word in text.lower().split():
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 512] += 1.0
            vectors.append(v)
        return Result(outputs={"vectors": vectors})


class FakeVoice(Adapter):
    """Writes silence whose length follows the number of words, like speech would."""

    def describe(self) -> Capability:
        return Capability(name="voice", operations=("speak",), runs="local")

    def submit(self, request: Request) -> Result:
        import wave
        seconds = max(1.0, 0.3 * len(request.inputs["text"].split()))
        with wave.open(request.params["out"], "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
            w.writeframes(b"\x00\x00" * int(48000 * seconds))
        return Result(outputs={"duration": seconds}, files=(request.params["out"],))
