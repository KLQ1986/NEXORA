"""ComfyUI on RunPod, against a local stand-in for the endpoint: the pinned template filled from the request (types kept), a
still and a clip (animated WEBP made an MP4) coming back, a template whose bytes changed refused."""
import base64
import io
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from nexora.adapters import comfy as comfy_mod
from nexora.adapters.comfy import Comfy, ComfyVideo, fill, template
from nexora.core.adapter import AdapterError, Request


def _b64_png() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (200, 150, 60)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _b64_webp() -> str:
    buf = io.BytesIO()
    frames = [Image.new("RGB", (64, 36), (i * 20, 80, 120)) for i in range(8)]
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=166, loop=0)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture()
def runpod():
    state = {"posted": []}

    class Api(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            assert self.headers["authorization"] == "Bearer k"
            state["posted"].append(body)
            self._json({"id": f"j{len(state['posted'])}", "status": "IN_QUEUE"})

        def do_GET(self):
            body = state["posted"][int(self.path.rsplit("/j", 1)[1]) - 1]
            video = "images" in body["input"]
            file = {"filename": "nexora_00001_.webp", "type": "base64", "data": _b64_webp()} if video else {"filename": "nexora_00001_.png", "type": "base64", "data": _b64_png()}
            self._json({"status": "COMPLETED", "executionTime": 12000, "output": {"images": [file]}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"host": f"http://127.0.0.1:{server.server_address[1]}", "state": state}
    server.shutdown()


def test_a_still_and_a_clip_from_the_pinned_templates(runpod, tmp_path):
    image = Comfy("k", "ep", checkpoint="flux1-dev-fp8.safetensors", host=runpod["host"], poll_seconds=0.01, price_per_second=0.001)
    made = image.submit(Request("generate", inputs={"prompt": "vườn dừa lúc bình minh"}, params={"out": str(tmp_path / "k.png"), "seed": 7, "aspect": "9:16"}))
    graph = runpod["state"]["posted"][0]["input"]["workflow"]
    sampler = next(n for n in graph.values() if n["class_type"] == "KSampler")["inputs"]
    latent = next(n for n in graph.values() if n["class_type"] == "EmptyLatentImage")["inputs"]
    assert sampler["seed"] == 7 and isinstance(sampler["steps"], int) and (latent["width"], latent["height"]) == (576, 1024)
    assert any(n["inputs"].get("text") == "vườn dừa lúc bình minh" for n in graph.values())
    assert Image.open(tmp_path / "k.png").size == (64, 36) and made.usage.cost == 0.012 and "txt2img@" in made.outputs["model"]
    video = ComfyVideo("k", "ep", checkpoint="svd_xt.safetensors", host=runpod["host"], poll_seconds=0.01)
    video.submit(Request("generate", inputs={"prompt": "máy đẩy tới", "first_frame": str(tmp_path / "k.png")}, params={"out": str(tmp_path / "c.mp4"), "duration": 3, "seed": 7}))
    sent = runpod["state"]["posted"][1]["input"]
    cond = next(n for n in sent["workflow"].values() if n["class_type"] == "SVD_img2vid_Conditioning")["inputs"]
    assert sent["images"][0]["name"] == "keyframe.png" and cond["video_frames"] == 18
    assert (tmp_path / "c.mp4").stat().st_size > 1000 and not list(tmp_path.glob("*_comfy*"))


def test_a_changed_template_is_refused_and_an_unfilled_place_is_named(tmp_path, monkeypatch):
    shutil.copytree(comfy_mod.TEMPLATES, tmp_path / "wf")
    (tmp_path / "wf" / "txt2img.json").write_text((tmp_path / "wf" / "txt2img.json").read_text().replace("euler", "dpmpp_2m"))
    monkeypatch.setattr(comfy_mod, "TEMPLATES", tmp_path / "wf")
    with pytest.raises(AdapterError, match="not the one that was pinned"):
        template("txt2img.json")
    with pytest.raises(AdapterError, match=r"\{\{seed\}\}"):
        fill({"a": {"inputs": {"seed": "{{seed}}", "text": "x {{prompt}}"}}}, {"prompt": "y"})
    assert fill({"a": {"inputs": {"seed": "{{seed}}", "text": "x {{prompt}}"}}}, {"prompt": "y", "seed": 3}) == {"a": {"inputs": {"seed": 3, "text": "x y"}}}
