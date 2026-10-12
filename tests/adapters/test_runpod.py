"""The RunPod video adapter against a stand-in for RunPod's serverless job protocol."""
import base64
import http.server
import json
import threading

import pytest
from PIL import Image

from nexora.adapters.runpod import RunPodVideo
from nexora.app import build
from nexora.core.adapter import AdapterError, ErrorCode, PrivacyClass, Request
from nexora.core.states import RunStatus

from tests.conftest import make_video
from tests.fakes import FakeImageGen, FakeVoice


class Pod:
    """One endpoint: jobs take a few status checks to finish, and it can be told how they end."""
    def __init__(self, tmp_path):
        self.clip = make_video(tmp_path / "made.mp4", picture=2).read_bytes()
        self.runs, self.cancelled, self.checks, self.ending, self.drop = [], [], {}, "base64", 0
        pod = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _send(self, status, body):
                self.send_response(status); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(body).encode())
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length") or 0))
                if self.headers.get("authorization") != "Bearer rp-key":
                    return self._send(401, {"error": "unauthorized"})
                if self.path.endswith("/run"):
                    pod.runs.append(json.loads(body)["input"])
                    return self._send(200, {"id": f"job-{len(pod.runs)}", "status": "IN_QUEUE"})
                pod.cancelled.append(self.path.rsplit("/", 1)[-1])
                self._send(200, {"status": "CANCELLED"})
            def do_GET(self):
                job = self.path.rsplit("/", 1)[-1]
                pod.checks[job] = pod.checks.get(job, 0) + 1
                if pod.drop:
                    pod.drop -= 1
                    return self._send(503, {"error": "busy"})
                if pod.checks[job] < 3 or pod.ending == "never":
                    return self._send(200, {"id": job, "status": "IN_PROGRESS"})
                if pod.ending == "failed":
                    return self._send(200, {"id": job, "status": "FAILED", "error": "CUDA out of memory"})
                output = {"video": base64.b64encode(pod.clip).decode(), "model": "wan"} if pod.ending == "base64" else {"note": "no clip"}
                self._send(200, {"id": job, "status": "COMPLETED", "executionTime": 42000, "output": output})
            def log_message(self, *a): pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def adapter(self, key="rp-key"):
        return RunPodVideo(key, "ep1", host=f"http://127.0.0.1:{self.server.server_port}", price_per_second=0.001, poll_seconds=0.01)


@pytest.fixture
def pod(tmp_path):
    pod = Pod(tmp_path)
    yield pod
    pod.server.shutdown()


def request(tmp_path, **more):
    Image.new("RGB", (64, 36), "teal").save(tmp_path / "key.png")
    return Request("generate", inputs={"prompt": "a cat by a window", "first_frame": str(tmp_path / "key.png")}, params={"out": str(tmp_path / "clip.mp4"), "duration": 4.0, "seed": 7, "aspect": "9:16", "camera": "pan left"},
                   privacy_class=PrivacyClass.CLOUD_ALLOWED, **more)


def test_a_job_is_submitted_once_followed_to_its_end_and_its_clip_and_cost_are_kept(pod, tmp_path):
    pod.drop = 2                                              # the connection is lost twice while waiting
    result = pod.adapter().submit(request(tmp_path))
    assert (tmp_path / "clip.mp4").read_bytes() == pod.clip and result.external_ref == "job-1" and result.outputs["model"] == "wan"
    assert result.usage.units == 42.0 and result.usage.cost == pytest.approx(0.042)
    sent = pod.runs[0]
    assert len(pod.runs) == 1 and (sent["prompt"], sent["seconds"], sent["seed"], sent["aspect"], sent["camera"]) == ("a cat by a window", 4.0, 7, "9:16", "pan left")
    assert base64.b64decode(sent["image"]) == (tmp_path / "key.png").read_bytes()
    assert pod.adapter().describe().runs == "cloud" and pod.adapter().describe().name == "video_gen.runpod"


def test_a_failed_job_a_job_without_a_clip_a_bad_key_and_a_job_that_never_ends_are_each_named(pod, tmp_path):
    pod.ending = "failed"
    with pytest.raises(AdapterError) as failed:
        pod.adapter().submit(request(tmp_path))
    assert failed.value.code is ErrorCode.INTERNAL and "CUDA out of memory" in failed.value.message and not failed.value.retryable
    pod.ending = "empty"
    with pytest.raises(AdapterError) as empty:
        pod.adapter().submit(request(tmp_path))
    assert empty.value.code is ErrorCode.OUTPUT_INVALID and "video_url" in empty.value.message
    with pytest.raises(AdapterError) as denied:
        pod.adapter(key="wrong").submit(request(tmp_path))
    assert denied.value.code is ErrorCode.AUTH
    pod.ending = "never"
    with pytest.raises(AdapterError) as slow:
        pod.adapter().submit(request(tmp_path, deadline_seconds=0.2))
    assert slow.value.code is ErrorCode.TIMEOUT and pod.cancelled == ["job-3"]        # billed by the second: it is not left running


def test_a_job_whose_answer_was_lost_is_found_again_by_its_id(pod, tmp_path):
    adapter = pod.adapter()
    adapter.submit(request(tmp_path))
    again = Request("generate", inputs={"job": "job-1"}, params={"out": str(tmp_path / "again.mp4")})
    assert adapter.reconcile(again).files == (str(tmp_path / "again.mp4"),) and (tmp_path / "again.mp4").read_bytes() == pod.clip
    assert adapter.reconcile(Request("generate", params={"out": str(tmp_path / "x.mp4")})) is None and len(pod.runs) == 1


def test_a_generated_story_takes_its_clips_from_the_rented_endpoint_and_falls_back_when_it_is_down(pod, tmp_path):
    from nexora.adapters.motion import StillMotion
    system = build(tmp_path / "data", voice=FakeVoice(), generators=[FakeImageGen(), pod.adapter(), StillMotion()])
    pid = system.planning.create_project("Mèo")
    script = system.planning.save_script(pid, ["Mèo ngồi bên cửa sổ.", "Mèo nhìn mưa rơi."])
    run = system.generation.start(script)
    while system.worker.run_once(): pass
    system.generation.approve(run)
    pod.ending = "base64"
    while system.worker.run_once(): pass
    shots = system.projects.script(script)["shots"]
    assert [system.projects.generations(s.shot_id, kind="clip")[-1]["provider"] for s in shots] == ["runpod", "runpod"] and len(pod.runs) == 2
    assert system.orch.run_status(run) is RunStatus.WAITING_REVIEW and system.orch.run_cost(run) == pytest.approx(0.04 + 2 * 0.042)

    pod.server.shutdown()                                      # the endpoint goes away: the next story is made on this machine instead
    pid2 = system.planning.create_project("Chó")
    script2 = system.planning.save_script(pid2, ["Chó chạy trên bãi biển."])
    run2 = system.generation.start(script2)
    while system.worker.run_once(): pass
    system.generation.approve(run2)
    while system.worker.run_once(): pass
    assert system.projects.generations(system.projects.script(script2)["shots"][0].shot_id, kind="clip")[-1]["provider"] == "motion"
