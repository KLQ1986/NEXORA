"""NEXORA Visual Quality worker for a RunPod serverless endpoint (adapters/runpod_restore.py is its client).

A job's input:
    task        deblur | denoise | upscale | restore | faces | capabilities
    video       the span, base64 (or video_url, https)
    max_bytes   what the answer may weigh (RunPod's response limit); the encode is sized for it
    height      upscale, restore: the height to bring the result to (the models work ×4)
    sigma       denoise: the noise measured (0..255); lift: how much the picture will be raised after
    weight      faces: CodeFormer's fidelity (0 = most restored, 1 = most faithful)
Its output: {"video": base64 (HEVC), "model": ..., "frames": n} or, with a bucket set (BUCKET_ENDPOINT_URL and keys, RunPod's
own upload), {"video_url": ...}. The number of frames out is the number in, always: the client cuts and joins by frame.

    VQ_WORKER_FAKE=1   stand-in models (resampling, a copy) so the protocol can be run without a GPU (tests/runpod).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import models

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")


def _ff(args: list[str]) -> None:
    done = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-400:])


def _probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=width,height,avg_frame_rate,nb_read_packets", "-of", "json", str(path)], capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    num, _, den = str(s.get("avg_frame_rate") or "25/1").partition("/")
    return {"width": int(s["width"]), "height": int(s["height"]), "frames": int(s["nb_read_packets"]), "fps": float(num) / float(den or 1)}


def _fetch(job: dict, dst: Path) -> None:
    if job.get("video"):
        dst.write_bytes(base64.b64decode(str(job["video"]).split(",", 1)[-1]))
    elif str(job.get("video_url", "")).startswith("https://"):
        with urllib.request.urlopen(job["video_url"], timeout=300) as r:
            dst.write_bytes(r.read())
    else:
        raise ValueError("the job carries no video (video as base64, or video_url)")


def _encode(frames: Path, info: dict, out: Path, *, height: int | None, max_bytes: int) -> None:
    """The frames as HEVC, at the height asked, sized to `max_bytes` (once more at 70% when the first pass is over)."""
    seconds = max(info["frames"] / info["fps"], 0.04)
    scale = [f"scale=-2:{int(height)}:flags=lanczos"] if height else []
    encoder = ["-c:v", "hevc_nvenc", "-preset", "p6"] if models.HAS_NVENC else ["-c:v", "libx265", "-preset", "medium", "-x265-params", "log-level=error"]
    for share in (0.85, 0.6):
        rate = int(max_bytes * 8 * share / seconds)
        _ff(["-framerate", f"{info['fps']:.6f}", "-i", str(frames / "%06d.png"), *(["-vf", ",".join(scale)] if scale else []), *encoder,
             "-b:v", str(rate), "-maxrate", str(int(rate * 1.2)), "-bufsize", str(rate), "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1", str(out)])
        if out.stat().st_size <= max_bytes:
            return
    raise RuntimeError(f"the result does not fit in {max_bytes} bytes; send shorter chunks")


def _answer(out: Path, model: str, frames: int) -> dict:
    if os.environ.get("BUCKET_ENDPOINT_URL"):
        from runpod.serverless.utils import rp_upload
        return {"video_url": rp_upload.upload_file_to_bucket(out.name, str(out)), "model": model, "frames": frames}
    return {"video": base64.b64encode(out.read_bytes()).decode(), "model": model, "frames": frames}


def handler(job: dict) -> dict:
    given = job.get("input") or {}
    task = given.get("task")
    if task == "capabilities":
        return {"tasks": models.available(), "fake": models.FAKE}
    if task not in models.TASKS:
        return {"error": f"unknown task {task!r}; this worker does {', '.join(models.TASKS)}"}
    work = Path(tempfile.mkdtemp(prefix="vq_"))
    try:
        src = work / "in.mp4"
        _fetch(given, src)
        info = _probe(src)
        frames_in, frames_out = work / "in", work / "out"
        frames_in.mkdir()
        _ff(["-i", str(src), "-pix_fmt", "rgb24", "-start_number", "0", str(frames_in / "%06d.png")])
        model = models.run(task, frames_in, frames_out, given)
        made = sorted(frames_out.glob("*.png"))
        if len(made) != info["frames"] or len(list(frames_in.glob("*.png"))) != info["frames"]:
            return {"error": f"{task} gave {len(made)} frames for {info['frames']}"}
        out = work / "out.mp4"
        _encode(frames_out, info, out, height=given.get("height") if task in ("upscale", "restore") else None,
                max_bytes=int(given.get("max_bytes") or 14_000_000))
        return _answer(out, model, info["frames"])
    except Exception as err:                                  # the job fails with what went wrong, for the client to show
        return {"error": f"{type(err).__name__}: {str(err)[:400]}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    import runpod
    runpod.serverless.start({"handler": handler})
