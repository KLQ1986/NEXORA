"""Media adapters: FFprobe and FFmpeg, run as local child processes."""
import json
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process


def _rate(value: str | None) -> float:
    num, _, den = (value or "0/1").partition("/")
    return float(num) / float(den) if den and float(den) else 0.0


# Colour descriptions by their ffprobe names, as the codes of ITU-T H.273 that a stream carries.
H273 = {"color_primaries": {"bt709": 1, "bt470m": 4, "bt470bg": 5, "smpte170m": 6, "smpte240m": 7, "bt2020": 9, "smpte432": 12},
        "color_transfer": {"bt709": 1, "smpte170m": 6, "linear": 8, "iec61966-2-1": 13, "bt2020-10": 14, "smpte2084": 16, "arib-std-b67": 18},
        "color_space": {"gbr": 0, "bt709": 1, "fcc": 4, "bt470bg": 5, "smpte170m": 6, "bt2020nc": 9, "bt2020c": 10}}

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
            **technical(info, video),
        })


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bit_depth(video: dict) -> int | None:
    """Bits a colour sample: given by the stream, else read from the pixel format's name (yuv420p10le is 10)."""
    given = _int(video.get("bits_per_raw_sample"))
    if given:
        return given
    import re
    found = re.search(r"p(\d{2})(le|be)?$", video.get("pix_fmt") or "")
    return int(found.group(1)) if found else (8 if video.get("pix_fmt") else None)


def _rotation(video: dict) -> int:
    """How far a player turns the picture (phones record upright footage on its side and say so)."""
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            return int(round(float(side["rotation"]))) % 360
    return int(video.get("tags", {}).get("rotate") or 0) % 360


def technical(info: dict, video: dict) -> dict:
    """Everything else a file says about itself (design 2026-10-14, group 01): container, rates, colour, rotation, the
    streams it carries and the device that made it. What the file declares is kept as declared; where two declarations
    disagree (the nominal and the average frame rate of variable-rate footage) both are kept and the disagreement named."""
    fmt, tags = info.get("format", {}), info.get("format", {}).get("tags", {}) or {}
    streams = info.get("streams", [])
    width, height, rotation = video.get("width") or 0, video.get("height") or 0, _rotation(video)
    shown_w, shown_h = (height, width) if rotation in (90, 270) else (width, height)
    sar = video.get("sample_aspect_ratio") or "1:1"
    sn, _, sd = sar.partition(":")
    sar_value = float(sn) / float(sd) if sd and float(sd or 0) and float(sn or 0) else 1.0
    display = shown_w * sar_value / shown_h if shown_h else 0.0
    nominal, average = _rate(video.get("r_frame_rate")), _rate(video.get("avg_frame_rate"))
    audio = [{"codec": s.get("codec_name"), "channels": s.get("channels"), "layout": s.get("channel_layout"),
              "sample_rate": _int(s.get("sample_rate")), "bit_rate": _int(s.get("bit_rate")), "language": (s.get("tags") or {}).get("language")}
             for s in streams if s.get("codec_type") == "audio"]
    data = [(s.get("tags") or {}).get("handler_name") or s.get("codec_tag_string") for s in streams if s.get("codec_type") == "data"]
    timecode = tags.get("timecode") or next(((s.get("tags") or {}).get("timecode") for s in streams if (s.get("tags") or {}).get("timecode")), None)
    make = tags.get("com.apple.quicktime.make") or tags.get("make")
    model = tags.get("com.apple.quicktime.model") or tags.get("model")
    return {
        "container": fmt.get("format_name"),
        "size": _int(fmt.get("size")),
        "bit_rate": _int(fmt.get("bit_rate")),
        "video_bit_rate": _int(video.get("bit_rate")),
        "profile": video.get("profile"),
        "pixel_format": video.get("pix_fmt"),
        "bit_depth": _bit_depth(video),
        "color_primaries": video.get("color_primaries"),
        "color_space": video.get("color_space"),
        "color_range": video.get("color_range"),
        "hdr": video.get("color_transfer") in HDR_TRANSFERS,
        "rotation": rotation,
        "display_width": shown_w, "display_height": shown_h,
        "display_aspect": round(display, 4),
        "orientation": "vuông" if abs(display - 1) < 0.05 else ("ngang" if display > 1 else "dọc"),
        "nominal_frame_rate": round(nominal, 3),
        "variable_frame_rate": bool(nominal and average and abs(nominal - average) / nominal > 0.01),
        "frames_declared": _int(video.get("nb_frames")),
        "field_order": video.get("field_order"),
        "dolby_vision": any("dovi" in str(sd.get("side_data_type", "")).lower() for sd in video.get("side_data_list") or []),
        "audio_streams": audio,
        "data_streams": [d for d in data if d],
        "timecode": timecode,
        "encoder": tags.get("encoder"),
        "device": " ".join(v for v in (make, model) if v) or tags.get("encoder"),
        "location": tags.get("com.apple.quicktime.location.ISO6709") or tags.get("location"),
    }


