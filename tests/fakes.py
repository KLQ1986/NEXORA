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
        if request.operation == "describe" and request.params.get("task") == "focus":
            return Result(outputs={"json": {"chu_the": "giả lập", "phan": "phai"}})
        if request.operation == "describe" and request.params.get("task") == "locate":
            return Result(outputs={"json": {"khung": len(request.inputs["images"])}})
        if request.operation == "describe":
            index = request.params.get("index", 0)
            return Result(outputs={"json": {"mo_ta": f"Đoạn {index}: {WORDS[index % len(WORDS)]}.", "chu_the": [WORDS[index % len(WORDS)]],
                                            "hanh_dong": [], "boi_canh": "ngoài trời", "chu_tren_hinh": "", "co_canh": "trung"}})
        if request.operation == "chat":
            if request.params.get("json"):
                return Result(outputs={"json": {"tom_tat": "Video thử nghiệm.", "chu_de": ["thử nghiệm"], "tieu_de": "Video thử",
                                                "cau": getattr(self, "script", []), "tu_khoa": "computer keyboard"}})
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


class FakeImageGen(Adapter):
    """Draws a flat picture whose colour follows the seed, so reproducibility can be tested."""

    def __init__(self):
        self.requests = []

    def describe(self) -> Capability:
        return Capability(name="image_gen", operations=("generate",), runs="cloud")

    def submit(self, request: Request) -> Result:
        from PIL import Image
        from nexora.core.adapter import Usage
        self.requests.append(request)
        seed = request.params["seed"]
        Image.new("RGB", (640, 360), (seed % 200, seed // 7 % 200, seed // 13 % 200)).save(request.params["out"])
        return Result(outputs={"provider": "fake", "model": "fake-image-1"}, files=(request.params["out"],), usage=Usage(units=1, cost=0.02))


class FakeVideoGen(Adapter):
    def __init__(self):
        self.requests = []

    def describe(self) -> Capability:
        return Capability(name="video_gen", operations=("generate",), runs="cloud")

    def submit(self, request: Request) -> Result:
        import subprocess
        from nexora.core.adapter import Usage
        self.requests.append(request)
        d = request.params["duration"]
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", request.inputs["first_frame"], "-t", str(d),
                        "-vf", "scale=640:360,fps=25", "-pix_fmt", "yuv420p", request.params["out"]], check=True)
        return Result(outputs={"provider": "fake", "model": "fake-video-1"}, files=(request.params["out"],), usage=Usage(units=d, cost=0.1 * d))


class FakeStock(Adapter):
    def describe(self) -> Capability:
        return Capability(name="stock", operations=("search",), runs="cloud")

    def submit(self, request: Request) -> Result:
        import subprocess
        from pathlib import Path
        out = Path(request.params["out_dir"]); out.mkdir(parents=True, exist_ok=True)
        clip = out / "stock_clip.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=6",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        return Result(outputs={"clips": [{"source": "archive_org", "source_url": "https://example.org/clip", "license": "Public Domain", "creator": "", "path": str(clip)}],
                               "raw": {}}, files=(str(clip),))
