"""Media adapters: FFprobe and FFmpeg, run as local child processes."""
import json
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process


def _rate(value: str | None) -> float:
    num, _, den = (value or "0/1").partition("/")
    return float(num) / float(den) if den and float(den) else 0.0


class FFprobeAdapter(Adapter):
    def describe(self) -> Capability:
        return Capability(name="ffprobe", operations=("probe",), runs="local")

    def submit(self, request: Request) -> Result:
        path = Path(request.inputs["path"])
        if not path.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{path} does not exist")
        done = run_process(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                           timeout=request.deadline_seconds or 60)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"ffprobe cannot read {path.name}: {done.stderr.strip()[:200]}")
        info = json.loads(done.stdout)
        video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
        if video is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"{path.name} has no video stream")
        fmt = info.get("format", {})
        return Result(outputs={
            "duration": float(fmt.get("duration") or video.get("duration") or 0.0),
            "width": video.get("width"),
            "height": video.get("height"),
            "frame_rate": round(_rate(video.get("avg_frame_rate")), 3),
            "codec": video.get("codec_name"),
            "color_transfer": video.get("color_transfer"),
            "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
            "created": fmt.get("tags", {}).get("creation_time"),
        })


_BLACK = __import__("re").compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)")
_FREEZE = __import__("re").compile(r"freeze_(start|end): ([\d.]+)")
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})


def ffmpeg_capabilities() -> dict:
    """Which filters and encoders this FFmpeg build has; the first part of the environment check."""
    filters = run_process(["ffmpeg", "-hide_banner", "-filters"], timeout=30).stdout
    encoders = run_process(["ffmpeg", "-hide_banner", "-encoders"], timeout=30).stdout
    have = {line.split()[1] for line in filters.splitlines() if len(line.split()) > 2}
    enc = {line.split()[1] for line in encoders.splitlines() if len(line.split()) > 2}
    return {
        "filters": {name: name in have for name in ("blackdetect", "scale", "fps", "zscale", "tonemap", "subtitles", "drawtext", "loudnorm")},
        "encoders": {name: name in enc for name in ("h264_videotoolbox", "hevc_videotoolbox", "libx264")},
    }


class FFmpegAdapter(Adapter):
    def environment(self) -> dict:
        return ffmpeg_capabilities()

    def describe(self) -> Capability:
        return Capability(name="ffmpeg", operations=("blackdetect", "freezedetect", "proxy", "thumbnail", "frames"), runs="local", supports_cancel=True)

    def submit(self, request: Request) -> Result:
        src = Path(request.inputs["path"])
        if not src.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{src} does not exist")
        timeout = request.deadline_seconds or 3600
        return getattr(self, f"_{request.operation}")(src, request.params, timeout)

    def _run(self, args: list[str], timeout: float, what: str):
        done = run_process(["ffmpeg", "-hide_banner", "-nostdin", "-nostats", *args], timeout=timeout)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"ffmpeg {what} failed: {done.stderr.strip()[-300:]}")
        return done

    def _blackdetect(self, src: Path, params: dict, timeout: float) -> Result:
        min_duration = params.get("min_duration", 0.5)
        done = self._run(["-i", str(src), "-vf", f"blackdetect=d={min_duration}:pix_th=0.10", "-an", "-f", "null", "-"], timeout, "blackdetect")
        ranges = [[round(float(a), 3), round(float(b), 3)] for a, b in _BLACK.findall(done.stderr)]
        return Result(outputs={"black_ranges": ranges})

    def _freezedetect(self, src: Path, params: dict, timeout: float) -> Result:
        done = self._run(["-i", str(src), "-vf", f"freezedetect=n=-60dB:d={params.get('min_duration', 2.0)}", "-an", "-f", "null", "-"],
                         timeout, "freezedetect")
        ranges, start = [], None
        for kind, value in _FREEZE.findall(done.stderr):
            if kind == "start":
                start = float(value)
            elif start is not None:
                ranges.append([round(start, 3), round(float(value), 3)]); start = None
        if start is not None:                                   # frozen until the end of the file
            ranges.append([round(start, 3), None])
        return Result(outputs={"frozen_ranges": ranges})

    def _proxy(self, src: Path, params: dict, timeout: float) -> Result:
        out = Path(params["out"])
        height = int(params.get("max_height", 720))
        partial = out.with_name(out.stem + ".partial" + out.suffix)     # written under another name, renamed when complete
        common = ["-y", "-i", str(src), "-vf", f"scale=-2:'min({height},ih)'", "-pix_fmt", "yuv420p", "-fps_mode", "cfr"]
        audio = ["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(partial)]
        bitrate = params.get("video_bitrate", "1200k")
        encoders = [["-c:v", params.get("encoder", "h264_videotoolbox"), "-b:v", bitrate],
                    ["-c:v", "libx264", "-preset", "veryfast", "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "2400k"]]
        last = None
        for encoder in encoders:
            try:
                self._run([*common, *encoder, *audio], timeout, "proxy")
                break
            except AdapterError as err:
                if err.code is not ErrorCode.INVALID_REQUEST:
                    raise
                last = err                                             # hardware encoder refused; fall back to software
        else:
            partial.unlink(missing_ok=True)
            raise last
        partial.replace(out)
        return Result(files=(str(out),))

    def _frames(self, src: Path, params: dict, timeout: float) -> Result:
        """Still frames at a fixed rate; frame k shows time k / fps."""
        out_dir, fps = Path(params["out_dir"]), float(params.get("fps", 0.5))
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("f_*.jpg"):
            old.unlink()
        self._run(["-y", "-i", str(src), "-vf", f"fps={fps},scale={int(params.get('width', 448))}:-2", "-q:v", "4", str(out_dir / "f_%05d.jpg")],
                  timeout, "frames")
        return Result(outputs={"frames": [str(p) for p in sorted(out_dir.glob("f_*.jpg"))], "fps": fps})

    def _thumbnail(self, src: Path, params: dict, timeout: float) -> Result:
        out = Path(params["out"])
        self._run(["-y", "-ss", str(params.get("at", 0.0)), "-i", str(src), "-frames:v", "1", "-vf", "scale=-2:'min(360,ih)'",
                   "-q:v", "3", str(out)], timeout, "thumbnail")
        return Result(files=(str(out),))