_BLACK = __import__("re").compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)")
_FREEZE = __import__("re").compile(r"freeze_(start|end): ([\d.]+)")
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp"})


FULL_BUILDS = ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "/usr/local/opt/ffmpeg-full/bin/ffmpeg")
# HDR (PQ or HLG, BT.2020) to the SDR every cut is made in: to linear light, to BT.709 primaries, highlights rolled off, back to BT.709 gamma.
HDR_TO_SDR = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"


def find_ffmpeg(wanted: str = "") -> str:
    """The FFmpeg to run: the one named in the settings, else a fuller build if one is installed beside the usual one
    (it has the filters HDR conversion needs), else whatever `ffmpeg` is on the path."""
    if wanted:
        return wanted
    return next((path for path in FULL_BUILDS if Path(path).is_file()), "ffmpeg")


def ffmpeg_capabilities(binary: str = "ffmpeg") -> dict:
    """Which filters and encoders this FFmpeg build has; the first part of the environment check."""
    filters = run_process([binary, "-hide_banner", "-filters"], timeout=30).stdout
    encoders = run_process([binary, "-hide_banner", "-encoders"], timeout=30).stdout
    have = {line.split()[1] for line in filters.splitlines() if len(line.split()) > 2}
    enc = {line.split()[1] for line in encoders.splitlines() if len(line.split()) > 2}
    return {
        "binary": binary,
        "filters": {name: name in have for name in ("blackdetect", "scale", "fps", "zscale", "tonemap", "subtitles", "drawtext", "loudnorm", "blurdetect",
                                                     # what Visual Quality's steps are made of
                                                     "lut3d", "colorlevels", "eq", "hqdn3d", "nlmeans", "bm3d", "cas", "deflicker", "deband", "deblock",
                                                     "bwdif", "fieldmatch", "decimate", "minterpolate", "vidstabdetect", "vidstabtransform", "libvmaf")},
        "encoders": {name: name in enc for name in ("h264_videotoolbox", "hevc_videotoolbox", "libx264")},
    }


