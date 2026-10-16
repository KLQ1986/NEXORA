"""The Source Profile and the content type of a subject (Visual Quality, design 2026-10-16 §3.1: SourceProfiler, ContentClassifier).

What the file declares (through the `ffprobe` adapter, or Pillow for a still) and what its picture measures (frames drawn
through the `ffmpeg` adapter), put side by side: the colour encoding is identified from both (`registry.identify`), and
where they disagree it is said. The content type (camera, screen, graphics, AI-generated, still) decides which steps a
recipe may take.
"""
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, Request
from nexora.modules.visual_quality import measure as M
from nexora.modules.visual_quality.registry import identify

VERSION = "1"
STILL_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif", ".dng"})
AI_HINTS = re.compile(r"runway|pika|kling|sora|luma|dream ?machine|hailuo|minimax|veo|wan2|hunyuan|cogvideo|ltx|stable video|gen-?\d|svd", re.I)
SCREEN_HINTS = re.compile(r"screen|obs|quicktime player|xsplit|shadowplay|bandicam|camtasia", re.I)


def _rgb(path: str | Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(ImageOps.exif_transpose(im).convert("RGB"), np.float32) / 255.0


def still_technical(path: Path) -> dict:
    """What a still says about itself: size, mode, the camera, orientation, its colour profile."""
    with Image.open(path) as im:
        exif = im.getexif()
        icc = im.info.get("icc_profile")
        icc_name = None
        if icc:
            try:
                from PIL import ImageCms
                import io
                icc_name = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
            except Exception:
                icc_name = "ICC (không đọc được tên)"
        bits = {"1": 1, "L": 8, "P": 8, "RGB": 8, "RGBA": 8, "CMYK": 8, "I;16": 16, "I;16B": 16, "I": 32, "F": 32}.get(im.mode, 8)
        return {"kind": "still", "container": (im.format or path.suffix.lstrip(".")).lower(), "width": im.width, "height": im.height,
                "display_width": im.width, "display_height": im.height, "bit_depth": bits, "mode": im.mode,
                "make": exif.get(271), "model": exif.get(272), "device": " ".join(str(v) for v in (exif.get(271), exif.get(272)) if v) or None,
                "software": exif.get(305), "orientation_tag": exif.get(274), "icc": icc_name,
                "color_transfer": "iec61966-2-1" if (icc_name or "").lower().startswith("srgb") or not icc_name else None,
                "duration": 0.0, "has_audio": False}


def content_type(technical: dict, looks: list[M.Look], *, path: Path) -> tuple[str, list[str]]:
    """camera, screen, graphics, ai, still; and why."""
    words = " ".join(str(technical.get(k) or "") for k in ("encoder", "device", "software", "comment")) + " " + path.name
    if technical.get("kind") == "still":
        return "still", ["ảnh tĩnh"]
    if AI_HINTS.search(words):
        return "ai", [f"metadata/tên file gợi ý video sinh bằng AI ({AI_HINTS.search(words).group(0)})"]
    flat = float(np.median([lk.flat_blocks for lk in looks])) if looks else 0.0
    noise = float(np.median([lk.noise for lk in looks])) if looks else 0.0
    if SCREEN_HINTS.search(words) or (flat > 0.35 and noise < 0.4):
        return "screen", [f"{flat:.0%} khối 8×8 phẳng tuyệt đối, nhiễu {noise:.2f}: quay màn hình hoặc đồ hoạ"]
    if flat > 0.12 and noise < 0.6:
        return "graphics", [f"{flat:.0%} khối phẳng, gần như không nhiễu: hoạt hình hoặc đồ hoạ"]
    return "camera", [f"nhiễu {noise:.2f}, {flat:.0%} khối phẳng: footage máy quay"]


class SourceProfiler:
    def __init__(self, adapters: AdapterRegistry, work_dir: str | Path):
        self._adapters, self._work = adapters, Path(work_dir)

    def sample(self, path: Path, *, duration: float, subject: str, count: int = 24, width: int = 960, filters: list[str] | None = None,
               t_in: float | None = None, seconds: float | None = None, fps: float | None = None, tag: str = "sample") -> list[np.ndarray]:
        """Frames of a video, `count` spread over it (or a burst at `fps` from `t_in` for `seconds`), as RGB arrays."""
        out = self._work / subject / tag
        shutil.rmtree(out, ignore_errors=True)
        rate = fps or max(0.05, min(4.0, count / max(duration, 0.5)))
        params = {"out_dir": str(out), "fps": rate, "width": width, "quality": 2, "filters": filters or []}
        if t_in is not None:
            params["t_in"] = max(0.0, t_in)
        if seconds:
            params["seconds"] = seconds
        frames = self._adapters.submit("ffmpeg", Request("frames", inputs={"path": str(path)}, params=params)).outputs["frames"]
        try:
            return [_rgb(f) for f in frames]
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def profile(self, path: str | Path, *, subject: str) -> dict:
        """The Source Profile of a file: declared, measured, identified, with warnings."""
        path = Path(path)
        is_still = path.suffix.lower() in STILL_EXT
        if is_still:
            technical = still_technical(path)
            frames = [_rgb(path)]
        else:
            probed = self._adapters.submit("ffprobe", Request("probe", inputs={"path": str(path)})).outputs
            technical = {"kind": "video", **probed}
            frames = self.sample(path, duration=float(technical.get("duration") or 0.0), subject=subject)
        depth = int(technical.get("bit_depth") or 8)
        looks = [M.look(f, depth=depth) for f in frames]
        if not looks:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"no picture could be read from {path.name}")
        med = {k: float(np.median([getattr(lk, k) for lk in looks])) for k in M.Look.__dataclass_fields__}
        match = identify(technical, contrast=med["contrast"], saturation=med["saturation"])
        kind, kind_why = content_type(technical, looks, path=path)
        warnings = list(match.warnings)
        height = int(technical.get("display_height") or technical.get("height") or 0)
        if technical.get("variable_frame_rate"):
            warnings.append(f"tốc độ khung thay đổi (khai {technical.get('nominal_frame_rate')}, trung bình {technical.get('frame_rate')}): sẽ đổi về tốc độ cố định")
        if str(technical.get("field_order") or "progressive") not in ("progressive", "unknown", "None", ""):
            warnings.append(f"xen kẽ dòng ({technical.get('field_order')}): sẽ khử xen kẽ")
        if height and height < 1080 and kind != "screen":
            warnings.append(f"độ phân giải thấp ({technical.get('display_width')}×{height})")
        apparent = None
        if not is_still and height >= 1440:
            full = self._still(path, t=float(technical.get("duration") or 0.0) / 2, subject=subject)
            if full is not None:
                h, w = full.shape[:2]
                crop = full[h // 2 - 384:h // 2 + 384, w // 2 - 384:w // 2 + 384]
                apparent = round(M.detail_share(M.luma(crop)), 5)
                if apparent < 0.0006:
                    warnings.append(f"độ chi tiết ở độ phân giải gốc rất thấp ({apparent}): có thể là bản phóng to từ nguồn nhỏ hơn")
        return {"version": VERSION, "path": str(path), "technical": technical, "content": kind, "content_why": kind_why,
                "measured": {k: round(v, 5) for k, v in med.items()}, "apparent_detail": apparent,
                "encoding": match.encoding.key if match.encoding else None, "encoding_name": match.encoding.name if match.encoding else None,
                "encoding_confidence": match.confidence, "encoding_why": match.why, "warnings": warnings, "frames_measured": len(looks)}

    def _still(self, path: Path, *, t: float, subject: str, filters: list[str] | None = None, width: int | None = None) -> np.ndarray | None:
        out = self._work / subject / f"still_{t:.2f}.png"
        try:
            self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(path)}, params={
                "kind": "still", "t_in": max(0.0, t), "out": str(out), "filters": filters or [], **({"width": width} if width else {})}))
            return _rgb(out)
        except AdapterError:
            return None
        finally:
            out.unlink(missing_ok=True)
