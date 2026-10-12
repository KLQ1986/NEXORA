"""Video from a model running on a RunPod serverless endpoint that the operator rents.

The endpoint is the operator's own: which model it runs and what its handler expects is their choice. This adapter
speaks RunPod's job protocol (run, status, cancel) and sends a plain input: the prompt, the approved still as base64,
the length, the seed and the shape. It reads the clip from the usual places a handler puts it: a `video_url` (or `url`)
to download, or the file itself as base64 under `video`. Only what was made for the shot is sent, never footage.

A job is paid for by the second, so nothing is ever submitted twice: once RunPod has given a job its id, a lost
connection is answered by asking about that id again, and a job that outlives the wait is cancelled.
"""
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result, Usage

FAILED = frozenset({"FAILED", "CANCELLED", "TIMED_OUT"})


MAX_PAYLOAD = 9_000_000          # RunPod refuses a job whose request is larger than about 10 MB; files travel inside it as base64


class RunPodVideo(Adapter):
    KIND, OPERATION = "video_gen", "generate"

    def __init__(self, api_key: str, endpoint_id: str, *, host: str = "https://api.runpod.ai/v2", price_per_second: float = 0.0, poll_seconds: float = 5.0, label: str = "runpod"):
        self._key, self._base, self._price, self._every, self._label = api_key, f"{host.rstrip('/')}/{endpoint_id}", price_per_second, poll_seconds, label

    def describe(self) -> Capability:
        return Capability(name=f"{self.KIND}.{self._label}", operations=(self.OPERATION,), runs="cloud", supports_cancel=True, supports_reconcile=True)

    def _start(self, payload: dict, out: Path, deadline_seconds: float | None) -> Result:
        if len(json.dumps(payload)) > MAX_PAYLOAD:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "the clip is too large to send to RunPod in one request (about 6 MB of media at most); use a shorter shot", retryable=False)
        job = self._call("POST", "/run", payload)
        if not job.get("id"):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "RunPod accepted the request but gave no job id")
        return self._wait(job["id"], out, time.time() + (deadline_seconds or 1800))

    def environment(self) -> dict:
        return {"endpoint": self._base, "key_present": bool(self._key)}

    def _call(self, method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
        req = urllib.request.Request(f"{self._base}{path}", data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"content-type": "application/json", "authorization": f"Bearer {self._key}", "accept": "application/json",
                                              "user-agent": "NEXORA/0.1"})         # RunPod's front door answers 403 (code 1010) to a client that does not name itself
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:
            code = {400: ErrorCode.INVALID_REQUEST, 401: ErrorCode.AUTH, 403: ErrorCode.AUTH, 404: ErrorCode.INVALID_REQUEST, 402: ErrorCode.QUOTA_EXHAUSTED, 429: ErrorCode.RATE_LIMITED}.get(err.code, ErrorCode.UNAVAILABLE)
            raise AdapterError(code, f"RunPod answered {err.code}: {err.read().decode(errors='replace')[:160]}") from None
        except TimeoutError:
            raise AdapterError(ErrorCode.TIMEOUT, "RunPod did not answer in time") from None
        except (urllib.error.URLError, ConnectionError, ValueError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"RunPod is not reachable: {err}") from None

    def check(self, *, rest: str = "https://rest.runpod.io/v1") -> dict:
        """Whether RunPod accepts the key and knows this endpoint, asked without starting any job (so without any charge)."""
        endpoint = self._base.rsplit("/", 1)[-1]
        req = urllib.request.Request(f"{rest}/endpoints", headers={"authorization": f"Bearer {self._key}", "accept": "application/json", "user-agent": "NEXORA/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
        except urllib.error.HTTPError as err:
            return {"ok": False, "detail": "khoá bị từ chối" if err.code in (401, 403) else f"RunPod trả lời {err.code}"}
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
            return {"ok": False, "detail": "không kết nối được tới RunPod"}
        known = [e.get("id") for e in (data if isinstance(data, list) else data.get("data", []))]
        return {"ok": endpoint in known, "detail": f"khoá được chấp nhận; endpoint {endpoint} " + ("có trên tài khoản" if endpoint in known else f"không có trên tài khoản ({len(known)} endpoint)")}

    def cancel(self, external_ref: str) -> bool:
        try:
            self._call("POST", f"/cancel/{external_ref}")
            return True
        except AdapterError:
            return False

    def _collect(self, job: dict, out: Path) -> Result:
        output = job.get("output")
        output = output[0] if isinstance(output, list) and output else output
        output = {"video_url": output} if isinstance(output, str) and output.startswith("http") else output if isinstance(output, dict) else {}
        url, data = output.get("video_url") or output.get("url"), output.get("video") or output.get("video_base64")
        out.parent.mkdir(parents=True, exist_ok=True)
        if url and str(url).lower().startswith("https://"):
            try:
                with urllib.request.urlopen(urllib.request.Request(str(url), headers={"user-agent": "NEXORA"}), timeout=300) as r:
                    out.write_bytes(r.read(2_000_000_000))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                raise AdapterError(ErrorCode.UNAVAILABLE, f"the finished clip could not be fetched: {err}") from None
        elif data:
            out.write_bytes(base64.b64decode(str(data).split(",", 1)[-1]))
        else:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the endpoint finished without a clip: its handler must return video_url (https) or video (base64)")
        if out.stat().st_size < 1000:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the endpoint returned a file too small to be a clip")
        seconds = float(job.get("executionTime") or 0) / 1000
        return Result(outputs={"provider": self._label, "model": output.get("model"), "job": job.get("id")}, files=(str(out),), external_ref=job.get("id"),
                      usage=Usage(units=seconds, cost=round(seconds * self._price, 4), measured=bool(job.get("executionTime"))))

    def _wait(self, job_id: str, out: Path, deadline: float) -> Result:
        lost = 0
        while True:
            try:
                job, lost = self._call("GET", f"/status/{job_id}"), 0
            except AdapterError as err:
                lost += 1
                if err.code in (ErrorCode.AUTH, ErrorCode.INVALID_REQUEST) or lost > 5:
                    raise
                job = {"status": "IN_QUEUE"}                    # a lost connection is not a lost job: ask again
            status = job.get("status")
            if status == "COMPLETED":
                return self._collect({**job, "id": job_id}, out)
            if status in FAILED:
                raise AdapterError(ErrorCode.INTERNAL, f"the RunPod job {status.lower()}: {str(job.get('error') or '')[:200]}", retryable=False)
            if time.time() >= deadline:
                self.cancel(job_id)                             # it is billed by the second: do not leave it running unwatched
                raise AdapterError(ErrorCode.TIMEOUT, "the RunPod job did not finish in time and was cancelled", retryable=False)
            time.sleep(self._every)

    def submit(self, request: Request) -> Result:
        still = Path(request.inputs["first_frame"])
        if not still.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{still} does not exist")
        payload = {"input": {"prompt": request.inputs["prompt"], "image": base64.b64encode(still.read_bytes()).decode(), "seconds": float(request.params["duration"]),
                             "seed": int(request.params.get("seed", 0)), "aspect": request.params.get("aspect", "16:9"), "camera": request.params.get("camera")}}
        return self._start(payload, Path(request.params["out"]), request.deadline_seconds)

    def reconcile(self, request: Request) -> Result | None:
        """What became of a job whose id is known: the clip if it finished, None if it is gone."""
        job_id = request.inputs.get("job")
        if not job_id:
            return None
        try:
            job = self._call("GET", f"/status/{job_id}")
        except AdapterError as err:
            if err.code is ErrorCode.INVALID_REQUEST:
                return None
            raise
        return self._collect({**job, "id": job_id}, Path(request.params["out"])) if job.get("status") == "COMPLETED" else None


def _b64(path: str | Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise AdapterError(ErrorCode.MISSING_INPUT, f"{path} does not exist")
    return base64.b64encode(path.read_bytes()).decode()


class RunPodLipSync(RunPodVideo):
    """A clip of a face and the sound of a line, sent to a lip-sync model on the operator's endpoint; the clip comes back with
    the mouth moving to the words. The handler gets `video` and `audio` as base64 and returns `video_url` or `video`.
    The clip leaves this machine, so the registry lets through only clips that are allowed to: generated ones, never the
    operator's own footage unless they have said so."""
    KIND, OPERATION = "lipsync", "sync"

    def submit(self, request: Request) -> Result:
        return self._start({"input": {"video": _b64(request.inputs["video"]), "audio": _b64(request.inputs["audio"])}}, Path(request.params["out"]), request.deadline_seconds)


class RunPodUpscale(RunPodVideo):
    """A short clip sent to an upscaling model on the operator's endpoint. The handler gets `video` as base64 and `scale`,
    and returns `video_url` or `video`."""
    KIND, OPERATION = "upscale", "upscale"

    def submit(self, request: Request) -> Result:
        return self._start({"input": {"video": _b64(request.inputs["video"]), "scale": int(request.params.get("scale", 2))}}, Path(request.params["out"]), request.deadline_seconds)


class RunPodTrainer(RunPodVideo):
    """Pictures of one character sent to a training endpoint; a small model of that character (a LoRA) comes back as a file.
    The handler gets `images` (base64), `name` and `trigger`, and returns `model_url` or `model` (base64). Training runs for
    minutes, so the wait is long and the job is cancelled only when it outlives it."""
    KIND, OPERATION = "train", "train"

    def _collect(self, job: dict, out: Path) -> Result:
        output = job.get("output") if isinstance(job.get("output"), dict) else {}
        result = super()._collect({**job, "output": {"video_url": output.get("model_url"), "video": output.get("model"), "model": output.get("base_model")}}, out)
        # Where the endpoint keeps the model, when it says: an image endpoint loads it from there, since the file is too large to send back up.
        return Result(outputs={**result.outputs, "model_url": output.get("model_url")}, files=result.files, external_ref=result.external_ref, usage=result.usage)

    def submit(self, request: Request) -> Result:
        images = [_b64(p) for p in request.inputs["images"]]
        if not images:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "training needs at least one picture")
        return self._start({"input": {"images": images, "name": request.params["name"], "trigger": request.params["trigger"], "steps": int(request.params.get("steps", 1000))}},
                           Path(request.params["out"]), request.deadline_seconds or 4 * 3600)


class RunPodImage(RunPodVideo):
    """Stills from an image model on the operator's endpoint. Unlike a keyless service, it can load the character models
    trained for a project: the handler gets `prompt`, `seed`, `aspect`, `references` (base64 pictures) and `loras` (the
    addresses of trained models), and returns `image_url` or `image` (base64)."""
    KIND, OPERATION = "image_gen", "generate"

    def _collect(self, job: dict, out: Path) -> Result:
        output = job.get("output")
        output = output[0] if isinstance(output, list) and output else output
        output = {"image_url": output} if isinstance(output, str) else output if isinstance(output, dict) else {}
        made = super()._collect({**job, "output": {"video_url": output.get("image_url") or output.get("url"), "video": output.get("image"), "model": output.get("model")}}, out)
        from PIL import Image
        try:
            Image.open(out).convert("RGB").save(out)            # whatever format came back, the file is the picture the caller named
        except OSError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the endpoint returned something that is not a picture") from None
        return made

    def submit(self, request: Request) -> Result:
        payload = {"input": {"prompt": request.inputs["prompt"], "seed": int(request.params.get("seed", 0)), "aspect": request.params.get("aspect", "16:9"),
                             "references": [_b64(p) for p in request.inputs.get("references") or []], "loras": list(request.inputs.get("model_urls") or [])}}
        return self._start(payload, Path(request.params["out"]), request.deadline_seconds)
