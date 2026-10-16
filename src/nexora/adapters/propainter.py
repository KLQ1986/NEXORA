"""Object removal in video by ProPainter (ICCV 2023), for Visual Quality (design 2026-10-16, wave 3).

ProPainter fills a masked region from what the neighbouring frames show of it (flow completion and propagation of real
pixels first, a transformer only for what no frame shows), which is why the design chose it over generating the region.
It runs in its own environment on the Apple GPU (MPS), set up by `scripts/setup-propainter.sh` into `data/tools/propainter/`.

ProPainter needs a lot of memory per pixel, so the span is processed at most `PROCESS_WIDTH` wide; only the masked region of
its result is laid back on the original, through a feathered mask at full size, so every other pixel of a 4K frame stays
the camera's own. The result is picture only, ProRes 422 HQ, like the other frame tools; the service puts the sound back.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

PROCESS_PIXELS = 640 * 360
# Measured on an M4 with 24 GB (2026-10-17), 30 frames at 640×360: 196 s with RAFT at its 20 iterations, 74 s at 10 (36 s for
# the whole step once warm), with no difference to see in the fill. At 960×544, and at 640×752, the same span stalled on the
# GPU past ten minutes: it is the area that matters, so the area is held to what was measured to run. Half precision on MPS.
RAFT_ITER = 10
CONTEXT = 1.0               # of the regions' larger side, on each side: what ProPainter sees around what it fills
FEATHER = 0.15              # of the region's smaller side: how softly the filled region meets the original


class ProPainter(Adapter):
    def __init__(self, folder: str | Path, ffmpeg: str = "ffmpeg"):
        self._folder, self._ffmpeg = Path(folder).resolve(), ffmpeg
        self._python, self._repo = self._folder / "env" / "bin" / "python", self._folder / "repo"

    def describe(self) -> Capability:
        return Capability(name="inpaint", operations=("remove",), runs="local")

    def available(self) -> bool:
        return self._python.is_file() and (self._repo / "inference_propainter.py").is_file() and (self._repo / "weights" / "ProPainter.pth").is_file()

    def environment(self) -> dict:
        return {"available": True, "remove": True} if self.available() else {"available": False, "fix": "sh scripts/setup-propainter.sh"}

    def _ff(self, args: list[str], what: str) -> None:
        done = subprocess.run([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"{what}: {done.stderr.strip()[-300:]}", retryable=False)

    def submit(self, request: Request) -> Result:
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "ProPainter is not set up (sh scripts/setup-propainter.sh)", retryable=False)
        if request.operation != "remove":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        p = request.params
        src, out = Path(request.inputs["path"]), Path(p["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        t_in, seconds = float(p.get("t_in", 0.0)), float(p.get("seconds") or 0.0)
        info = self._probe(src)
        W, H, rate = info["width"], info["height"], info["rate"]
        frames = max(1, round((seconds or info["duration"] - t_in) * rate))
        regions = [[float(v) for v in r] for r in (p.get("regions") or [p["region"]])]
        # Only the part of the frame around the regions is worked on, with as much again of context on each side: a small
        # object of a 4K frame is then filled near its own resolution, not at a sixth of it.
        x0, y0 = min(r[0] for r in regions), min(r[1] for r in regions)
        x1, y1 = max(r[0] + r[2] for r in regions), max(r[1] + r[3] for r in regions)
        margin = max(x1 - x0, y1 - y0) * CONTEXT
        cx0, cy0 = int(max(0, x0 - margin)) // 2 * 2, int(max(0, y0 - margin)) // 2 * 2
        cx1, cy1 = min(W, int(x1 + margin)), min(H, int(y1 + margin))
        cw, ch = (cx1 - cx0) // 2 * 2, (cy1 - cy0) // 2 * 2
        k = min(1.0, (PROCESS_PIXELS / (cw * ch)) ** 0.5)
        pw, ph = max(64, int(cw * k) // 8 * 8), max(64, int(ch * k) // 8 * 8)
        span = ["-ss", f"{t_in:.3f}"] if t_in > 0 else []
        with tempfile.TemporaryDirectory(prefix="vq_propainter_") as tmp:
            work = Path(tmp)
            (work / "frames").mkdir()
            self._ff([*span, "-i", str(src), "-frames:v", str(frames), "-vf", f"crop={cw}:{ch}:{cx0}:{cy0},scale={pw}:{ph}:flags=area,format=rgb24",
                      str(work / "frames" / "%05d.png")], "frames for ProPainter")
            small = Image.new("L", (pw, ph), 0)
            full = Image.new("L", (W, H), 0)
            for x, y, w, h in regions:
                ImageDraw.Draw(small).rectangle([(x - cx0) * pw / cw, (y - cy0) * ph / ch, (x + w - cx0) * pw / cw, (y + h - cy0) * ph / ch], fill=255)
                pad = FEATHER * min(w, h)
                ImageDraw.Draw(full).rectangle([x - pad / 2, y - pad / 2, x + w + pad / 2, y + h + pad / 2], fill=255)
            small.save(work / "mask.png")
            feather = max(1.0, FEATHER * min(min(r[2], r[3]) for r in regions) / 2)
            full.filter(ImageFilter.GaussianBlur(feather)).save(work / "mask_full.png")
            try:
                # Run from its own folder, which its script imports from (`model`, `core`): a pinned clone, run as a tool.
                done = subprocess.run([str(self._python), "inference_propainter.py", "-i", str(work / "frames"), "-m", str(work / "mask.png"),
                                       "-o", str(work / "results"), "--save_frames", "--fp16", "--raft_iter", str(RAFT_ITER)],
                                      cwd=self._repo, capture_output=True, text=True, timeout=300 + frames * 15)
            except subprocess.TimeoutExpired:
                raise AdapterError(ErrorCode.TIMEOUT, "ProPainter exceeded its time", retryable=True) from None
            made = work / "results" / "frames" / "frames"
            if done.returncode != 0 or not made.is_dir():
                raise AdapterError(ErrorCode.OUTPUT_INVALID, f"ProPainter: {(done.stderr or done.stdout).strip()[-400:]}", retryable=False)
            # Laid on in 4:4:4 at 10 bits, so a log or HDR original loses nothing outside the fill.
            graph = (f"[1:v]scale={cw}:{ch}:flags=lanczos,format=yuv444p10le[fill];[2:v]format=gray,crop={cw}:{ch}:{cx0}:{cy0}[m];"
                     f"[0:v]format=yuv444p10le[base];[fill][m]alphamerge[cut];[base][cut]overlay={cx0}:{cy0}:format=yuv444p10,format=yuv422p10le")
            self._ff([*span, "-i", str(src), "-framerate", f"{rate:.6f}", "-i", str(made / "%04d.png"), "-loop", "1", "-i", str(work / "mask_full.png"),
                      "-filter_complex", graph, "-frames:v", str(frames), "-an", "-c:v", "prores_ks", "-profile:v", "3", str(out)], "laying the fill on the original")
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "ProPainter wrote nothing", retryable=False)
        return Result(outputs={"frames": frames, "process_size": [pw, ph], "context": [cx0, cy0, cw, ch], "regions": regions, "generative": True},
                      files=(str(out),))

    def _probe(self, src: Path) -> dict:
        done = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
                               "-of", "json", str(src)], capture_output=True, text=True)
        try:
            data = json.loads(done.stdout)
            s = data["streams"][0]
            num, _, den = s["avg_frame_rate"].partition("/")
            return {"width": int(s["width"]), "height": int(s["height"]), "rate": float(num) / float(den or 1), "duration": float(data["format"]["duration"])}
        except (ValueError, KeyError, IndexError, ZeroDivisionError):
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"cannot read {src.name}", retryable=False) from None
