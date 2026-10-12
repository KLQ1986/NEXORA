"""The reference RunPod workers and NEXORA's adapters, talking to each other through RunPod's job protocol.

The stand-in server here only carries jobs: what answers is the worker in `runpod/worker.py`, so a change to either
side of the contract that the other side does not follow fails here.
"""
import http.server
import importlib.util
import json
import subprocess
import threading
from pathlib import Path

import pytest
from PIL import Image

from nexora.adapters.runpod import RunPodImage, RunPodLipSync, RunPodTrainer, RunPodUpscale, RunPodVideo
from nexora.core.adapter import PrivacyClass, Request

from tests.conftest import make_video
from tests.library.test_sync import room_sound

spec = importlib.util.spec_from_file_location("nexora_runpod_worker", Path(__file__).resolve().parents[2] / "runpod" / "worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


@pytest.fixture
def endpoint():
    """One server standing for RunPod: /<task>/run starts the worker of that task, /<task>/status/<id> returns what it made."""
    done = {}

    class Carrier(http.server.BaseHTTPRequestHandler):
        def _send(self, body):
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(body).encode())
        def do_POST(self):
            task = self.path.split("/")[1]
            job = {"id": f"{task}-{len(done) + 1}", "input": json.loads(self.rfile.read(int(self.headers["content-length"])))["input"]}
            done[job["id"]] = worker.HANDLERS[task](job)
            self._send({"id": job["id"], "status": "IN_QUEUE"})
        def do_GET(self):
            job = self.path.rsplit("/", 1)[-1]
            self._send({"id": job, "status": "COMPLETED", "executionTime": 3000, "output": done[job]})
        def log_message(self, *a): pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Carrier)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield lambda cls, task: cls("k", task, host=f"http://127.0.0.1:{server.server_port}", poll_seconds=0.01)
    server.shutdown()


def shape(path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()


def ask(adapter, operation, tmp_path, out_name, inputs, **params):
    return adapter.submit(Request(operation, inputs=inputs, params={"out": str(tmp_path / out_name), **params}, privacy_class=PrivacyClass.CLOUD_ALLOWED))


def test_every_reference_worker_answers_its_adapter(endpoint, tmp_path):
    Image.new("RGB", (640, 360), "teal").save(tmp_path / "key.png")
    clip = make_video(tmp_path / "clip.mp4", picture=2)
    sound = room_sound(tmp_path / "line.wav", 4, seconds=2)

    made = ask(endpoint(RunPodImage, "image"), "generate", tmp_path, "still.png", {"prompt": "a cat", "references": [str(tmp_path / "key.png")], "model_urls": ["https://example.test/m.safetensors"]}, seed=9, aspect="9:16")
    assert Image.open(tmp_path / "still.png").size == (720, 1280) and made.outputs["model"] == "stand-in-flat"

    made = ask(endpoint(RunPodVideo, "video"), "generate", tmp_path, "shot.mp4", {"prompt": "a cat", "first_frame": str(tmp_path / "still.png")}, duration=2.0, seed=9, aspect="9:16", camera="slow push in")
    assert shape(tmp_path / "shot.mp4") == "720,1280" and made.usage.units == 3.0

    ask(endpoint(RunPodUpscale, "upscale"), "upscale", tmp_path, "big.mp4", {"video": str(clip)}, scale=2)
    assert shape(tmp_path / "big.mp4") == "640,360"

    ask(endpoint(RunPodLipSync, "lipsync"), "sync", tmp_path, "synced.mp4", {"video": str(clip), "audio": str(sound)})
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(tmp_path / "synced.mp4")], capture_output=True, text=True).stdout.split()
    assert sorted(streams) == ["audio", "video"]

    trained = ask(endpoint(RunPodTrainer, "train"), "train", tmp_path, "mit.safetensors", {"images": [str(tmp_path / "key.png")] * 4}, name="Mít", trigger="nxmit")
    assert (tmp_path / "mit.safetensors").read_bytes().startswith(b"NOT-A-MODEL") and trained.outputs["model"] == "stand-in-no-training"      # and says plainly that it is not one
    assert set(worker.HANDLERS) == {"video", "image", "lipsync", "upscale", "train"}
