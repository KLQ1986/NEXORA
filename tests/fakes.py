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
            v = [0.0] * 32
            for word in text.lower().split():
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 32] += 1.0
            vectors.append(v)
        return Result(outputs={"vectors": vectors})
