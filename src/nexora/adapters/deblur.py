"""Deblurring on this Mac, for Visual Quality (design 2026-10-16, wave 3): NAFNet (GoPro motion blur) in its MLX port on the
Apple GPU, run by `deblur_helper.py` in the environment `scripts/setup-deblur.sh` sets up.

On a still, or a video span frame by frame, always at the picture's own size (in tiles), written to ProRes 422 HQ, picture
only, like the other frame tools. Measured on an M4 (2026-10-17): about 6 s a 1080p frame, 25 s a 4K one. On motion blur of
11 pixels added to a frame of foliage: PSNR 21.4 → 23.7, SSIM 0.46 → 0.66.

The same port's denoiser (NAFNet SIDD width64, mlx-community, sha256 62c6825e…) was tried for stills and left out: on a frame
of foliage it lost to nlmeans at every level (Gaussian σ 4: 31.0 against 39.7, below the noisy 36.0; σ 8: 29.5 against 34.3;
correlated noise with chroma blotches: 29.0 against 31.1), shifting red and blue by about 3 and taking the leaves' texture for
noise; it learned the smooth pictures of phone sensors (2026-10-17).
"""
import json
import subprocess
import tempfile
from pathlib import Path

from nexora.adapters.pinned import offline_env, verify
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

HELPER = Path(__file__).with_name("deblur_helper.py")


class Deblur(Adapter):
    def __init__(self, env: str | Path, ffmpeg: str = "ffmpeg"):
        self._env, self._ffmpeg = Path(env).resolve(), ffmpeg
        self._python, self._model = self._env / "bin" / "python", self._env / "models" / "gopro_width64.safetensors"

    def describe(self) -> Capability:
        return Capability(name="deblur", operations=("deblur",), runs="local")

    def available(self) -> bool:
        return self._python.is_file() and self._model.is_file()

    def environment(self) -> dict:
        return {"available": True, "deblur": True} if self.available() else {"available": False, "fix": "sh scripts/setup-deblur.sh"}

    def _ff(self, args: list[str], what: str) -> None:
        done = subprocess.run([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"{what}: {done.stderr.strip()[-300:]}", retryable=False)

    def _helper(self, src: Path, dst: Path, frames: int) -> dict:
        verify(self._model, fix="sh scripts/setup-deblur.sh")
        try:
            done = subprocess.run([str(self._python), "-I", str(HELPER), str(src), str(dst), json.dumps({"model": str(self._model)})],
                                  capture_output=True, text=True, timeout=120 + 60 * frames, env=offline_env())
        except subprocess.TimeoutExpired:
            raise AdapterError(ErrorCode.TIMEOUT, "deblurring took too long", retryable=True) from None
        line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith("{")), None)
        answer = json.loads(line) if line else {}
        if done.returncode != 0 or "error" in answer:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"deblur: {answer.get('error') or done.stderr.strip()[-300:]}", retryable=False)
        return answer

    def submit(self, request: Request) -> Result:
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "deblurring is not set up (sh scripts/setup-deblur.sh)", retryable=False)
        if request.operation != "deblur":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        p = request.params
        src, out = Path(request.inputs["path"]), Path(p["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        if p.get("kind") == "still":
            with tempfile.TemporaryDirectory(prefix="vq_deblur_") as tmp:
                given = Path(tmp) / "in.png"                       # any still (a 16-bit TIFF, a JPEG) as 8-bit PNG for the helper
                self._ff(["-i", str(src), "-frames:v", "1", "-pix_fmt", "rgb24", str(given)], "a picture for deblurring")
                answer = self._helper(given, Path(tmp) / "out.png", 1)
                self._ff(["-i", str(Path(tmp) / "out.png"), "-frames:v", "1", "-update", "1", str(out)], "the deblurred picture")
        else:
            t_in, seconds = float(p.get("t_in", 0.0)), float(p.get("seconds") or 0.0)
            rate = self._rate(src)
            with tempfile.TemporaryDirectory(prefix="vq_deblur_") as tmp:
                frames_in, frames_out = Path(tmp) / "in", Path(tmp) / "out"
                frames_in.mkdir()
                span = ["-ss", f"{t_in:.3f}"] if t_in > 0 else []
                count = ["-frames:v", str(max(1, round(seconds * rate)))] if seconds else []
                self._ff([*span, "-i", str(src), *count, "-pix_fmt", "rgb24", str(frames_in / "%05d.png")], "frames for deblurring")
                n = len(list(frames_in.glob("*.png")))
                answer = self._helper(frames_in, frames_out, n)
                self._ff(["-framerate", f"{rate:.6f}", "-i", str(frames_out / "%05d.png"), "-an", "-c:v", "prores_ks", "-profile:v", "3",
                          "-pix_fmt", "yuv422p10le", str(out)], "the deblurred span")
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "deblurring wrote nothing", retryable=False)
        return Result(outputs={**answer, "generative": True}, files=(str(out),))

    @staticmethod
    def _rate(src: Path) -> float:
        rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0", str(src)],
                              capture_output=True, text=True).stdout.strip()
        try:
            num, _, den = rate.partition("/")
            return float(num) / float(den or 1)
        except ValueError:
            return 25.0
