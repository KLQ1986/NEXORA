"""Gyroflow for Visual Quality (design 2026-10-16): stabilising from the camera's own gyroscope, with its lens profile and
rolling-shutter correction, instead of guessing motion from the picture as vidstab does.

It is only worth anything when the file carries gyro samples: DJI cameras record them only with their in-camera
stabilisation (RockSteady, HorizonSteady) off; GoPro, Insta360 and Sony record them too. `probe` says whether a file has
them, and the planner uses Gyroflow only then. Measured on an M4 (2026-10-17): a second of 4K written to ProRes 422 HQ in
about two seconds. Gyroflow reads the gyro by the source's own timeline, so it is always given the original file and the
span to render, never an intermediate.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

APP = Path("/Applications/Gyroflow.app/Contents/MacOS/gyroflow")


def find_binary() -> Path | None:
    found = shutil.which("gyroflow")
    return Path(found) if found else APP if APP.is_file() else None


class Gyroflow(Adapter):
    def __init__(self, binary: str | Path | None = None):
        self._binary = Path(binary) if binary else find_binary()

    def describe(self) -> Capability:
        return Capability(name="gyroflow", operations=("probe", "stabilise"), runs="local")

    def available(self) -> bool:
        return self._binary is not None and self._binary.is_file()

    def environment(self) -> dict:
        if not self.available():
            return {"available": False, "fix": "brew install --cask gyroflow"}
        return {"available": True, "binary": str(self._binary)}

    def _run(self, args: list[str], *, timeout: float) -> subprocess.CompletedProcess:
        try:
            done = subprocess.run([str(self._binary), *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdapterError(ErrorCode.TIMEOUT, "Gyroflow exceeded its time", retryable=True) from None
        except FileNotFoundError:
            raise AdapterError(ErrorCode.UNAVAILABLE, "Gyroflow is not installed (brew install --cask gyroflow)", retryable=False) from None
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"Gyroflow: {(done.stderr or done.stdout).strip()[-300:]}", retryable=False)
        return done

    def submit(self, request: Request) -> Result:
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "Gyroflow is not installed (brew install --cask gyroflow)", retryable=False)
        src = Path(request.inputs["path"])
        if request.operation == "probe":
            return Result(outputs=self._probe(src))
        if request.operation != "stabilise":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        p = request.params
        out = Path(p["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        t_in, seconds = float(p.get("t_in", 0.0)), float(p.get("seconds") or 0.0)
        smooth = max(0.05, min(1.0, float(p.get("smoothness", 0.5))))
        stab = {"smoothing_params": [{"name": "smoothness", "value": smooth}], "horizon_lock_amount": float(p.get("horizon_lock", 0.0))}
        preset = {"version": 2, "stabilization": stab}
        if t_in > 0 or seconds > 0:
            preset["trim_ranges_ms"] = [[t_in * 1000.0, (t_in + seconds) * 1000.0 if seconds else 1e12]]
        params = {"codec": "ProRes", "codec_options": "422 HQ", "output_folder": out.parent.resolve().as_uri() + "/",
                  "output_filename": out.name, "audio": False}
        self._run([str(src), "-f", "-p", json.dumps(params), "--preset", json.dumps(preset)], timeout=120 + (seconds or 600.0) * 10)
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "Gyroflow wrote nothing", retryable=False)
        if seconds:
            self._exact(out, seconds)
        return Result(outputs={"smoothness": smooth}, files=(str(out),))

    def _probe(self, src: Path) -> dict:
        """Whether the file carries gyro samples Gyroflow can use: its camera data, read and checked for motion."""
        with tempfile.TemporaryDirectory(prefix="vq_gyro_") as tmp:
            dump = Path(tmp) / "camera.json"
            self._run([str(src), "--export-metadata", f"3:{dump}"], timeout=180)
            try:
                rows = json.loads(dump.read_text())
            except (OSError, ValueError):
                return {"gyro": False, "frames": 0, "moving": 0}
        moving = sum(1 for r in rows if any(abs(v) > 1e-6 for v in r.get("org_gyro") or ()))
        # A file with a gyro track that is all zeros (DJI with RockSteady on) has nothing to stabilise from.
        return {"gyro": moving > max(3, len(rows) // 20), "frames": len(rows), "moving": moving}

    @staticmethod
    def _exact(out: Path, seconds: float) -> None:
        """Gyroflow renders a few frames past the end of a trim (measured: three at 25 fps); ProRes is all key frames, so the
        span is cut to its exact number of frames by copying, without encoding again."""
        rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0", str(out)],
                              capture_output=True, text=True).stdout.strip()
        try:
            num, _, den = rate.partition("/")
            frames = round(seconds * float(num) / float(den or 1))
        except ValueError:
            return
        cut = out.with_name(out.stem + ".exact" + out.suffix)
        done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out), "-map", "0:v:0", "-c", "copy", "-frames:v", str(frames), str(cut)],
                              capture_output=True, text=True)
        if done.returncode != 0 or not cut.is_file():
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"could not cut Gyroflow's span: {done.stderr.strip()[-200:]}", retryable=False)
        cut.replace(out)
