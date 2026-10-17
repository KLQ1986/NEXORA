"""Pictures and clips from ComfyUI on a RunPod serverless endpoint (the runpod-workers/worker-comfyui image), driven by workflow
templates kept in this repository and pinned by their SHA-256 (design 2026-10-17, phase 5).

A template is a ComfyUI graph in its API form with places to fill (`{{prompt}}`, `{{seed}}`, `{{width}}`, `{{image}}`…); the
Shot Spec fills them, so the storyboard stays the source of truth and the graph is only how a picture is made. A template is
read only when its bytes are the ones in `comfy_workflows/manifest.json`; the filled graph and the seed are what the job
carries, so the picture can be made again. The two templates use ComfyUI's core nodes only (text to image; image to video by
Stable Video Diffusion); the models they name (`comfy_checkpoint`, `comfy_video_checkpoint`) must be on the endpoint's image.
The approved keyframe a clip starts from goes inside the request; only generated pictures are sent, never footage.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from nexora.adapters.runpod import RunPodVideo
from nexora.core.adapter import AdapterError, ErrorCode, Request, Result, Usage

TEMPLATES = Path(__file__).with_name("comfy_workflows")
SIZES = {"16:9": (1024, 576), "9:16": (576, 1024), "1:1": (768, 768), "4:3": (896, 672), "3:4": (672, 896)}
NEGATIVE = "text, watermark, logo, distorted hands, blurry"


def template(name: str) -> dict:
    """A workflow template, refused unless its bytes are the pinned ones."""
    manifest = json.loads((TEMPLATES / "manifest.json").read_text())
    path = TEMPLATES / name
    if name not in manifest or not path.is_file():
        raise AdapterError(ErrorCode.INVALID_REQUEST, f"no workflow template {name} (have: {', '.join(k for k in manifest if k != '_')})", retryable=False)
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[name]:
        raise AdapterError(ErrorCode.INVALID_REQUEST, f"workflow template {name} is not the one that was pinned", retryable=False)
    return json.loads(path.read_text())


def fill(graph: dict, values: dict) -> dict:
    """Every `{{key}}` of the graph replaced: a value standing alone keeps its type (a seed stays a number)."""
    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str) and x.startswith("{{") and x.endswith("}}") and x[2:-2] in values:
            return values[x[2:-2]]
        if isinstance(x, str):
            for k, v in values.items():
                x = x.replace("{{" + k + "}}", str(v))
        return x
    out = walk(copy.deepcopy(graph))
    left = [s for s in json.dumps(out).split('"') if s.startswith("{{") and s.endswith("}}")]
    if left:
        raise AdapterError(ErrorCode.INVALID_REQUEST, f"the workflow still asks for {', '.join(sorted(set(left)))}", retryable=False)
    return out


class Comfy(RunPodVideo):
    """The job protocol of RunPod with worker-comfyui's input (`workflow`, `images` as base64) and output (`images`: files as
    base64 or addresses)."""
    KIND = "image_gen"
    WORKFLOW = "txt2img.json"

    def __init__(self, api_key: str, endpoint_id: str, *, checkpoint: str, steps: int = 28, **kw):
        super().__init__(api_key, endpoint_id, label=kw.pop("label", "comfy"), **kw)
        self._checkpoint, self._steps = checkpoint, steps

    def available(self) -> bool:
        return bool(self._key and self._checkpoint)

    def environment(self) -> dict:
        return {"available": self.available(), "checkpoint": self._checkpoint, "templates": [k for k in json.loads((TEMPLATES / "manifest.json").read_text()) if k != "_"]}

    def _collect(self, job: dict, out: Path) -> Result:
        output = job.get("output") if isinstance(job.get("output"), dict) else {}
        files = output.get("images") or output.get("videos") or []
        if isinstance(output.get("message"), str):                     # the worker's older answer: one file, base64 or an address
            files = [{"data": output["message"], "filename": "out.png"}]
        if not files:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"ComfyUI finished without an output file (the workflow needs a Save node): {str(output.get('errors') or '')[:160]}")
        f = files[-1]                                                   # the last Save node's file is the graph's result
        data = str(f.get("data") or f.get("image") or "")
        got = out.with_name(out.stem + "_comfy" + (Path(str(f.get("filename") or "")).suffix or ".png"))
        if f.get("type") == "s3_url" or data.startswith("http"):
            super()._collect({**job, "output": {"video_url": f.get("url") or data}}, got)   # https only, as for every RunPod file
        else:
            got.parent.mkdir(parents=True, exist_ok=True)
            got.write_bytes(base64.b64decode(data.split(",", 1)[-1]))
        self._finish(got, out)
        seconds = float(job.get("executionTime") or 0) / 1000
        return Result(outputs={"provider": self._label, "model": self._model, "job": job.get("id")}, files=(str(out),), external_ref=job.get("id"),
                      usage=Usage(units=seconds, cost=round(seconds * self._price, 4), measured=bool(job.get("executionTime"))))

    @property
    def _model(self) -> str:
        """What made the picture, kept with the generation: the checkpoint and the template with the start of its hash."""
        pinned = json.loads((TEMPLATES / "manifest.json").read_text()).get(self.WORKFLOW, "")
        return f"{self._checkpoint} · {self.WORKFLOW.removesuffix('.json')}@{pinned[:12]}"

    def _finish(self, got: Path, out: Path) -> None:
        from PIL import Image
        try:
            Image.open(got).convert("RGB").save(out)
        except OSError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "ComfyUI returned something that is not a picture") from None
        got.unlink(missing_ok=True)

    def submit(self, request: Request) -> Result:
        w, h = SIZES.get(request.params.get("aspect", "16:9"), SIZES["16:9"])
        graph = fill(template(self.WORKFLOW), {"prompt": request.inputs["prompt"], "negative": NEGATIVE, "seed": int(request.params.get("seed", 0)),
                                      "width": w, "height": h, "steps": self._steps, "cfg": 4.5, "checkpoint": self._checkpoint})
        return self._start({"input": {"workflow": graph}}, Path(request.params["out"]), request.deadline_seconds)


class ComfyVideo(Comfy):
    """A clip from the approved keyframe: Stable Video Diffusion in ComfyUI, its animated output made an MP4 here."""
    KIND = "video_gen"
    WORKFLOW = "img2vid_svd.json"

    def _finish(self, got: Path, out: Path) -> None:
        if got.suffix.lower() == ".mp4":
            got.replace(out)
            return
        # An animated WEBP or GIF, as ComfyUI's core saves it: decoded frame by frame and written as H.264.
        from PIL import Image, ImageSequence
        with tempfile.TemporaryDirectory(prefix="comfy_") as tmp, Image.open(got) as im:
            n = 0
            for n, frame in enumerate(ImageSequence.Iterator(im), 1):
                frame.convert("RGB").save(Path(tmp) / f"{n:05d}.png")
            fps = max(1, round(1000 / (im.info.get("duration") or 166)))
            done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", str(Path(tmp) / "%05d.png"),
                                   "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out)], capture_output=True, text=True)
        got.unlink(missing_ok=True)
        if done.returncode != 0 or not out.is_file() or n < 2:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"ComfyUI's clip could not be read ({n} frames)")

    def submit(self, request: Request) -> Result:
        first = Path(request.inputs["first_frame"])
        if not first.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{first} does not exist")
        w, h = SIZES.get(request.params.get("aspect", "16:9"), SIZES["16:9"])
        fps = 6
        frames = max(14, min(25, round(float(request.params.get("duration", 4)) * fps)))
        graph = fill(template(self.WORKFLOW), {"image": "keyframe.png", "seed": int(request.params.get("seed", 0)), "width": w, "height": h,
                                                                                  "frames": frames, "fps": fps, "motion": 127, "steps": 20, "checkpoint": self._checkpoint, "prompt": request.inputs.get("prompt", "")})
        payload = {"input": {"workflow": graph, "images": [{"name": "keyframe.png", "image": base64.b64encode(first.read_bytes()).decode()}]}}
        return self._start(payload, Path(request.params["out"]), request.deadline_seconds)