class FFmpegAdapter(Adapter):
    def __init__(self, binary: str = ""):
        self._binary = find_ffmpeg(binary)
        self._can_tonemap: bool | None = None
        self._can_blurdetect: bool | None = None
        self.hardware_decoding = __import__("platform").system() == "Darwin"

    def environment(self) -> dict:
        return ffmpeg_capabilities(self._binary)

    def _sdr(self, params: dict) -> list[str]:
        """The filters that bring HDR footage to SDR, when the footage is HDR. Without them HDR footage comes out grey and
        washed, so a build that cannot do it says so instead of quietly producing that."""
        if params.get("color_transfer") not in HDR_TRANSFERS:
            return []
        if self._can_tonemap is None:
            have = ffmpeg_capabilities(self._binary)["filters"]
            self._can_tonemap = have["zscale"] and have["tonemap"]
        if not self._can_tonemap:
            raise AdapterError(ErrorCode.UNAVAILABLE, "this footage is HDR and this FFmpeg build cannot convert it: install one with zscale (brew install ffmpeg-full)", retryable=False)
        return [HDR_TO_SDR]

    def describe(self) -> Capability:
        return Capability(name="ffmpeg", operations=("blackdetect", "freezedetect", "proxy", "thumbnail", "frames", "segment", "concat", "loudness", "envelope", "enhance", "silencedetect", "scenecuts", "analysis", "unusable", "r128", "pcm", "telemetry", "extract", "vq_render", "vq_stabilise", "vq_mux"), runs="local", supports_cancel=True)

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
        done = run_process([self._binary, "-hide_banner", "-nostdin", "-nostats", *args], timeout=timeout)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"ffmpeg {what} failed: {done.stderr.strip()[-300:]}")
        return done

    def _decode(self, args: list[str], timeout: float, what: str):
        """A pass that decodes every frame of a file. On a Mac the decoding is done by the media engine (VideoToolbox), about
        five times faster for 4K HEVC than the processor; when the hardware refuses a file, the same pass runs on the processor.
        `args` holds the input as "-i", path; the hardware option is put before it."""
        if self.hardware_decoding:
            at = args.index("-i")
            try:
                return self._run([*args[:at], "-hwaccel", "videotoolbox", *args[at:]], timeout, what)
            except AdapterError as err:
                if err.code is not ErrorCode.INVALID_REQUEST:
                    raise
        return self._run(args, timeout, what)

    def _blackdetect(self, src: Path, params: dict, timeout: float) -> Result:
        min_duration = params.get("min_duration", 0.5)
        done = self._decode(["-i", str(src), "-vf", f"blackdetect=d={min_duration}:pix_th=0.10", "-an", "-f", "null", "-"], timeout, "blackdetect")
        ranges = [[round(float(a), 3), round(float(b), 3)] for a, b in _BLACK.findall(done.stderr)]
        return Result(outputs={"black_ranges": ranges})

    def _unusable(self, src: Path, params: dict, timeout: float) -> Result:
        """Black stretches and frozen stretches in one pass over the file. Long 4K footage takes minutes to decode, so the two
        are looked for together instead of one after the other."""
        done = self._decode(["-i", str(src), "-vf", f"blackdetect=d={params.get('min_black', 0.5)}:pix_th=0.10,freezedetect=n=-60dB:d={params.get('min_frozen', 2.0)}",
                          "-an", "-f", "null", "-"], timeout, "unusable")
        black = [[round(float(a), 3), round(float(b), 3)] for a, b in _BLACK.findall(done.stderr)]
        frozen, start = [], None
        for kind, value in _FREEZE.findall(done.stderr):
            if kind == "start":
                start = float(value)
            elif start is not None:
                frozen.append([round(start, 3), round(float(value), 3)]); start = None
        if start is not None:                                   # frozen until the end of the file
            frozen.append([round(start, 3), None])
        return Result(outputs={"black_ranges": black, "frozen_ranges": frozen})

    def _scenecuts(self, src: Path, params: dict, timeout: float) -> Result:
        """The instants at which the picture changes outright: one shot ends and another begins. Measured on a small copy of
        each frame, which is enough to see a cut and far quicker."""
        threshold = float(params.get("threshold", 0.35))
        done = self._decode(["-i", str(src), "-vf", f"{','.join([*self._sdr(params), 'scale=320:-2'])},select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"], timeout, "scenecuts")
        times = [round(float(t), 2) for t in __import__("re").findall(r"pts_time:([\d.]+)", done.stderr)]
        return Result(outputs={"cuts": sorted(t for t in dict.fromkeys(times) if t > 0.2)})

    def _analysis(self, src: Path, params: dict, timeout: float) -> Result:
        """Small copies of the frames for measuring, written raw to `out`: every frame at `fps`, `width` by `height`, three bytes a
        pixel. In the same pass, how blurred the full-size picture is, twice a second, where this build can measure it."""
        out, fps = Path(params["out"]), float(params.get("fps", 25.0))
        width, height, blur_rate = int(params.get("width", 96)), int(params.get("height", 54)), float(params.get("blur_rate", 2.0))
        out.parent.mkdir(parents=True, exist_ok=True)
        notes = out.with_suffix(".blur.txt")
        small = f"fps={fps:g},scale={width}:{height}:flags=area,format=rgb24"
        head = ",".join([*self._sdr(params), "split=2"]) if self._has_blurdetect() else ",".join([*self._sdr(params), "null"])
        if self._has_blurdetect():
            notes.unlink(missing_ok=True)
            graph = f"[0:v]{head}[a][b];[a]{small}[small];[b]fps={blur_rate:g},blurdetect=block_pct=80,metadata=print:file='{notes}'[soft]"
            maps = ["-map", "[small]", "-f", "rawvideo", str(out), "-map", "[soft]", "-f", "null", "-"]
        else:
            graph, maps = f"[0:v]{head},{small}[small]", ["-map", "[small]", "-f", "rawvideo", str(out)]
        self._decode(["-y", "-i", str(src), "-filter_complex", graph, "-an", *maps], timeout, "analysis")
        blur = [round(float(v), 3) for v in __import__("re").findall(r"lavfi\.blur=([\d.]+)", notes.read_text())] if notes.is_file() else []
        notes.unlink(missing_ok=True)
        return Result(outputs={"fps": fps, "width": width, "height": height, "frames": out.stat().st_size // (width * height * 3),
                               "blur": blur, "blur_rate": blur_rate if blur else 0.0}, files=(str(out),))

    def _has_blurdetect(self) -> bool:
        if self._can_blurdetect is None:
            self._can_blurdetect = bool(ffmpeg_capabilities(self._binary)["filters"].get("blurdetect"))
        return self._can_blurdetect

    def _freezedetect(self, src: Path, params: dict, timeout: float) -> Result:
        done = self._decode(["-i", str(src), "-vf", f"freezedetect=n=-60dB:d={params.get('min_duration', 2.0)}", "-an", "-f", "null", "-"],
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
        common = ["-y", "-i", str(src), "-vf", ",".join([*self._sdr(params), f"scale=-2:'min({height},ih)'"]), "-pix_fmt", "yuv420p", "-fps_mode", "cfr"]
        audio = ["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(partial)]
        bitrate = params.get("video_bitrate", "1200k")
        encoders = [["-c:v", params.get("encoder", "h264_videotoolbox"), "-b:v", bitrate],
                    ["-c:v", "libx264", "-preset", "veryfast", "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "2400k"]]
        last = None
        for encoder in encoders:
            try:
                self._decode([*common, *encoder, *audio], timeout, "proxy")
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
        # A stretch only (`t_in`, `seconds`), for a burst of frames in a row; `filters` go before the rate and the size.
        span = (["-ss", str(params["t_in"])] if params.get("t_in") else []) + ["-i", str(src)] + (["-t", str(params["seconds"])] if params.get("seconds") else [])
        chain = [*self._sdr(params), *(params.get("filters") or []), f"fps={fps},scale={int(params.get('width', 448))}:-2"]
        self._decode(["-y", *span, "-vf", ",".join(chain), "-q:v", str(int(params.get("quality", 4))), str(out_dir / "f_%05d.jpg")],
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
            # An approved Visual Quality recipe for the stretch comes first and does the colour (its tone map included); without
            # one, HDR is brought to SDR here as before.
            before += list(params.get("vq_filters") or []) or self._sdr(params)
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
            own = ",".join(ins.get("vq_filters") or [])
            chain += (f";[{n}:v]{own + ',' if own else ''}{cover(0.5) if filling else fitted},setsar=1,fps={fps},setpts=PTS-STARTPTS+{at}/TB[i{k}]"
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
        if params.get("plain"):
            # Parts of one recording put back together (Visual Quality): picture and sound as they are, nothing re-encoded.
            self._run(["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(partial)], timeout, "concat")
            partial.replace(out); listing.unlink(missing_ok=True)
            return Result(files=(str(out),))
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
        out, filters = Path(params["out"]), list(self._sdr(params))
        if params.get("smooth_fps"):
            filters.append(f"minterpolate=fps={int(params['smooth_fps'])}:mi_mode=mci:mc_mode=aobmc:vsbmc=1")
        factor = int(params.get("upscale") or 1)
        if factor > 1:
            filters.append(f"scale=iw*{factor}:ih*{factor}:flags=lanczos,unsharp=5:5:0.6:5:5:0.0")
        if not params.get("smooth_fps") and factor <= 1:
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

    def _r128(self, src: Path, params: dict, timeout: float) -> Result:
        """Loudness to EBU R 128: the momentary loudness ten times a second, the integrated loudness of the whole file, its
        loudness range and its true peak."""
        done = self._run(["-i", str(src), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], timeout, "r128")
        re = __import__("re")
        momentary = [None if float(m) <= -120 else round(float(m), 1) for m in re.findall(r"t:\s*[\d.]+\s+TARGET:[^M]*M:\s*(-?[\d.]+|-inf)", done.stderr.replace("-inf", "-120.7"))]
        summary = done.stderr[done.stderr.rfind("Summary:"):]
        grab = lambda pattern: (lambda m: float(m.group(1)) if m else None)(re.search(pattern, summary))
        return Result(outputs={"rate": 10, "momentary": momentary, "integrated": grab(r"I:\s*(-?[\d.]+) LUFS"), "range": grab(r"LRA:\s*(-?[\d.]+) LU"),
                               "true_peak": grab(r"Peak:\s*(-?[\d.]+) dBFS")})

    def _pcm(self, src: Path, params: dict, timeout: float) -> Result:
        """The sound as raw 32-bit float samples, one channel, written to `out`."""
        out = Path(params["out"])
        rate = int(params.get("rate", 16000))
        self._run(["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", str(out)], timeout, "pcm")
        return Result(outputs={"rate": rate, "samples": out.stat().st_size // 4}, files=(str(out),))

    def _telemetry(self, src: Path, params: dict, timeout: float) -> Result:
        """The packets of a camera's own data stream (DJI's "CAM meta"), one per frame, as raw bytes; none when the file has no such stream."""
        probe = run_process(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type:stream_tags=handler_name", "-of", "json", str(src)], timeout=60)
        streams = json.loads(probe.stdout or "{}").get("streams", [])
        wanted = next((s["index"] for s in streams if s.get("codec_type") == "data" and "meta" in str((s.get("tags") or {}).get("handler_name", "")).lower()), None)
        if wanted is None:
            return Result(outputs={"packets": []})
        sizes = run_process(["ffprobe", "-v", "error", "-select_streams", str(wanted), "-show_entries", "packet=size", "-of", "csv=p=0", str(src)], timeout=timeout).stdout.split()
        out = Path(params["out"])
        self._run(["-y", "-i", str(src), "-map", f"0:{wanted}", "-c", "copy", "-f", "data", str(out)], timeout, "telemetry")
        raw, pos, packets = out.read_bytes(), 0, []
        out.unlink(missing_ok=True)
        for n in (int(x) for x in sizes if x.strip().isdigit()):
            packets.append(raw[pos:pos + n]); pos += n
        return Result(outputs={"packets": [p.hex() for p in packets]})

    def _extract(self, src: Path, params: dict, timeout: float) -> Result:
        """A piece of the original to keep and use elsewhere (design 2026-10-15, section 9 F), at the original's size and depth:
        `kind` "clip" (picture and sound from `t_in` to `t_out`, HEVC, 10-bit when the original is), "still" (one frame at `at`,
        full size) or "audio" (24-bit WAV at 48 kHz). The look is the original's: log footage stays log, HDR stays HDR in a clip;
        a still of HDR footage is brought to SDR, since a JPEG cannot hold it."""
        out, kind = Path(params["out"]), params["kind"]
        out.parent.mkdir(parents=True, exist_ok=True)
        given = list(params.get("filters") or [])               # an approved Visual Quality recipe for the stretch
        if kind == "still":
            vf = given or self._sdr(params)
            self._run(["-y", "-ss", str(params["at"]), "-i", str(src), "-frames:v", "1", *(["-vf", ",".join(vf)] if vf else []), "-q:v", "2", str(out)], timeout, "still")
        else:
            t_in, t_out = float(params["t_in"]), float(params["t_out"])
            span = ["-y", "-ss", str(t_in), "-i", str(src), "-t", str(round(t_out - t_in, 3))]
            if kind == "audio":
                self._run([*span, "-vn", "-c:a", "pcm_s24le", "-ar", "48000", str(out)], timeout, "audio")
            elif kind == "clip":
                deep = int(params.get("bit_depth") or 8) > 8
                video = (["-c:v", "hevc_videotoolbox", "-profile:v", "main10" if deep else "main", "-q:v", "80", "-tag:v", "hvc1"]
                         if params.get("hardware", True) else ["-c:v", "libx265", "-crf", "16", "-preset", "fast", "-tag:v", "hvc1",
                                                              "-pix_fmt", "yuv420p10le" if deep else "yuv420p"])
                # The encoder does not carry the original's colour description over by itself (VideoToolbox drops the primaries even
                # when told them); without it an editor reads the clip wrongly. It is written into the stream itself, by H.273 code.
                codes = [f"{name}={H273[key].get(str(params.get(key)))}" for key, name in (("color_primaries", "colour_primaries"),
                         ("color_transfer", "transfer_characteristics"), ("color_space", "matrix_coefficients")) if H273[key].get(str(params.get(key)))]
                colour = ["-bsf:v", "hevc_metadata=" + ":".join(codes)] if codes else []
                args = [*span, "-map", "0:v:0", "-map", "0:a:0?", *(["-vf", ",".join(given)] if given else []), *video, *colour, "-c:a", "aac", "-b:a", "256k",
                        "-map_metadata", "0", "-movflags", "+faststart", str(out)]
                try:
                    self._run(args, timeout, "clip")
                except AdapterError:
                    if not params.get("hardware", True):
                        raise
                    return self._extract(src, {**params, "hardware": False}, timeout)     # no media engine: the processor does it
            else:
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown kind {kind}")
        return Result(outputs={"kind": kind, "size": out.stat().st_size}, files=(str(out),))

    def _vq_render(self, src: Path, params: dict, timeout: float) -> Result:
        """A stretch of a source through a Visual Quality filter chain (design 2026-10-16): `kind` "still" (one frame at `t_in`,
        PNG, at `width` or full size) or "video" (`t_in` for `seconds`, HEVC 10-bit with its sound, or ProRes 422 HQ with
        `master`). `filters` is the chain; `colour` the description the result carries (after a transform, Rec.709)."""
        out, kind = Path(params["out"]), params.get("kind", "video")
        out.parent.mkdir(parents=True, exist_ok=True)
        chain = list(params.get("filters") or [])
        if params.get("width"):
            chain.append(f"scale={int(params['width'])}:-2:flags=lanczos")
        vf = ["-vf", ",".join(chain)] if chain else []
        # A seek of 0 goes past the only frame of a still, and FFmpeg then writes nothing yet ends well: seek only when there is
        # somewhere to go, and never take an ended run for a written file.
        seek = ["-ss", str(params["t_in"])] if float(params.get("t_in") or 0.0) > 0 else []
        if kind == "still":
            out.unlink(missing_ok=True)
            # An intermediate between steps keeps 16 bits a channel: written at 8, a 10-bit or RAW shade lifted later posterises.
            deep = ["-pix_fmt", "rgb48be" if out.suffix.lower() == ".png" else "rgb48le"] if params.get("deep") and out.suffix.lower() in (".png", ".tif", ".tiff") else []
            self._run(["-y", *seek, "-i", str(src), "-frames:v", "1", "-update", "1", *vf, *deep, str(out)], timeout, "vq still")
            if not out.is_file() or out.stat().st_size == 0:
                raise AdapterError(ErrorCode.OUTPUT_INVALID, f"no frame came out of {src.name} at {params.get('t_in', 0.0)}s", retryable=False)
            return Result(outputs={"kind": "still"}, files=(str(out),))
        colour = params.get("colour") or {}
        codes = [f"{name}={H273[key][colour[key]]}" for key, name in (("color_primaries", "colour_primaries"), ("color_transfer", "transfer_characteristics"),
                 ("color_space", "matrix_coefficients")) if colour.get(key) in H273[key]]
        tags = ["-bsf:v", "hevc_metadata=" + ":".join(codes)] if codes and not params.get("master") else []
        if params.get("master"):
            video = ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
        elif params.get("codec") == "store":
            # A file kept for cuts to take from (Visual Quality's prepared shots): HEVC 10-bit by the Apple encoder at a high
            # quality. Measured on 0002 (2026-10-17): 31 MB/s against 116 for ProRes 422 HQ, SSIM 0.9973 against 0.9987, and faster
            # to write; without the hardware encoder, x265 at crf 12 (20 MB/s, SSIM 0.993, three times slower).
            video = (["-c:v", "hevc_videotoolbox", "-q:v", "80", "-pix_fmt", "p010le", "-tag:v", "hvc1"] if self._has_encoder("hevc_videotoolbox")
                     else ["-c:v", "libx265", "-crf", "12", "-preset", "fast", "-x265-params", "log-level=error", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1"])
        elif params.get("codec") == "h264":                   # a preview any browser plays
            video = ["-c:v", "libx264", "-crf", str(int(params.get("crf", 20))), "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            tags = [x for k, flag in (("color_primaries", "-color_primaries"), ("color_transfer", "-color_trc"), ("color_space", "-colorspace"))
                    if colour.get(k) for x in (flag, colour[k])]
        else:
            video = ["-c:v", "libx265", "-crf", str(int(params.get("crf", 16))), "-preset", params.get("preset", "fast"), "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1"]
        span = [*seek, "-i", str(src)] + (["-t", str(params["seconds"])] if params.get("seconds") else [])
        sound = ["-map", "0:a:0?"]
        if params.get("sound_from"):
            # The picture came from a processor (picture only): the sound is taken straight from the same stretch of the source,
            # so no copy of the picture is written just to put the sound back.
            at = float(params.get("sound_t_in") or 0.0)
            span += [*(["-ss", f"{at:.3f}"] if at > 0 else []), "-i", str(params["sound_from"])] + (["-t", str(params["seconds"])] if params.get("seconds") else [])
            sound = ["-map", "1:a:0?", "-shortest"]
        out.unlink(missing_ok=True)
        self._run(["-y", *span, "-map", "0:v:0", *sound, *vf, *video, *tags, "-c:a", "aac", "-b:a", "256k", str(out)], timeout, "vq video")
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"nothing came out of {src.name}", retryable=False)
        return Result(outputs={"kind": "video", "size": out.stat().st_size}, files=(str(out),))

    def _vq_stabilise(self, src: Path, params: dict, timeout: float) -> Result:
        """Steadies a stretch from its picture alone, in two passes (vidstab): the camera's path is measured, then smoothed, and
        the frame moved against the jitter. For a source without the camera's own motion data (Gyroflow takes that)."""
        out = Path(params["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        motions = out.with_suffix(".trf")
        seek = ["-ss", str(params["t_in"])] if float(params.get("t_in") or 0) > 0 else []
        span = [*seek, "-i", str(src)] + (["-t", str(params["seconds"])] if params.get("seconds") else [])
        self._run(["-y", *span, "-vf", f"vidstabdetect=shakiness={int(params.get('shakiness', 6))}:accuracy=15:result={motions}", "-f", "null", "-"], timeout, "vidstab detect")
        smoothing, zoom = int(params.get("smoothing", 15)), float(params.get("zoom", 0))
        self._run(["-y", *span, "-vf", f"vidstabtransform=input={motions}:smoothing={smoothing}:zoom={zoom}:optzoom={1 if zoom == 0 else 0}:interpol=bicubic",
                   "-an", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", str(out)], timeout, "vidstab transform")
        motions.unlink(missing_ok=True)
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "stabilisation wrote nothing", retryable=False)
        return Result(outputs={"stabilised": True}, files=(str(out),))

    def _has_encoder(self, name: str) -> bool:
        known = getattr(self, "_encoders", None)
        if known is None:
            try:
                listed = run_process([self._binary, "-hide_banner", "-encoders"], timeout=30).stdout
            except AdapterError:
                listed = ""
            known = self._encoders = {line.split()[1] for line in listed.splitlines() if len(line.split()) > 1 and line.startswith(" V")}
        return name in known

    def _vq_mux(self, src: Path, params: dict, timeout: float) -> Result:
        """The picture of a processed stretch with the sound of the same stretch of the source: processors work on pictures."""
        out = Path(params["out"])
        seek = ["-ss", str(params["t_in"])] if float(params.get("t_in") or 0) > 0 else []
        sound = [*seek, "-i", str(params["sound_from"])] + (["-t", str(params["seconds"])] if params.get("seconds") else [])
        self._run(["-y", "-i", str(src), *sound, "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "pcm_s24le", "-shortest", str(out)], timeout, "vq mux")
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "nothing came out of the mux", retryable=False)
        return Result(files=(str(out),))

    def _thumbnail(self, src: Path, params: dict, timeout: float) -> Result:
        out = Path(params["out"])
        self._run(["-y", "-ss", str(params.get("at", 0.0)), "-i", str(src), "-frames:v", "1", "-vf", ",".join([*self._sdr(params), "scale=-2:'min(360,ih)'"]),
                   "-q:v", "3", str(out)], timeout, "thumbnail")
        return Result(files=(str(out),))
