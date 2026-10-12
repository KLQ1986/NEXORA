"""Reference workers for the five RunPod serverless endpoints NEXORA can call.

Each handler takes a RunPod job (`{"id": ..., "input": {...}}`) and returns the output NEXORA's adapters read. The
input and output of every handler is the contract; what happens in between is yours to replace.

As shipped, the part in between is a stand-in made with FFmpeg and Pillow, so that the whole path can be run and
checked without a GPU: the "video model" pushes in on the still, the "upscaler" resamples, the "lip-sync" only lays the
sound under the picture, the "image model" draws a flat picture, and the "trainer" returns a file that is not a model.
None of them is the real thing. Replace the function named `run_*` in the task you deploy with a call to your model
and keep the handler around it.

Deploy one endpoint per task with the environment variable NEXORA_TASK set to video, image, lipsync, upscale or train.
"""
import base64
import os
import subprocess
import tempfile
from pathlib import Path

SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}


def _write(folder: Path, name: str, data: str) -> Path:
    path = folder / name
    path.write_bytes(base64.b64decode(data.split(",", 1)[-1]))
    return path


def _read(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def _ffmpeg(*args: str) -> None:
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:])


# ------------------------------------------------------------------ the parts to replace with real models
def run_video(still: Path, prompt: str, seconds: float, seed: int, aspect: str, camera: str | None, out: Path) -> str:
    """STAND-IN. Replace with an image-to-video model. Must write an MP4 of about `seconds` to `out`; returns the model's name."""
    w, h = SIZES.get(aspect, SIZES["16:9"])
    frames = max(1, round(seconds * 25))
    _ffmpeg("-i", str(still), "-vf", f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
            f"zoompan=z='1+0.1*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=25", "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(out))
    return "stand-in-zoom"


def run_image(prompt: str, seed: int, aspect: str, references: list[Path], loras: list[str], out: Path) -> str:
    """STAND-IN. Replace with a text-to-image model that loads `loras` (addresses of trained character models). Writes a PNG to `out`."""
    from PIL import Image
    Image.new("RGB", SIZES.get(aspect, SIZES["16:9"]), (60 + seed % 180, 60 + seed // 7 % 180, 60 + seed // 13 % 180)).save(out)
    return "stand-in-flat"


def run_lipsync(video: Path, audio: Path, out: Path) -> str:
    """STAND-IN. Replace with a lip-sync model. This only lays the sound under the picture; no mouth is moved."""
    _ffmpeg("-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out))
    return "stand-in-mux"


def run_upscale(video: Path, scale: int, out: Path) -> str:
    """STAND-IN. Replace with a learned upscaler. This resamples; it adds no detail."""
    _ffmpeg("-i", str(video), "-vf", f"scale=iw*{scale}:ih*{scale}:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out))
    return "stand-in-lanczos"


def run_train(images: list[Path], name: str, trigger: str, steps: int, out: Path) -> str:
    """STAND-IN. Replace with a LoRA trainer; upload the result and return its address as `model_url`. This writes a file that is not a model."""
    out.write_bytes(b"NOT-A-MODEL " + f"{name} {trigger} {len(images)} pictures {steps} steps".encode() + b"\0" * 2000)
    return "stand-in-no-training"


# ------------------------------------------------------------------ the contract: keep these as they are
def video(job: dict) -> dict:
    """In: prompt, image (base64), seconds, seed, aspect, camera. Out: video (base64) or video_url (https), model."""
    i = job["input"]
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        model = run_video(_write(folder, "still.png", i["image"]), i["prompt"], float(i["seconds"]), int(i.get("seed", 0)), i.get("aspect", "16:9"), i.get("camera"), folder / "out.mp4")
        return {"video": _read(folder / "out.mp4"), "model": model}


def image(job: dict) -> dict:
    """In: prompt, seed, aspect, references (base64 list), loras (addresses). Out: image (base64) or image_url (https), model."""
    i = job["input"]
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        refs = [_write(folder, f"ref{n}.png", data) for n, data in enumerate(i.get("references") or [])]
        model = run_image(i["prompt"], int(i.get("seed", 0)), i.get("aspect", "16:9"), refs, list(i.get("loras") or []), folder / "out.png")
        return {"image": _read(folder / "out.png"), "model": model}


def lipsync(job: dict) -> dict:
    """In: video, audio (both base64). Out: video (base64) or video_url (https), model."""
    i = job["input"]
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        model = run_lipsync(_write(folder, "in.mp4", i["video"]), _write(folder, "in.wav", i["audio"]), folder / "out.mp4")
        return {"video": _read(folder / "out.mp4"), "model": model}


def upscale(job: dict) -> dict:
    """In: video (base64), scale. Out: video (base64) or video_url (https), model."""
    i = job["input"]
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        model = run_upscale(_write(folder, "in.mp4", i["video"]), int(i.get("scale", 2)), folder / "out.mp4")
        return {"video": _read(folder / "out.mp4"), "model": model}


def train(job: dict) -> dict:
    """In: images (base64 list), name, trigger, steps. Out: model_url (https, preferred: an image endpoint loads it from there) or model (base64), base_model."""
    i = job["input"]
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        pictures = [_write(folder, f"p{n}.png", data) for n, data in enumerate(i["images"])]
        base = run_train(pictures, i["name"], i["trigger"], int(i.get("steps", 1000)), folder / "model.safetensors")
        return {"model": _read(folder / "model.safetensors"), "base_model": base}


HANDLERS = {"video": video, "image": image, "lipsync": lipsync, "upscale": upscale, "train": train}

if __name__ == "__main__":
    import runpod                                            # the RunPod worker SDK, present in the container
    runpod.serverless.start({"handler": HANDLERS[os.environ["NEXORA_TASK"]]})
