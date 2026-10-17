"""Visual Quality's RunPod endpoint, end to end without a GPU: the worker in runpod/vq_worker (its models stood in for by
VQ_WORKER_FAKE) behind a local stand-in for RunPod's job API, and NEXORA's client cutting, sending and joining a span."""
import base64
import importlib
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nexora.adapters import runpod_restore as RR
from nexora.adapters.runpod_restore import RunPodRestore
from nexora.core.adapter import AdapterError, Request

from tests.conftest import make_video
from tests.visual_quality.test_old_and_dark import _tape
from tests.visual_quality.test_vq import drain, vq_system

WORKER = Path(__file__).resolve().parents[2] / "runpod" / "vq_worker"


@pytest.fixture()
def endpoint(monkeypatch):
    """A local RunPod: /run runs the worker's handler at once, /status gives its answer, /health answers while it is on."""
    monkeypatch.setenv("VQ_WORKER_FAKE", "1")
    monkeypatch.syspath_prepend(str(WORKER))
    for name in ("models", "handler"):
        sys.modules.pop(name, None)
    handler = importlib.import_module("handler")
    jobs, state = {}, {"on": True, "runs": 0}

    class Api(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not state["on"]:
                return self._send(503, {"error": "off"})
            if self.path.endswith("/health"):
                return self._send(200, {"workers": {"idle": 1, "running": 0}, "jobs": {"inQueue": 0}})
            job = jobs.get(self.path.rsplit("/", 1)[-1])
            self._send(200, job or {"status": "FAILED", "error": "no such job"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            assert len(json.dumps(body)) <= RR.MAX_PAYLOAD
            state["runs"] += 1
            out = handler.handler({"input": body["input"]})
            jid = f"job{len(jobs)}"
            jobs[jid] = {"status": "FAILED", "error": out["error"]} if "error" in out else {"status": "COMPLETED", "output": out, "executionTime": 1500}
            self._send(200, {"id": jid, "status": "IN_QUEUE"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"host": f"http://127.0.0.1:{server.server_address[1]}", "state": state}
    server.shutdown()


def _frames(path: Path) -> tuple[int, int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=width,height,nb_read_packets",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip().split(",")
    return int(out[0]), int(out[1]), int(out[2])


def test_the_client_sends_a_span_in_overlapping_chunks_and_joins_them_frame_exactly(endpoint, tmp_path, monkeypatch):
    src = make_video(tmp_path / "span.mp4", picture=4, size="320x180", rate=25)
    client = RunPodRestore("key", "vq", host=endpoint["host"], poll_seconds=0.05)
    assert client.environment()["available"] and "restore" in client.environment()["tasks"]
    whole = client.submit(Request("upscale", inputs={"video": str(src)}, params={"out": str(tmp_path / "one.mov"), "task": "upscale", "height": 360}))
    assert whole.outputs["chunks"] == 1 and _frames(tmp_path / "one.mov") == (640, 360, 100)
    monkeypatch.setattr(RR, "MAX_CHUNK", 40)                       # force chunks: 24 own frames each, 8 shared on each side
    runs = endpoint["state"]["runs"]
    cut = client.submit(Request("deblur", inputs={"video": str(src)}, params={"out": str(tmp_path / "many.mov"), "task": "deblur"}))
    mp4 = client.submit(Request("denoise", inputs={"video": str(src)}, params={"out": str(tmp_path / "many.mp4"), "task": "denoise", "sigma": 4}))
    assert mp4.outputs["chunks"] == 5 and _frames(tmp_path / "many.mp4") == (320, 180, 100)
    assert cut.outputs["chunks"] == 5 and endpoint["state"]["runs"] - runs == 10
    assert _frames(tmp_path / "many.mov") == (320, 180, 100)
    # The frames come back in their places: frame 50 of the result is frame 50 of the source.
    pick = lambda p, n: subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"select=eq(n\\,{n}),scale=32:18", "-frames:v", "1", "-f", "rawvideo",
                                        "-pix_fmt", "gray", "-"], capture_output=True).stdout
    a, b = pick(src, 50), pick(tmp_path / "many.mov", 50)
    assert sum(abs(x - y) for x, y in zip(a, b)) / len(a) < 6
    assert cut.usage.units == pytest.approx(7.5)                   # five jobs of 1.5 s each, as RunPod reported them


def test_an_endpoint_that_is_off_is_not_offered_and_a_task_it_lacks_is_refused(endpoint, tmp_path):
    endpoint["state"]["on"] = False
    client = RunPodRestore("key", "vq", host=endpoint["host"], poll_seconds=0.05, tasks=("deblur",))
    assert client.environment()["available"] is False
    with pytest.raises(AdapterError):
        client.submit(Request("faces", inputs={"video": str(tmp_path / "x.mp4")}, params={"out": str(tmp_path / "y.mov"), "task": "faces"}))


def test_old_footage_allowed_out_is_restored_on_the_endpoint_and_previewed(endpoint, tmp_path):
    system = vq_system(tmp_path)
    system.adapters.register(RunPodRestore("key", "vq", host=endpoint["host"], poll_seconds=0.05))
    subject = system.vq.subject_for_file(_tape(tmp_path / "in" / "tape.mp4", seconds=1))
    system.vq.analyse(subject, allow_cloud=True, stabilise=False)
    drain(system)
    recipe = system.vq_reader.recipe(subject)
    steps = recipe.shots[0]["steps"]
    restore = next(s for s in steps if s["op"] == "restore")
    assert restore["tier"] == "remote" and restore["params"] == {"task": "restore", "height": 1080} and restore["remote"]   # 480p brought to 1080p
    assert not {"deblock", "denoise", "sharpen"} & {s["op"] for s in steps}    # the restoration does what these would
    runs = endpoint["state"]["runs"]
    system.vq.preview(subject, seconds=0.5)
    drain(system)
    preview = system.vq_reader.previews(recipe.recipe_id)[0]
    assert endpoint["state"]["runs"] > runs and preview["qa"]["verdict"] in ("pass", "warn", "fail")
    # Not allowed out, the same footage stays here.
    other = system.vq.subject_for_file(_tape(tmp_path / "in2" / "tape.mp4", seconds=1))
    system.vq.analyse(other, stabilise=False)
    drain(system)
    assert not any(s.get("tier") == "remote" for s in system.vq_reader.recipe(other).shots[0]["steps"])
