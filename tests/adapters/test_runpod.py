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


class ShotPod(Pod):
    """An endpoint for work on one shot's clip: it gives back a clip of its own, so the change can be seen in the cut."""
    def __init__(self, tmp_path, name):
        super().__init__(tmp_path / name)
        self.clip = make_video(tmp_path / name / "back.mp4", picture=4, size="640x360").read_bytes()


def test_lip_sync_and_model_upscaling_are_done_on_a_shot_and_the_operators_own_footage_stays_unless_allowed(tmp_path):
    from fastapi.testclient import TestClient
    from nexora.adapters.runpod import RunPodLipSync, RunPodUpscale
    from nexora.api.app import create_app
    from tests.fakes import FakeModel
    lips, bigger = ShotPod(tmp_path, "lips"), ShotPod(tmp_path, "bigger")
    make = lambda cls, pod: cls("rp-key", "ep", host=f"http://127.0.0.1:{pod.server.server_port}", price_per_second=0.001, poll_seconds=0.01)
    try:
        system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=False, shot_models=[make(RunPodLipSync, lips), make(RunPodUpscale, bigger)])
        client = TestClient(create_app(system))
        system.library.ingest(make_video(tmp_path / "own.mp4", picture=20))
        while system.worker.run_once(): pass
        pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["chợ rau củ", "cá tươi trên sạp"]}).json()["project_id"]
        client.post(f"/api/v1/projects/{pid}/match")
        while system.worker.run_once(): pass
        client.post(f"/api/v1/projects/{pid}/match/approve")
        view = client.get(f"/api/v1/projects/{pid}").json()
        assert view["remote"] == ["lipsync", "upscale"]
        first, second = (s["shot_id"] for s in view["shots"])
        client.patch(f"/api/v1/shots/{first}/treatment", json={"lipsync": True})
        client.patch(f"/api/v1/shots/{second}/treatment", json={"upscale_ml": True})

        client.post(f"/api/v1/projects/{pid}/render")
        while system.worker.run_once(): pass
        render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]
        assert lips.runs == [] and bigger.runs == []                                   # the operator's own footage did not leave this machine
        notes = [f for f in render["qc"]["findings"] if f["check"] in ("Khớp khẩu hình", "Phóng to bằng mô hình")]
        assert render["qc"]["passed"] and [n["shot"] for n in notes] == [1, 2] and "footage riêng" in notes[0]["text"]

        client.patch(f"/api/v1/projects/{pid}", json={"options": {"footage_may_leave": True}})         # the operator allows it for this project
        client.post(f"/api/v1/projects/{pid}/render")
        while system.worker.run_once(): pass
        render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]
        assert len(lips.runs) == 1 and len(bigger.runs) == 1 and set(lips.runs[0]) == {"video", "audio"} and bigger.runs[0]["scale"] == 2
        assert [s["remote"] for s in render["qc"]["shots"]] == [["lipsync"], ["upscale"]] and render["qc"]["passed"]
        assert not [f for f in render["qc"]["findings"] if f["check"] in ("Khớp khẩu hình", "Phóng to bằng mô hình")]
        assert system.orch.run_cost(next(r for r in system.orch.runs_for_subject(view["script"]["script_id"]) if system.orch.pipeline_of(r) == "edit.render")) == pytest.approx(0.084)

        client.post(f"/api/v1/projects/{pid}/render")                                  # nothing changed: nothing is sent or paid for again
        while system.worker.run_once(): pass
        assert len(lips.runs) == 1 and len(bigger.runs) == 1
        system.orch.set_setting("privacy_local_only", "1")
        client.patch(f"/api/v1/shots/{second}/treatment", json={"lipsync": True})
        client.post(f"/api/v1/projects/{pid}/render")
        while system.worker.run_once(): pass
        assert len(lips.runs) == 1                                                     # privacy mode overrides the project's permission
    finally:
        lips.server.shutdown(); bigger.server.shutdown()


