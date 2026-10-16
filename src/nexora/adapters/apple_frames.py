"""Apple's frame processors for Visual Quality (design 2026-10-16): temporal noise filtering, frame rate conversion and super
resolution, by VideoToolbox's VTFrameProcessor on this Mac's own hardware.

Measured on an M4 (2026-10-17): the temporal noise filter at 4K 10-bit runs at about 35 frames a second written to ProRes;
frame rate conversion makes 4K 60 from 30 at about 16 frames a second; super resolution makes 3840×2160 from 960×540 at
about 3 frames a second. The helper (`apple_frames.swift`) is built once by `scripts/setup-apple-frames.sh`; without it the
adapter says it is unavailable and Visual Quality uses FFmpeg's filters instead.
"""
import json
import subprocess
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

HELPER = Path(__file__).with_name("apple_frames.swift")


class AppleFrames(Adapter):
    def __init__(self, binary: str | Path):
        self._binary = Path(binary)
        self._probe: dict | None = None

    def describe(self) -> Capability:
        return Capability(name="apple_frames", operations=("denoise", "interpolate", "superres", "probe"), runs="local")

    def available(self) -> bool:
        return self._binary.is_file()

    def environment(self) -> dict:
        if not self.available():
            return {"available": False, "fix": "sh scripts/setup-apple-frames.sh"}
        if self._probe is None:
            try:
                self._probe = self._call(["probe"], timeout=60)
            except AdapterError:
                self._probe = {}
        return {"available": True, **self._probe}

    def _call(self, args: list[str], *, timeout: float) -> dict:
        try:
            done = subprocess.run([str(self._binary), *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdapterError(ErrorCode.TIMEOUT, "Apple frame processor exceeded its time", retryable=True) from None
        except FileNotFoundError:
            raise AdapterError(ErrorCode.UNAVAILABLE, "the Apple frame processor is not built (sh scripts/setup-apple-frames.sh)", retryable=False) from None
        line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith("{")), None)
        answer = json.loads(line) if line else {}
        if done.returncode != 0 or "error" in answer:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"Apple frame processor: {answer.get('error') or done.stderr.strip()[-300:]}", retryable=False)
        return answer

    def submit(self, request: Request) -> Result:
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "the Apple frame processor is not built (sh scripts/setup-apple-frames.sh)", retryable=False)
        if request.operation == "probe":
            return Result(outputs=self._call(["probe"], timeout=60))
        p = request.params
        src, out = str(request.inputs["path"]), Path(p["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        span = [src, str(out), f"{float(p.get('t_in', 0.0)):.3f}", f"{float(p.get('seconds') or 0.0):.3f}"]
        seconds = float(p.get("seconds") or 600.0)
        if request.operation == "denoise":
            answer = self._call(["denoise", *span, f"{max(0.0, min(1.0, float(p.get('strength', 0.5)))):.3f}"], timeout=60 + seconds * 4)
        elif request.operation == "interpolate":
            answer = self._call(["interpolate", *span, f"{float(p['fps']):.3f}"], timeout=60 + seconds * 10)
        elif request.operation == "superres":
            answer = self._call(["superres", *span], timeout=600 + seconds * 30)
        else:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the Apple frame processor wrote nothing", retryable=False)
        return Result(outputs=answer, files=(str(out),))
