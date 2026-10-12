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
        return Capability(name="ffprobe", operations=("probe", "duration"), runs="local")

    def submit(self, request: Request) -> Result:
        path = Path(request.inputs["path"])
        if not path.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{path} does not exist")
        done = run_process(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                           timeout=request.deadline_seconds or 60)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"ffprobe cannot read {path.name}: {done.stderr.strip()[:200]}")
        info = json.loads(done.stdout)
        if request.operation == "duration":                 # any media file, including audio only
            return Result(outputs={"duration": float(info.get("format", {}).get("duration") or 0.0)})
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
IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp"})


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
        return Capability(name="ffmpeg", operations=("blackdetect", "freezedetect", "proxy", "thumbnail", "frames", "segment", "concat", "loudness", "envelope", "enhance", "silencedetect"), runs="local", supports_cancel=True)

    def submit(self, request: Request) -> Result:
        timeout = request.deadline_seconds or 3600
        if request.operation == "concat":
            return self._concat(request.inputs["paths"], request.params, timeout)
        if request.operation == "segment" and not request.inputs.get("path"):
            return self._segment(None, request.params, timeout)
        src = Path(request.inputs["path"])
        if not src.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{src} does not exist")
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

    def _segment(self, src: Path | None, params: dict, timeout: float) -> Result:
        """One timeline item as a self-contained clip: picture conformed to the output format, caption overlay, audio.
        Without a source it is a plain card (used for a gap). Every segment has the same format, so they join without re-encoding."""
        out, d = Path(params["out"]), float(params["duration"])
        w, h, fps = int(params.get("width", 1280)), int(params.get("height", 720)), int(params.get("fps", 30))
        speed = max(0.25, min(4.0, float(params.get("speed") or 1.0)))        # above 1 the footage runs faster; `duration` is always the length on the timeline
        args = ["-y"]
        still = src is not None and src.suffix.lower() in IMAGE_EXT
        if src is None:
            args += ["-f", "lavfi", "-i", f"color=c=0x1e2021:s={w}x{h}:r={fps}:d={d}"]
        elif still:
            args += ["-loop", "1", "-t", str(d), "-i", str(src)]
        else:
            args += ["-ss", str(params.get("t_in", 0.0)), "-t", str(round(d * speed, 3)), "-i", str(src)]
        # "cover" fills the frame and crops the overflow (used when the output shape differs from the footage); "fit" letterboxes.
        # The crop is centred on `focus_x` (0 left, 1 right) so that a subject off to one side stays in a narrower frame.
        fx = max(0.0, min(1.0, float(params.get("focus_x", 0.5))))
        crop = lambda cw, ch, x=fx: f"crop={cw}:{ch}:'min(max(iw*{x}-{cw}/2,0),iw-{cw})':(ih-{ch})/2"
        cover = lambda x=fx: f"scale={w}:{h}:force_original_aspect_ratio=increase,{crop(w, h, x)}"
        filling = params.get("fill", "fit") == "cover"
        fitted = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        shape = cover() if filling else fitted
        if still:
            # A photograph gets a slow push-in so that it reads as a shot, not a slide.
            frames = max(1, round(d * fps))
            shape = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,{crop(w * 2, h * 2)},"
                     f"zoompan=z='1+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}")
        before = []
        if not still and src is not None:
            if speed != 1.0:
                before.append(f"setpts=PTS/{speed}")
            if params.get("stabilise"):
                before.append("deshake=rx=32:ry=32")                # steadies a hand-held shot; the edges it exposes are filled from the frame
            if params.get("normalise"):
                before.append("normalize=smoothing=24:strength=0.6")        # pulls each shot towards full range, so shots from different days sit together
        chain = f"[0:v]{','.join([*before, shape])},setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={d}[base]"
        n, last = 1, "base"
        # An insert is a second picture laid over the first from its moment to the end of the shot: a cut, without splitting the audio.
        for k, ins in enumerate(params.get("inserts") or []):
            at, ipath = float(ins["at"]), Path(ins["path"])
            args += (["-loop", "1"] if ipath.suffix.lower() in IMAGE_EXT else ["-ss", str(ins.get("t_in", 0.0))]) + ["-t", str(round(d - at, 2)), "-i", str(ipath)]
            chain += (f";[{n}:v]{cover(0.5) if filling else fitted},setsar=1,fps={fps},setpts=PTS-STARTPTS+{at}/TB[i{k}]"
                      f";[{last}][i{k}]overlay=enable='gte(t,{at})':eof_action=pass[b{k}]")
            n, last = n + 1, f"b{k}"
        if params.get("overlay"):
            args += ["-loop", "1", "-i", str(params["overlay"])]
            chain += f";[{last}][{n}:v]overlay=0:0[v]"; n += 1
        else:
            chain += f";[{last}]null[v]"
        clean = "highpass=f=80,afftdn=nr=12," if params.get("clean_audio") else ""       # rumble out, steady hiss down
        if params.get("live_sound") and src is not None and not still:
            # The clip keeps its own sound: what was said on camera, at the speed of the picture.
            tempo = "".join(f"atempo={step}," for step in ([2.0, speed / 2.0] if speed > 2.0 else [0.5, speed / 0.5] if speed < 0.5 else [speed]) if step != 1.0)
            chain += f";[0:a]{tempo}{clean}aresample=48000,apad[main]"
        else:
            if params.get("audio"):
                args += ["-i", str(params["audio"])]
            else:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            chain += f";[{n}:a]{clean if params.get('audio') and params.get('own_voice') else ''}aresample=48000,apad[main]"
            n += 1
        if params.get("sfx"):
            # A sound effect starts with the shot and sits under whatever else is heard.
            args += ["-i", str(params["sfx"])]
            chain += f";[{n}:a]aresample=48000,volume={float(params.get('sfx_gain', 0.6))},apad[fx];[main][fx]amix=inputs=2:duration=first:normalize=0[a]"
        else:
            chain += ";[main]anull[a]"
        preview = params.get("quality") == "preview"
        partial = out.with_name(out.stem + ".partial" + out.suffix)
        self._run([*args, "-filter_complex", chain, "-map", "[v]", "-map", "[a]", "-t", str(d), "-c:v", "libx264", "-preset", "ultrafast" if preview else "veryfast", "-crf", "32" if preview else "20",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k", str(partial)], timeout, "segment")
        partial.replace(out)
        return Result(files=(str(out),))

    def _concat(self, paths: list[str], params: dict, timeout: float) -> Result:
        out = Path(params["out"])
        listing = out.with_suffix(".txt")
        listing.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in paths), encoding="utf-8")
        partial = out.with_name(out.stem + ".partial" + out.suffix)
        tail = ["-c:a", "aac", "-ar", "48000", "-b:a", "160k", "-movflags", "+faststart", str(partial)]
        if params.get("music"):
            # The music loops under the narration and is pushed down whenever the narration speaks (ducking).
            gain = float(params.get("music_gain", 0.35))
            graph = (f"[1:a]aresample=48000,volume={gain}[m];[0:a]asplit=2[voice][key];"
                     "[m][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];"
                     "[voice][duck]amix=inputs=2:duration=first:normalize=0,apad=pad_dur=4,loudnorm=I=-16:TP=-1.5:LRA=11[a]")
            self._run(["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-stream_loop", "-1", "-i", str(params["music"]),
                       "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-shortest", *tail], timeout, "concat")
        else:
            # loudnorm emits nothing for less than about three seconds of sound, so the sound is padded and the picture decides the length.
            self._run(["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:v", "copy", "-af", "apad=pad_dur=4,loudnorm=I=-16:TP=-1.5:LRA=11",
                       "-shortest", *tail], timeout, "concat")
        partial.replace(out); listing.unlink(missing_ok=True)
        return Result(files=(str(out),))

    def _enhance(self, src: Path, params: dict, timeout: float) -> Result:
        """A larger or smoother copy of a clip. Upscaling here is a careful resample with a little sharpening, not a learned
        model: it makes footage fill a bigger frame cleanly, it does not invent detail. Smoothing makes in-between frames
        by motion estimation, which suits slow, steady shots and can smear fast ones."""
        out, filters = Path(params["out"]), []
        if params.get("smooth_fps"):
            filters.append(f"minterpolate=fps={int(params['smooth_fps'])}:mi_mode=mci:mc_mode=aobmc:vsbmc=1")
        factor = int(params.get("upscale") or 1)
        if factor > 1:
            filters.append(f"scale=iw*{factor}:ih*{factor}:flags=lanczos,unsharp=5:5:0.6:5:5:0.0")
        if not filters:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "nothing to enhance: give upscale or smooth_fps")
        partial = out.with_name(out.stem + ".partial" + out.suffix)
        self._run(["-y", "-i", str(src), "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "copy", str(partial)], timeout, "enhance")
        partial.replace(out)
        return Result(files=(str(out),))

    def _silencedetect(self, src: Path, params: dict, timeout: float) -> Result:
        """Stretches with nothing to hear, as [start, end] pairs. A silence that runs to the end of the file ends at None."""
        done = self._run(["-i", str(src), "-af", f"silencedetect=n={params.get('noise_db', -45)}dB:d={params.get('min_seconds', 0.4)}", "-vn", "-f", "null", "-"], timeout, "silencedetect")
        re = __import__("re")
        starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", done.stderr)]
        ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", done.stderr)]
        return Result(outputs={"silent_ranges": [[max(0.0, s), ends[i] if i < len(ends) else None] for i, s in enumerate(starts)]})

    def _envelope(self, src: Path, params: dict, timeout: float) -> Result:
        """How loud the sound is, `rate` times a second: enough to recognise the same event in two recordings."""
        rate, raw = int(params.get("rate", 100)), Path(params["out"])
        self._run(["-y", "-t", str(params.get("max_seconds", 600)), "-i", str(src), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", str(raw)], timeout, "envelope")
        samples = __import__("array").array("h")
        data = raw.read_bytes(); raw.unlink()
        samples.frombytes(data[:len(data) // 2 * 2])
        window = 8000 // rate
        return Result(outputs={"rate": rate, "envelope": [sum(map(abs, samples[i:i + window])) / window for i in range(0, len(samples) - window + 1, window)]})

    def _loudness(self, src: Path, params: dict, timeout: float) -> Result:
        done = self._run(["-i", str(src), "-af", "volumedetect", "-vn", "-f", "null", "-"], timeout, "loudness")
        found = dict(__import__("re").findall(r"(mean_volume|max_volume): (-?[\d.]+|-inf) dB", done.stderr))
        number = lambda v: -120.0 if v in (None, "-inf") else float(v)
        return Result(outputs={"mean_db": number(found.get("mean_volume")), "max_db": number(found.get("max_volume"))})

    def _thumbnail(self, src: Path, params: dict, timeout: float) -> Result:
        out = Path(params["out"])
        self._run(["-y", "-ss", str(params.get("at", 0.0)), "-i", str(src), "-frames:v", "1", "-vf", "scale=-2:'min(360,ih)'",
                   "-q:v", "3", str(out)], timeout, "thumbnail")
        return Result(files=(str(out),))
