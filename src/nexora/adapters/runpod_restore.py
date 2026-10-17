"""Visual Quality's models on the operator's RunPod endpoint: restoration that needs a rented GPU (design 2026-10-17).

One endpoint, built from `runpod/vq_worker` in this repository, does five tasks on a span of footage, each with a model that
looks at the frames around every frame (so nothing flickers from one frame to the next):

    deblur    VRT (GoPro)              blur a single frame cannot undo
    denoise   VRT (DAVIS), given σ      heavy noise, a dark shot lifted
    upscale   BasicVSR++ ×4, then to the height asked       clean footage made larger
    restore   RealBasicVSR ×4, then to the height asked     old footage: tape noise, blocks and softness at once
    faces     CodeFormer, weight given                       faces in a video

RunPod takes a job whose request is at most about 10 MB, and sends back what fits likewise, with files as base64 inside. A
span is therefore sent in chunks that each fit both ways (the input as it is, the output at the size the task makes it), each
chunk overlapping its neighbours by `OVERLAP` frames so a model that reads frames around each one has them at the joins; the
overlap is cut away from what comes back and the chunks are joined frame-exactly. Chunks run side by side, `concurrency` at a
time (a serverless endpoint starts more workers for them). Whether the endpoint is on is asked at its /health, which starts no
job and costs nothing; Visual Quality offers these tasks only while it answers, and only for a recording the operator has
allowed to leave this machine (privacy mode still stops it in the registry).
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nexora.adapters.runpod import MAX_PAYLOAD, RunPodVideo
from nexora.core.adapter import AdapterError, Capability, ErrorCode, Request, Result, Usage

TASKS = ("deblur", "denoise", "upscale", "restore", "faces")
SCALES = {"upscale": 4, "restore": 4}       # what the model makes before the worker brings it to the height asked
OVERLAP = 8                                  # frames shared with each neighbour: VRT reads 6–16 around a frame, BasicVSR++ propagates
IN_BUDGET = int(MAX_PAYLOAD * 0.72)          # bytes of media in a request (base64 adds a third)
OUT_BUDGET = 14_000_000                      # bytes the worker may send back for a chunk (it sets its bitrate for it)
BITS_PER_PIXEL = 0.12                        # what a good HEVC encode of restored footage costs, to size chunks by their output
MAX_CHUNK = 240


class RunPodRestore(RunPodVideo):
    KIND, OPERATION = "restore_remote", "restore"

    def __init__(self, api_key: str, endpoint_id: str, *, tasks: tuple[str, ...] | list[str] = TASKS, concurrency: int = 3, health_seconds: float = 60.0,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", **kw):
        super().__init__(api_key, endpoint_id, **kw)
        self._tasks = tuple(t for t in tasks if t in TASKS) or TASKS
        self._concurrency, self._health_every = max(1, int(concurrency)), health_seconds
        self._ffmpeg, self._ffprobe = ffmpeg, ffprobe
        self._health: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    def describe(self) -> Capability:
        return Capability(name=f"{self.KIND}.{self._label}", operations=self._tasks, runs="cloud", supports_cancel=True)

    # ----------------------------------------------------------------------------------------------------------- is it on
    def environment(self) -> dict:
        """Whether the endpoint answers, from its /health (no job, no charge), kept for `health_seconds`."""
        if not self._key:
            return {"available": False, "fix": "RUNPOD_API_KEY or runpod_api_key in nexora.toml"}
        with self._lock:
            if self._health and time.time() - self._health[0] < self._health_every:
                return self._health[1]
        try:
            health = self._call("GET", "/health", timeout=10)
            state = {"available": True, "tasks": list(self._tasks), "workers": health.get("workers", {}), "jobs": health.get("jobs", {})}
        except AdapterError as err:
            state = {"available": False, "tasks": list(self._tasks), "detail": str(err)[:200],
                     "fix": "bật endpoint VQ trên RunPod (runpod/vq_worker) và đặt runpod_restore_endpoint"}
        with self._lock:
            self._health = (time.time(), state)
        return state

    # ------------------------------------------------------------------------------------------------------------ media
    def _ff(self, args: list[str], what: str) -> None:
        done = subprocess.run([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"{what}: {done.stderr.strip()[-300:]}", retryable=False)

    def _probe(self, path: Path) -> dict:
        done = subprocess.run([self._ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                               "stream=width,height,avg_frame_rate,nb_read_packets", "-of", "json", str(path)], capture_output=True, text=True)
        try:
            s = json.loads(done.stdout)["streams"][0]
            num, _, den = str(s.get("avg_frame_rate") or "25/1").partition("/")
            return {"width": int(s["width"]), "height": int(s["height"]), "frames": int(s["nb_read_packets"]),
                    "fps": float(num) / float(den or 1), "bytes": path.stat().st_size}
        except (KeyError, IndexError, ValueError, ZeroDivisionError):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"{path.name} is not a video RunPod can be sent", retryable=False) from None

    def _cut(self, src: Path, a: int, b: int, out: Path) -> None:
        """Frames a..b-1 of `src`, exactly, as a compact H.264 file for the request."""
        self._ff(["-i", str(src), "-vf", f"select='between(n\\,{a}\\,{b - 1})',setpts=N/FRAME_RATE/TB", "-an", "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "14", "-pix_fmt", "yuv420p", str(out)], "a chunk for RunPod")

    def plan(self, info: dict, task: str, height: int | None) -> tuple[int, int]:
        """Frames a chunk carries of its own (`core`) and in all, sized so the request and the answer both fit."""
        scale = SCALES.get(task, 1)
        out_h = int(height or info["height"] * scale)
        out_w = info["width"] * out_h / max(1, info["height"])
        fit_in = IN_BUDGET / max(1.0, info["bytes"] / max(1, info["frames"]))
        fit_out = OUT_BUDGET * 8 / max(1.0, out_w * out_h * BITS_PER_PIXEL)
        whole = int(min(fit_in, fit_out, MAX_CHUNK))
        if whole < 2 * OVERLAP + 4:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"a frame of this footage is too large to send to RunPod inside a request ({task}, {out_w:.0f}×{out_h})", retryable=False)
        return whole - 2 * OVERLAP, whole

    # ----------------------------------------------------------------------------------------------------------- submit
    def submit(self, request: Request) -> Result:
        task = request.params.get("task") or request.operation
        if task not in self._tasks:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"the endpoint is not set up for {task} (it does {', '.join(self._tasks)})", retryable=False)
        src, out = Path(request.inputs["video"]), Path(request.params["out"])
        if not src.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{src} does not exist")
        options = {k: request.params[k] for k in ("height", "sigma", "lift", "weight") if request.params.get(k) is not None}
        info = self._probe(src)
        core, whole = self.plan(info, task, options.get("height"))
        deadline = request.deadline_seconds or 3600
        with tempfile.TemporaryDirectory(prefix="vq_runpod_") as tmp:
            work = Path(tmp)
            spans = [(max(0, s - OVERLAP), min(info["frames"], s + core + OVERLAP), s, min(info["frames"], s + core)) for s in range(0, info["frames"], core)]
            if len(spans) == 1 and info["bytes"] <= IN_BUDGET:
                spans = [(0, info["frames"], 0, info["frames"])]

            def one(k: int) -> tuple[Path, Result]:
                a, b, _, _ = spans[k]
                sent = src if (a, b) == (0, info["frames"]) and info["bytes"] <= IN_BUDGET else work / f"in_{k:03d}.mp4"
                if sent != src:
                    self._cut(src, a, b, sent)
                payload = {"input": {"task": task, "video": base64.b64encode(sent.read_bytes()).decode(), "max_bytes": OUT_BUDGET, **options}}
                back = work / f"out_{k:03d}.mp4"
                return back, self._start(payload, back, deadline)

            with ThreadPoolExecutor(max_workers=min(self._concurrency, len(spans))) as pool:
                done = list(pool.map(one, range(len(spans))))
            self._join(done, spans, out, fps=info["fps"])
        seconds = sum(r.usage.units for _, r in done if r.usage)
        return Result(outputs={"task": task, "chunks": len(spans), "frames": info["frames"], "provider": self._label}, files=(str(out),),
                      usage=Usage(units=seconds, cost=round(sum(r.usage.cost for _, r in done if r.usage), 4), measured=all(r.usage and r.usage.measured for _, r in done)))

    def _join(self, done: list[tuple[Path, Result]], spans: list[tuple[int, int, int, int]], out: Path, *, fps: float) -> None:
        """The chunks back, each cut to its own frames (the overlap with its neighbours dropped), one after another, frame-exact."""
        # ProRes where the container takes it (.mov), else a near-lossless H.264: the service renders it again either way.
        mov = out.suffix.lower() == ".mov"
        pix = "yuv422p10le" if mov else "yuv420p"
        codec = ["-c:v", "prores_ks", "-profile:v", "3"] if mov else ["-c:v", "libx264", "-preset", "fast", "-crf", "8"]
        args, parts = [], []
        for k, ((back, _), (a, _b, s, e)) in enumerate(zip(done, spans)):
            args += ["-i", str(back)]
            parts.append(f"[{k}:v]select='between(n\\,{s - a}\\,{e - a - 1})',setpts=N/({fps:.6f}*TB),format={pix}[c{k}]")
        graph = ";".join(parts) + ";" + "".join(f"[c{k}]" for k in range(len(done))) + f"concat=n={len(done)}:v=1:a=0[v]"
        out.parent.mkdir(parents=True, exist_ok=True)
        self._ff([*args, "-filter_complex", graph, "-map", "[v]", "-r", f"{fps:.6f}", *codec, str(out)], "the chunks back from RunPod")
        want = sum(e - s for _, _, s, e in spans)
        got = self._probe(out)["frames"]
        if got != want:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"RunPod sent back {got} frames for {want}", retryable=False)
