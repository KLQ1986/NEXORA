"""Stills that neither Pillow nor FFmpeg read whole, made into a 16-bit TIFF for Visual Quality (design 2026-10-16, wave 3).

- HEIC/HEIF (iPhone, recent DJI): by macOS `sips`, which keeps the EXIF and the colour profile.
- RAW (DNG, CR2/CR3, NEF, ARW, RAF, ORF, RW2…): by LibRaw (`rawpy`), with the camera's white balance, no automatic
  brightening, into linear-free sRGB at 16 bits, so that exposure and colour are left to the recipe. Apple's own RAW engine
  (`sips`, Core Image) was tried first and does not open every DNG (it fails on the Osmo Action's, 2026-10-17); LibRaw does.

Measured on an M4: a 12-megapixel DNG in about 0.4 s, a HEIC in about 0.3 s.
"""
import shutil
import subprocess
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

HEIF_EXT = frozenset({".heic", ".heif", ".hif", ".avif"})
RAW_EXT = frozenset({".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".orf", ".rw2", ".pef", ".srw", ".x3f", ".3fr", ".iiq", ".erf", ".mos", ".gpr"})
DECODE_EXT = HEIF_EXT | RAW_EXT


class Stills(Adapter):
    def __init__(self, ffmpeg: str = "ffmpeg"):
        self._ffmpeg = ffmpeg

    def describe(self) -> Capability:
        return Capability(name="stills", operations=("decode",), runs="local")

    def available(self) -> bool:
        return True

    def environment(self) -> dict:
        try:
            import rawpy  # noqa: F401
            raw = True
        except ImportError:
            raw = False
        return {"available": True, "heif": bool(shutil.which("sips")) or bool(shutil.which(self._ffmpeg)), "raw": raw}

    def submit(self, request: Request) -> Result:
        if request.operation != "decode":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        src, out = Path(request.inputs["path"]), Path(request.params["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        ext = src.suffix.lower()
        if ext in RAW_EXT:
            info = self._raw(src, out)
        elif ext in HEIF_EXT:
            info = self._heif(src, out)
        else:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"{ext} is read directly, not decoded", retryable=False)
        if not out.is_file() or out.stat().st_size == 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"could not decode {src.name}", retryable=False)
        return Result(outputs={**self._tags(src), **info, "from": ext.lstrip(".")}, files=(str(out),))

    def _raw(self, src: Path, out: Path) -> dict:
        try:
            import rawpy
        except ImportError:
            raise AdapterError(ErrorCode.UNAVAILABLE, "RAW needs LibRaw (uv pip install rawpy)", retryable=False) from None
        try:
            with rawpy.imread(str(src)) as raw:
                rgb = raw.postprocess(output_bps=16, use_camera_wb=True, no_auto_bright=True, output_color=rawpy.ColorSpace.sRGB)
                white = int(raw.white_level)
        except Exception as e:                                                  # LibRaw's own errors, one class per cause
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"LibRaw could not read {src.name}: {e}", retryable=False) from None
        h, w = rgb.shape[:2]
        done = subprocess.run([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{w}x{h}",
                               "-i", "-", "-frames:v", "1", "-pix_fmt", "rgb48le", "-color_trc", "iec61966-2-1", "-color_primaries", "bt709", str(out)],
                              input=rgb.astype("<u2").tobytes(), capture_output=True)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"could not write the decoded RAW: {done.stderr.decode(errors='replace')[-200:]}", retryable=False)
        return {"raw": True, "bit_depth": max(10, white.bit_length()), "width": w, "height": h}

    def _heif(self, src: Path, out: Path) -> dict:
        if shutil.which("sips"):
            done = subprocess.run(["sips", "-s", "format", "tiff", str(src), "--out", str(out)], capture_output=True, text=True)
            if done.returncode == 0 and out.is_file():
                bits = self._sips(out).get("bitsPerSample")
                return {"raw": False, "bit_depth": int(bits) if bits and bits.isdigit() else 8}
        done = subprocess.run([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-frames:v", "1", "-pix_fmt", "rgb48le", str(out)],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"could not read {src.name}: {done.stderr.strip()[-200:]}", retryable=False)
        return {"raw": False, "bit_depth": 8}

    @staticmethod
    def _sips(path: Path, *keys: str) -> dict:
        if not shutil.which("sips"):
            return {}
        args = [a for k in (keys or ("bitsPerSample",)) for a in ("-g", k)]
        text = subprocess.run(["sips", *args, str(path)], capture_output=True, text=True).stdout
        return {k.strip(): v.strip() for k, _, v in (line.partition(":") for line in text.splitlines()[1:]) if v}

    def _tags(self, src: Path) -> dict:
        """The camera, as the original says (sips reads the metadata of RAW files it cannot render)."""
        tags = self._sips(src, "make", "model", "software", "profile")
        return {k: tags[k] for k in ("make", "model", "software", "profile") if tags.get(k)}
