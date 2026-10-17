"""Pictures and clips from models hosted on fal (fal.ai), for the storyboard's generated shots (design 2026-10-17, phase 4).

fal runs many current image and video models behind one queue: a request is posted to `queue.fal.run/<model>`, answered
with its status and response addresses, asked about until it is done, and its result fetched. The models are the operator's
choice in nexora.toml (`fal_image_model`, `fal_video_model`); the key is FAL_KEY or `fal_api_key`. Pictures sent along (the
approved keyframe a clip starts from, a character's reference) go inside the request as data URIs, so nothing is uploaded
elsewhere; only generated pictures are ever sent, never footage. Each request is paid for: the price set per picture and per
second of clip is recorded with it, and the queue's own request id lets a lost connection be asked about rather than the job
submitted twice.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result, Usage

SIZES = {"16:9": "landscape_16_9", "9:16": "portrait_16_9", "1:1": "square_hd", "4:3": "landscape_4_3", "3:4": "portrait_4_3"}
DONE, WAITING = "COMPLETED", ("IN_QUEUE", "IN_PROGRESS")


def _data_uri(path: str | Path) -> str:
    path = Path(path)
    kind = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{kind};base64,{base64.b64encode(path.read_bytes()).decode()}"


class Fal(Adapter):
    KIND = "image_gen"

    def __init__(self, api_key: str, model: str, *, host: str = "https://queue.fal.run", price: float = 0.0, poll_seconds: float = 3.0, label: str = "fal"):
        self._key, self._model, self._host, self._price, self._every, self._label = api_key, model.strip("/"), host.rstrip("/"), price, poll_seconds, label

    def describe(self) -> Capability:
        return Capability(name=f"{self.KIND}.{self._label}", operations=("generate",), runs="cloud", supports_cancel=True)

    def available(self) -> bool:
        return bool(self._key and self._model)

    def environment(self) -> dict:
        # fal has no free health check: a key and a model are what can be told without paying for a request.
        return {"available": self.available(), "model": self._model, "key_present": bool(self._key)} if self._key else {"available": False, "fix": "FAL_KEY hoặc fal_api_key trong nexora.toml"}

    # ------------------------------------------------------------------------------------------------------------- HTTP
    def _call(self, method: str, url: str, body: dict | None = None, timeout: float = 60) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"authorization": f"Key {self._key}", "content-type": "application/json", "accept": "application/json", "user-agent": "NEXORA/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            code = {400: ErrorCode.INVALID_REQUEST, 401: ErrorCode.AUTH, 403: ErrorCode.AUTH, 404: ErrorCode.INVALID_REQUEST, 422: ErrorCode.INVALID_REQUEST,
                    402: ErrorCode.QUOTA_EXHAUSTED, 429: ErrorCode.RATE_LIMITED}.get(err.code, ErrorCode.UNAVAILABLE)
            raise AdapterError(code, f"fal answered {err.code}: {err.read().decode(errors='replace')[:200]}") from None
        except TimeoutError:
            raise AdapterError(ErrorCode.TIMEOUT, "fal did not answer in time") from None
        except (urllib.error.URLError, ConnectionError, ValueError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"fal is not reachable: {err}") from None

    def _fetch(self, url: str, out: Path) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost"):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "fal returned a file address that is not https")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "NEXORA/0.1"}), timeout=300) as r:
                out.write_bytes(r.read(2_000_000_000))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"the finished file could not be fetched from fal: {err}") from None

    def _run(self, payload: dict, deadline_seconds: float | None) -> tuple[dict, str]:
        """Post to the model's queue and wait for its result; a job that outlives the deadline is cancelled (it is paid for)."""
        job = self._call("POST", f"{self._host}/{self._model}", payload)
        rid = job.get("request_id")
        status_url = job.get("status_url") or f"{self._host}/{self._model}/requests/{rid}/status"
        response_url = job.get("response_url") or f"{self._host}/{self._model}/requests/{rid}"
        if not rid:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "fal accepted the request but gave no request id")
        deadline, lost = time.time() + (deadline_seconds or 1800), 0
        while True:
            try:
                st, lost = self._call("GET", status_url), 0
            except AdapterError as err:
                lost += 1
                if err.code in (ErrorCode.AUTH, ErrorCode.INVALID_REQUEST) or lost > 5:
                    raise
                st = {"status": "IN_QUEUE"}                       # a lost connection is not a lost job: ask again
            if st.get("status") == DONE:
                return self._call("GET", response_url), rid
            if st.get("status") not in WAITING:
                raise AdapterError(ErrorCode.INTERNAL, f"the fal request ended as {st.get('status')}: {str(st.get('error') or '')[:200]}", retryable=False)
            if time.time() >= deadline:
                try:
                    self._call("PUT", job.get("cancel_url") or f"{self._host}/{self._model}/requests/{rid}/cancel")
                except AdapterError:
                    pass
                raise AdapterError(ErrorCode.TIMEOUT, "the fal request did not finish in time and was cancelled", retryable=False)
            time.sleep(self._every)


class FalImage(Fal):
    """A still from a fal image model: `prompt`, `seed`, the size named from the aspect; a reference picture, when given, goes as
    `image_url` for the models that take one."""
    KIND = "image_gen"

    def submit(self, request: Request) -> Result:
        out = Path(request.params["out"])
        payload = {"prompt": request.inputs["prompt"], "seed": int(request.params.get("seed", 0)), "num_images": 1,
                   "image_size": SIZES.get(request.params.get("aspect", "16:9"), "landscape_16_9"), "enable_safety_checker": False}
        refs = [p for p in request.inputs.get("references") or [] if Path(p).is_file()]
        if refs:
            payload["image_url"] = _data_uri(refs[0])
        result, rid = self._run(payload, request.deadline_seconds)
        images = result.get("images") or ([result["image"]] if isinstance(result.get("image"), dict) else [])
        if not images or not images[0].get("url"):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "fal finished without a picture")
        self._fetch(images[0]["url"], out)
        from PIL import Image
        try:
            Image.open(out).convert("RGB").save(out)            # whatever format came back, the file is the picture the caller named
        except OSError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "fal returned something that is not a picture") from None
        return Result(outputs={"provider": self._label, "model": self._model, "job": rid}, files=(str(out),), external_ref=rid,
                      usage=Usage(units=1, cost=round(self._price, 4), measured=False))


class FalVideo(Fal):
    """A clip from a fal image-to-video model, starting from the approved keyframe: `prompt`, `image_url`, the length and aspect."""
    KIND = "video_gen"

    def submit(self, request: Request) -> Result:
        out = Path(request.params["out"])
        first = Path(request.inputs["first_frame"])
        if not first.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{first} does not exist")
        seconds = float(request.params.get("duration", 5))
        payload = {"prompt": request.inputs["prompt"], "image_url": _data_uri(first), "duration": "10" if seconds > 7.5 else "5",
                   "aspect_ratio": request.params.get("aspect", "16:9")}
        if request.params.get("seed") is not None:
            payload["seed"] = int(request.params["seed"])
        result, rid = self._run(payload, request.deadline_seconds)
        video = result.get("video") or {}
        url = video.get("url") if isinstance(video, dict) else video if isinstance(video, str) else None
        if not url:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "fal finished without a clip")
        self._fetch(url, out)
        if out.stat().st_size < 1000:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "fal returned a file too small to be a clip")
        length = 10.0 if payload["duration"] == "10" else 5.0
        return Result(outputs={"provider": self._label, "model": self._model, "job": rid}, files=(str(out),), external_ref=rid,
                      usage=Usage(units=length, cost=round(self._price * length, 4), measured=False))
