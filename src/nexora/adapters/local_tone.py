"""Local tone (relight) for Visual Quality (design 2026-10-16, wave 3): shadows lifted and highlights held back where they are,
not by one curve for the whole picture, for a backlit or high-contrast scene a global grade cannot fix without clipping.

A gain map: the brightness of the picture, much smoothed and at a sixteenth of its size (its "base"), sets how much each
place is lifted or held; the gain is brought back to full size smoothly and multiplies the picture, so fine detail and edges
keep their own contrast (the base/detail split of local tone mapping, as in Durand & Dorsey 2002, with the fast guided
filter in place of their bilateral one, so the base keeps hard edges and no halo forms along them). The same picture always gives the
same gain, so a still scene does not flicker; Visual Quality's temporal checks see to a moving one.

Works on a still or a video span (read and written through FFmpeg at 16 bits a channel, picture only, ProRes 422 HQ).
"""
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter, zoom

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
SMALL = 16                  # the base is worked at 1/16 of the size
SPREAD = 0.06               # of the picture's width: how far the base looks around each place
GAIN = (0.6, 3.0)           # the most a place is held back or lifted
EDGE = 0.1                  # guided filter: a change of log brightness bigger than about √0.1 is an edge the base keeps


def _up(x: np.ndarray, h: int, w: int) -> np.ndarray:
    full = zoom(x, (h / x.shape[0], w / x.shape[1]), order=1, mode="nearest")[:h, :w]
    if full.shape != (h, w):
        full = np.pad(full, ((0, h - full.shape[0]), (0, w - full.shape[1])), mode="edge")
    return full


def base_of(rgb: np.ndarray) -> np.ndarray:
    """The picture's brightness without its detail, following its hard edges: the fast guided filter (He & Sun 2015) on log
    luma, its coefficients found at a sixteenth of the size and applied at full size. A box-smoothed base spread a bright sky
    into the shade under it and drew a halo along the edge (measured on a backlit frame, 2026-10-17: NIQE 4.5 → 5.1)."""
    h, w = rgb.shape[:2]
    hs, ws = max(2, h // SMALL), max(2, w // SMALL)
    log_full = np.log(rgb @ LUMA + 1e-3)
    small = np.log(rgb[: hs * SMALL, : ws * SMALL] @ LUMA + 1e-3).reshape(hs, SMALL, ws, SMALL).mean((1, 3))
    size = max(3, int(ws * SPREAD) | 1)
    mean = uniform_filter(small, size, mode="nearest")
    var = uniform_filter(small * small, size, mode="nearest") - mean * mean
    a = var / (var + EDGE)
    b = mean - a * mean
    a, b = uniform_filter(a, size, mode="nearest"), uniform_filter(b, size, mode="nearest")
    return np.clip(np.exp(_up(a, h, w) * log_full + _up(b, h, w)), 1e-3, 1.0)


def gain_map(rgb: np.ndarray, *, shadows: float, highlights: float) -> np.ndarray:
    """The gain for each pixel of an RGB picture (0..1), from its edge-aware base."""
    base = base_of(rgb)
    # Below a middle grey the base is lifted towards it, above it brought down, each by its own amount, smoothly at 0.5.
    lift = 1.0 + shadows * np.clip((0.5 - base) / 0.5, 0.0, 1.0) ** 2 * (0.5 / np.maximum(base, 0.05) - 1.0)
    hold = 1.0 - highlights * np.clip((base - 0.5) / 0.5, 0.0, 1.0) ** 2 * 0.5
    return np.clip(lift * hold, *GAIN)[..., None].astype(np.float32)


def relight(rgb: np.ndarray, *, shadows: float, highlights: float) -> np.ndarray:
    out = rgb * gain_map(rgb, shadows=shadows, highlights=highlights)
    # Highlights that a lift pushes past white are rolled off rather than clipped.
    over = out > 0.9
    out[over] = 0.9 + 0.1 * np.tanh((out[over] - 0.9) / 0.1)
    return np.clip(out, 0.0, 1.0)


class LocalTone(Adapter):
    def __init__(self, ffmpeg: str = "ffmpeg"):
        self._ffmpeg = ffmpeg

    def describe(self) -> Capability:
        return Capability(name="local_tone", operations=("relight",), runs="local")

    def available(self) -> bool:
        return True

    def environment(self) -> dict:
        return {"available": True, "relight": True}

    def _probe(self, src: Path) -> tuple[int, int, float]:
        done = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate", "-of", "csv=p=0", str(src)],
                              capture_output=True, text=True)
        try:
            w, h, rate = done.stdout.strip().split("\n")[0].split(",")[:3]
            num, _, den = rate.partition("/")
            return int(w), int(h), (float(num) / float(den or 1)) if float(den or 1) else 25.0
        except (ValueError, ZeroDivisionError):
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"cannot read {src.name}", retryable=False) from None

    def submit(self, request: Request) -> Result:
        if request.operation != "relight":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        p = request.params
        src, out = Path(request.inputs["path"]), Path(p["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        shadows, highlights = float(np.clip(p.get("shadows", 0.5), 0, 1)), float(np.clip(p.get("highlights", 0.3), 0, 1))
        w, h, rate = self._probe(src)
        still = p.get("kind") == "still"
        t_in, seconds = float(p.get("t_in", 0.0)), float(p.get("seconds") or 0.0)
        read = [self._ffmpeg, "-hide_banner", "-loglevel", "error", *(["-ss", f"{t_in:.3f}"] if t_in > 0 and not still else []), "-i", str(src),
                *(["-frames:v", "1"] if still else ["-frames:v", str(max(1, round(seconds * rate)))] if seconds else []),
                "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"]
        write = [self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{w}x{h}",
                 *([] if still else ["-r", f"{rate:.6f}"]), "-i", "-",
                 *(["-frames:v", "1", "-update", "1"] if still else ["-an", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]), str(out)]
        size = w * h * 6
        frames = 0
        reader = subprocess.Popen(read, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        writer = subprocess.Popen(write, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while True:
                raw = reader.stdout.read(size)
                if len(raw) < size:
                    break
                rgb = np.frombuffer(raw, "<u2").reshape(h, w, 3).astype(np.float32) / 65535.0
                done = relight(rgb, shadows=shadows, highlights=highlights)
                writer.stdin.write((done * 65535.0 + 0.5).astype("<u2").tobytes())
                frames += 1
        finally:
            writer.stdin.close()
            writer.wait()
            reader.stdout.close()
            reader.wait()
        if frames == 0 or writer.returncode != 0 or not out.is_file():
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"relight wrote nothing: {writer.stderr.read().decode(errors='replace')[-200:]}", retryable=False)
        return Result(outputs={"frames": frames, "shadows": shadows, "highlights": highlights}, files=(str(out),))
