"""A moving clip from one still, made on this machine with FFmpeg: a slow push, pull or pan across the picture.

It is not a video model: nothing in the picture moves, only the frame. It gives generated stories a cut that can be
watched, timed and approved without paying for video generation, and it is what a shot falls back to when no video
provider is reachable.
"""
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process

SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}
FPS = 25


def camera_filter(camera: str, frames: int, width: int, height: int) -> str:
    """zoompan expressions for one camera move over `frames` frames."""
    step = 0.12 / max(frames, 1)
    centre = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    moves = {
        "slow push in": f"z='1+{step:.6f}*on':{centre}",
        "slow pull out": f"z='1.12-{step:.6f}*on':{centre}",
        "pan left": f"z='1.12':x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'",
        "pan right": f"z='1.12':x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'",
        "static": f"z='1':{centre}",
    }
    # Scaled up first: zoompan moves by whole pixels, and on a small picture that shows as a tremble.
    return (f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2},"
            f"zoompan={moves.get(camera, moves['slow push in'])}:d={frames}:s={width}x{height}:fps={FPS}")


class StillMotion(Adapter):
    def describe(self) -> Capability:
        return Capability(name="video_gen.motion", operations=("generate",), runs="local")

    def submit(self, request: Request) -> Result:
        still = Path(request.inputs["first_frame"])
        if not still.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{still} does not exist")
        seconds = float(request.params["duration"])
        width, height = SIZES.get(request.params.get("aspect", "16:9"), SIZES["16:9"])
        frames = max(1, round(seconds * FPS))
        out = Path(request.params["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        done = run_process(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(still), "-vf", camera_filter(request.params.get("camera", ""), frames, width, height),
                            "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(out)], timeout=request.deadline_seconds or 300)
        if done.returncode != 0 or not out.is_file():
            raise AdapterError(ErrorCode.INTERNAL, f"ffmpeg could not make the clip: {done.stderr.strip()[-200:]}")
        return Result(outputs={"provider": "motion", "model": "ffmpeg-zoompan"}, files=(str(out),))