def test_a_character_model_is_trained_from_library_pictures_and_then_loaded_for_every_shot_that_names_the_character(tmp_path):
    from fastapi.testclient import TestClient
    from nexora.adapters.runpod import RunPodTrainer
    from nexora.api.app import create_app
    from nexora.app import capabilities
    trainer = Pod(tmp_path / "trainer")

    class TrainPod(http.server.BaseHTTPRequestHandler):
        jobs = []
        def _send(self, body):
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(body).encode())
        def do_POST(self):
            TrainPod.jobs.append(json.loads(self.rfile.read(int(self.headers["content-length"])))["input"])
            self._send({"id": "train-1", "status": "IN_QUEUE"})
        def do_GET(self):
            self._send({"id": "train-1", "status": "COMPLETED", "executionTime": 600000, "output": {"model": base64.b64encode(b"LORA" * 600).decode(), "base_model": "flux"}})
        def log_message(self, *a): pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), TrainPod)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    trainer.server.shutdown()
    try:
        image = FakeImageGen()
        system = build(tmp_path / "data", voice=FakeVoice(), generators=[image, RunPodTrainer("k", "ep", host=f"http://127.0.0.1:{server.server_port}", price_per_second=0.001, poll_seconds=0.01)])
        client = TestClient(create_app(system))
        assert next(c for c in capabilities(system) if c["pipeline"] == "sourcing.train")["available"]
        pictures = []
        for i in range(5):
            Image.new("RGB", (64, 64), (200, 100 + i * 20, 40)).save(tmp_path / f"mit{i}.png")
            pictures.append(system.library.ingest(tmp_path / f"mit{i}.png")[0])
        while system.worker.run_once(): pass
        pid = client.post("/api/v1/projects", json={"title": "Mít", "lines": ["Mít ngồi bên cửa sổ.", "Trời mưa ngoài hiên."]}).json()["project_id"]
        client.patch(f"/api/v1/projects/{pid}", json={"bible": [{"name": "Mít", "kind": "character", "description": "an orange tabby cat"}]})
        assert client.post(f"/api/v1/projects/{pid}/characters/train", json={"name": "Mít", "assets": pictures[:2]}).status_code == 422       # too few pictures
        assert client.post(f"/api/v1/projects/{pid}/characters/train", json={"name": "Mít", "assets": pictures}).status_code == 202
        while system.worker.run_once(): pass
        assert TrainPod.jobs == []                                    # the operator's own pictures: not sent without the project's permission
        client.patch(f"/api/v1/projects/{pid}", json={"options": {"footage_may_leave": True}})
        run = client.post(f"/api/v1/projects/{pid}/characters/train", json={"name": "Mít", "assets": pictures}).json()["run_id"]
        while system.worker.run_once(): pass
        assert system.orch.run_status(run) is RunStatus.SUCCEEDED and system.orch.run_cost(run) == pytest.approx(0.6)
        assert len(TrainPod.jobs) == 1 and len(TrainPod.jobs[0]["images"]) == 5 and TrainPod.jobs[0]["trigger"] == "nxmit"
        entry = client.get(f"/api/v1/projects/{pid}").json()["bible"][0]
        assert entry["training"]["status"] == "done" and entry["model"].endswith(".safetensors")
        client.patch(f"/api/v1/projects/{pid}", json={"bible": [{"name": "Mít", "kind": "character", "description": "an orange tabby cat with a white chest"}]})
        assert client.get(f"/api/v1/projects/{pid}").json()["bible"][0]["model"] == entry["model"]              # editing the description keeps the trained model

        client.post(f"/api/v1/projects/{pid}/generate")
        while system.worker.run_once(): pass
        first, second = image.requests
        assert first.inputs["models"] == [entry["model"]] and "nxmit an orange tabby cat with a white chest" in first.inputs["prompt"]
        assert second.inputs["models"] == [] and "nxmit" not in second.inputs["prompt"]                          # the line that does not name the character
    finally:
        server.shutdown()


def test_the_rented_image_endpoint_gets_the_prompt_the_references_and_the_trained_models_and_returns_a_picture(tmp_path):
    import io
    from nexora.adapters.runpod import RunPodImage
    jobs = []
    picture = io.BytesIO(); Image.new("RGB", (720, 1280), "purple").save(picture, "JPEG")

    class ImagePod(http.server.BaseHTTPRequestHandler):
        def _send(self, body):
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(body).encode())
        def do_POST(self):
            jobs.append(json.loads(self.rfile.read(int(self.headers["content-length"])))["input"]); self._send({"id": "img-1", "status": "IN_QUEUE"})
        def do_GET(self):
            self._send({"id": "img-1", "status": "COMPLETED", "executionTime": 8000, "output": {"image": base64.b64encode(picture.getvalue()).decode(), "model": "flux-dev"}})
        def log_message(self, *a): pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ImagePod)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        adapter = RunPodImage("k", "ep", host=f"http://127.0.0.1:{server.server_port}", price_per_second=0.001, poll_seconds=0.01)
        Image.new("RGB", (32, 32), "orange").save(tmp_path / "ref.png")
        result = adapter.submit(Request("generate", inputs={"prompt": "nxmit an orange cat", "references": [str(tmp_path / "ref.png")], "model_urls": ["https://example.test/mit.safetensors"]},
                                        params={"out": str(tmp_path / "key.png"), "seed": 5, "aspect": "9:16"}, privacy_class=PrivacyClass.CLOUD_ALLOWED))
        made = Image.open(tmp_path / "key.png")
        assert adapter.describe().name == "image_gen.runpod" and made.format == "PNG" and made.size == (720, 1280) and result.usage.cost == pytest.approx(0.008)
        assert jobs[0]["loras"] == ["https://example.test/mit.safetensors"] and len(jobs[0]["references"]) == 1 and (jobs[0]["prompt"], jobs[0]["seed"], jobs[0]["aspect"]) == ("nxmit an orange cat", 5, "9:16")
    finally:
        server.shutdown()
