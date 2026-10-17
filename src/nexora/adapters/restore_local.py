"""Restoration by AI on this Mac, for Visual Quality (design 2026-10-16, wave 3): Real-ESRGAN, its ncnn build (Vulkan through
MoltenVK on the Apple GPU), called as a program, as the design's §9.3 says.

It makes detail up: Visual Quality uses it only where its measures show it beats the classic step, and marks it as
generative. Two uses on stills: a picture made larger (×4, then brought to the size asked) and a heavily compressed
picture restored (×4, then back to its own size, which takes JPEG blocks and ringing away). Measured on an M4 (2026-10-17):
220×220 to 880×880 in about 2.5 s with `realesrgan-x4plus`.

Set up by `scripts/setup-realesrgan.sh`, into `data/tools/realesrgan/`.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from nexora.adapters.pinned import verify
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

MODELS = ("realesrgan-x4plus", "realesrgan-x4plus-anime", "realesr-animevideov3-x4")


class RestoreLocal(Adapter):
    def __init__(self, folder: str | Path, ffmpeg: str = "ffmpeg"):
        self._folder, self._ffmpeg = Path(folder), ffmpeg
        self._binary = self._folder / "realesrgan-ncnn-vulkan"

    def describe(self) -> Capability:
        return Capability(name="restore_local", operations=("esrgan",), runs="local")

    def available(self) -> bool:
        return self._binary.is_file() and (self._folder / "models" / "realesrgan-x4plus.bin").is_file()

    def environment(self) -> dict:
        if not self.available():
            return {"available": False, "fix": "sh scripts/setup-realesrgan.sh"}
        return {"available": True, "esrgan": [m for m in MODELS if (self._folder / "models" / f"{m}.bin").is_file()]}

    def submit(self, request: Request) -> Result:
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "Real-ESRGAN is not set up (sh scripts/setup-realesrgan.sh)", retryable=False)
        if request.operation != "esrgan":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        p = request.params
        src, out = Path(request.inputs["path"]), Path(p["out"])
        model = p.get("model", "realesrgan-x4plus")
        if model not in MODELS:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown model {model}", retryable=False)
        for f in (self._binary, self._folder / "models" / f"{model}.bin", self._folder / "models" / f"{model}.param"):
            verify(f, fix="sh scripts/setup-realesrgan.sh")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="vq_esrgan_") as tmp:
            # The ncnn build reads 8-bit PNG, JPEG and WebP only: anything else (a 16-bit TIFF, a frame) goes through FFmpeg first.
            given = Path(tmp) / "in.png"
            self._ffmpeg_run(["-i", str(src), "-frames:v", "1", "-pix_fmt", "rgb24", str(given)])
            big = Path(tmp) / "x4.png"
            try:
                done = subprocess.run([str(self._binary), "-i", str(given), "-o", str(big), "-n", model, "-s", "4", "-m", str(self._folder / "models"), "-f", "png"],
                                      capture_output=True, text=True, timeout=float(p.get("timeout", 900)))
            except subprocess.TimeoutExpired:
                raise AdapterError(ErrorCode.TIMEOUT, "Real-ESRGAN exceeded its time", retryable=True) from None
            if done.returncode != 0 or not big.is_file():
                raise AdapterError(ErrorCode.OUTPUT_INVALID, f"Real-ESRGAN: {(done.stderr or done.stdout).strip()[-300:]}", retryable=False)
            size = p.get("size")
            if size:
                self._ffmpeg_run(["-i", str(big), "-vf", f"scale={int(size[0])}:{int(size[1])}:flags=lanczos", "-frames:v", "1", "-update", "1", str(out)])
            else:
                shutil.move(str(big), out)
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "Real-ESRGAN wrote nothing", retryable=False)
        return Result(outputs={"model": model, "generative": True}, files=(str(out),))

    def _ffmpeg_run(self, args: list[str]) -> None:
        done = subprocess.run([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"FFmpeg around Real-ESRGAN: {done.stderr.strip()[-200:]}", retryable=False)
