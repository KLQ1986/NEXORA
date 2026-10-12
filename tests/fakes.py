"""A stand-in for a local model adapter, so tests need no model."""
import hashlib
import json

from nexora.core.adapter import Adapter, Capability, Request, Result

WORDS = ["chợ rau củ", "cá tươi trên sạp", "pha cà phê", "con đường mòn", "khung cảnh yên tĩnh"]


class FakeModel(Adapter):
    def __init__(self):
        self.calls = {"describe": 0, "chat": 0, "embed": 0}
        self.answers = {}            # what to answer a chat by its task: a dict, or a function of the request

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
        if request.operation == "chat" and request.params.get("task") in self.answers:
            answer = self.answers[request.params["task"]]
            return Result(outputs={"json": answer(request) if callable(answer) else answer})
        if request.operation == "chat":
            if request.params.get("json"):
                return Result(outputs={"json": {"tom_tat": "Video thử nghiệm.", "chu_de": ["thử nghiệm"], "tieu_de": "Video thử",
                                                "cau": getattr(self, "script", []), "tu_khoa": "computer keyboard",
                                                "y_tuong": [{"tieu_de": "Cá tươi trên sạp buổi sớm", "mo_ta": "chợ rau củ và cá tươi trên sạp", "hop_khan_gia": 4, "co_hinh": 1, "moi_la": 3, "de_lam": 5, "rui_ro": ""},
                                                            {"tieu_de": "Tàu vũ trụ", "mo_ta": "phóng tên lửa", "hop_khan_gia": 5, "co_hinh": 5, "moi_la": 5, "de_lam": 1, "rui_ro": "Kho không có hình nào về tên lửa."}]}})
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
        # Never near black: the seed comes from a random id, and a dark still would be reported, rightly, as black frames in the cut.
        Image.new("RGB", (640, 360), (55 + seed % 200, 55 + seed // 7 % 200, 55 + seed // 13 % 200)).save(request.params["out"])
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


class FakeWeb(Adapter):
    """Pages by address, so that reading a source needs no network."""

    def __init__(self, pages: dict):
        self.pages = pages

    def describe(self) -> Capability:
        return Capability(name="web", operations=("read", "search"), runs="cloud")

    def submit(self, request: Request) -> Result:
        from nexora.core.adapter import AdapterError, ErrorCode
        if request.operation == "search":
            words = set(request.inputs["query"].lower().split())
            hits = [{"title": page.get("title", url), "url": url, "snippet": "", "language": "vi"} for url, page in self.pages.items() if words & set(page.get("title", "").lower().split())]
            return Result(outputs={"results": (hits + [{"title": "Trang hỏng", "url": "https://example.test/hong", "snippet": "", "language": "vi"}])[:request.params.get("limit", 3)]})
        url = request.inputs["url"]
        if url not in self.pages:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "the page answered 404")
        return Result(outputs={"title": "", "publisher": "", "date": "", **self.pages[url], "url": url})


class FakeSpeech(Adapter):
    """Says the same words for every recording, half a second each, with a pause where `|` stands."""

    def __init__(self, text: str = "chợ hội an buổi sáng rất đông. | ờ cá tươi nằm trên sạp. cá tươi nằm trên sạp."):
        self.text, self.calls = text, 0

    def describe(self) -> Capability:
        return Capability(name="speech", operations=("transcribe",), runs="local")

    def submit(self, request: Request) -> Result:
        self.calls += 1
        words, t = [], 0.5
        for token in self.text.split():
            if token == "|":
                t += 2.0
                continue
            words.append({"text": token, "start": round(t, 2), "end": round(t + 0.4, 2), "p": 0.2 if token == "ờ" else 0.95})
            t += 0.5
        return Result(outputs={"words": words, "language": "vi"})
