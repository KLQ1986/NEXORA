"""fal's queue, against a local stand-in: a picture and a clip made, a failure and a lost job reported, and a storyboard's
generated shot getting its keyframe through the project's generation."""
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nexora.adapters.fal import FalImage, FalVideo
from nexora.core.adapter import AdapterError, Request


@pytest.fixture()
def fal(tmp_path):
    files = tmp_path / "served"
    files.mkdir()
    Image.new("RGB", (64, 36), (40, 120, 80)).save(files / "out.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=1", "-pix_fmt", "yuv420p", str(files / "out.mp4")], check=True)
    state = {"posted": [], "polls": {}, "fail": False}

    class Api(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            assert self.headers["authorization"] == "Key k"
            rid = f"r{len(state['posted'])}"
            state["posted"].append((self.path, body))
            base = f"http://127.0.0.1:{self.server.server_address[1]}{self.path}/requests/{rid}"
            self._json(200, {"request_id": rid, "status_url": base + "/status", "response_url": base, "cancel_url": base + "/cancel"})

        def do_GET(self):
            host = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path.startswith("/files/"):
                data = (files / self.path.rsplit("/", 1)[-1]).read_bytes()
                self.send_response(200)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            rid = self.path.split("/requests/")[1].split("/")[0]
            if self.path.endswith("/status"):
                n = state["polls"][rid] = state["polls"].get(rid, 0) + 1
                return self._json(200, {"status": "FAILED", "error": "nsfw"} if state["fail"] else {"status": "IN_PROGRESS" if n < 2 else "COMPLETED"})
            video = "video" in self.path
            self._json(200, {"video": {"url": f"{host}/files/out.mp4"}} if video else {"images": [{"url": f"{host}/files/out.png"}]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"host": f"http://127.0.0.1:{server.server_address[1]}", "state": state}
    server.shutdown()


def test_a_picture_and_a_clip_come_back_through_the_queue(fal, tmp_path):
    image = FalImage("k", "fal-ai/flux/dev", host=fal["host"], poll_seconds=0.01, price=0.025)
    ref = tmp_path / "ref.png"
    Image.new("RGB", (8, 8)).save(ref)
    made = image.submit(Request("generate", inputs={"prompt": "vườn dừa lúc bình minh", "references": [str(ref)]}, params={"out": str(tmp_path / "k.png"), "seed": 7, "aspect": "9:16"}))
    path, body = fal["state"]["posted"][0]
    assert path == "/fal-ai/flux/dev" and body["image_size"] == "portrait_16_9" and body["seed"] == 7 and body["image_url"].startswith("data:image/png;base64,")
    assert Image.open(tmp_path / "k.png").size == (64, 36) and made.usage.cost == 0.025 and made.external_ref == "r0"
    video = FalVideo("k", "fal-ai/kling-video/v2.1/standard/image-to-video", host=fal["host"], poll_seconds=0.01, price=0.07)
    clip = video.submit(Request("generate", inputs={"prompt": "máy đẩy tới", "first_frame": str(tmp_path / "k.png")}, params={"out": str(tmp_path / "c.mp4"), "duration": 8, "aspect": "16:9"}))
    _, body = fal["state"]["posted"][1]
    assert body["duration"] == "10" and body["image_url"].startswith("data:image/png") and (tmp_path / "c.mp4").stat().st_size > 1000
    assert clip.usage.units == 10.0 and clip.usage.cost == 0.7


def test_a_failed_request_is_reported_and_without_a_key_fal_is_not_offered(fal, tmp_path):
    fal["state"]["fail"] = True
    with pytest.raises(AdapterError) as err:
        FalImage("k", "fal-ai/flux/dev", host=fal["host"], poll_seconds=0.01).submit(Request("generate", inputs={"prompt": "x"}, params={"out": str(tmp_path / "x.png")}))
    assert "FAILED" in str(err.value) and "nsfw" in str(err.value)
    assert FalImage("", "fal-ai/flux/dev").environment()["available"] is False


def test_a_storyboard_s_generated_shot_gets_its_keyframe_from_fal(fal, tmp_path):
    from nexora.api.app import create_app
    from nexora.app import build
    from tests.fakes import FakeModel
    from tests.visual_quality.test_vq import drain
    system = build(tmp_path / "data", model=FakeModel(), generators=[FalImage("k", "fal-ai/flux/dev", host=fal["host"], poll_seconds=0.01, price=0.025)])
    client = TestClient(create_app(system))
    project = system.projects.create_project("Vườn dừa")
    system.projects.save_script(project, ["Vườn dừa lúc bình minh, sương trên tán."])
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "set", "shot": "SC1", "field": "source.policy", "value": "generate"},
                                                                           {"op": "set", "shot": "SC1", "field": "generation.provider", "value": "image_gen.fal"}]})
    assert client.get(f"/api/v1/projects/{project}/storyboard").json()["providers"]["image_providers"][0]["name"] == "image_gen.fal"
    client.post(f"/api/v1/projects/{project}/storyboard/keyframes")
    drain(system)
    assert fal["state"]["posted"] and "vườn dừa" in fal["state"]["posted"][0][1]["prompt"].lower()
    client.post(f"/api/v1/projects/{project}/storyboard/run", json={})
    shot = client.get(f"/api/v1/projects/{project}/storyboard").json()["shots"][0]
    assert shot["assignment"]["kind"] == "generated" and shot["frame_url"].startswith("/media/") and shot["state"] == "needs"
