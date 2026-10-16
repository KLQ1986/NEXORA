"""Recipes: what to do to each shot, in what order, with what tool and why (Visual Quality, design 2026-10-16 §3.1-3.2).

Steps come in a fixed order, because each assumes the ones before have run: the structure of the picture first (fields,
rate), then compression damage, then noise (on the source, where it is noise and not yet stretched by a grade), then
colour (the encoding's transform, then exposure and white balance), then stabilisation, sharpening, size and frame rate.

A step is only proposed when a defect calls for it or the operator asked for it, and only with a tool this machine has.
Screens and graphics are never denoised or sharpened; a still never has a temporal step.
"""
import hashlib
import math
from pathlib import Path

import numpy as np

from nexora.modules.visual_quality import measure as M

# Steps that can cost a picture more than they give; each must show on the shot's own frame that it does not make it less
# natural (NIQE) before it stays in a recipe.
RISKY = frozenset({"deblock", "deband", "denoise", "sharpen"})
ORDER = ("deinterlace", "ivtc", "constant_rate", "deblock", "restore", "remove", "deband", "denoise", "tonemap", "color_transform", "levels", "relight",
         "deflicker", "stabilise", "deblur", "sharpen", "upscale", "faces", "interpolate")
VERSION = "1"
# Real-ESRGAN works ×4: above this many pixels in the source its intermediate is too big to be worth it.
AI_PIXELS = 4_000_000
AI_MODEL = "realesrgan-x4plus"
RELIGHT_MIDDLE = 0.3       # a median luma below this ...
RELIGHT_TOP = 0.85         # ... under a 99th percentile above this calls for light where it is
DEBLUR_SEVERITY = 0.15     # less blurred than this, sharpening is enough (a model is still checked against sharpening)
DEBLUR_STILL_PIXELS = 24_000_000
DEBLUR_VIDEO_PIXELS = 1280 * 720   # NAFNet takes about 5 s a 720p frame here; a 4K frame about a minute
FACE_SIDES = (48, 400)     # pixels: smaller has too little to align on, larger is already detailed enough to lose by a redraw
TARGET_MIDTONE = 0.45


def exposure_balance(look: dict, *, content: str, parts: frozenset[str] = frozenset({"black", "white", "wb", "gamma", "saturation"})) -> dict | None:
    """Levels for a shot from its display measures: black and white points, white balance (half the cast, at most 7%),
    a midtone gamma towards a mid grey, a little colour for a dull picture. None when nothing is worth changing.
    A dark picture with bright highlights is taken for a low-key scene (night, a lamp) and only lifted a little."""
    p01, p50, p99 = look["luma_p01"], look["luma_p50"], look["luma_p99"]
    clip_hi, sat = look["clipped_high"], look["saturation"]
    params, why = {}, []
    black = 0.0
    # Lifted blacks are a dark end that never reaches black (log, haze, a flat grade), not a bright picture: a white card or
    # a high-key scene has a high darkest tone because it has no dark tones at all.
    if "black" in parts and 0.06 < p01 < 0.25 and p50 < 0.65:
        black = round(p01 * 0.7, 4); why.append(f"đen bị nâng ({p01:.2f})")
    white = 1.0
    if "white" in parts and p99 < 0.88 and clip_hi < 0.002:
        white = round(max(p99 + 0.03, 0.75), 4); why.append(f"sáng nhất chỉ tới {p99:.2f}")
    gains = [1.0, 1.0, 1.0]
    if "wb" in parts and content not in ("screen", "graphics"):
        cr, cb = look.get("cast_r", 1.0), look.get("cast_b", 1.0)
        if abs(cr - 1) > 0.06 or abs(cb - 1) > 0.06:
            gains = [min(1.07, max(0.93, (1.0 / cr) ** 0.5)), 1.0, min(1.07, max(0.93, (1.0 / cb) ** 0.5))]
            why.append(f"ám màu đỏ/lục {cr:.2f}, lam/lục {cb:.2f}")
    # Midtones after the new black and white points.
    mid = (p50 - black) / max(white - black, 1e-3)
    gamma = 1.0
    if "gamma" in parts and abs(mid - TARGET_MIDTONE) > 0.08 and 0.02 < mid < 0.98:
        gamma = math.log(mid) / math.log(TARGET_MIDTONE)
        low_key = mid < 0.25 and p99 > 0.9
        gamma = min(gamma, 1.15) if low_key else gamma
        gamma = round(min(1.4, max(0.75, gamma)), 3)
        why.append(("cảnh tối có vùng sáng: chỉ nâng nhẹ" if low_key else "trung tông lệch") + f" ({mid:.2f} → gamma {gamma})")
    saturation = 1.12 if "saturation" in parts and sat < 0.06 and content not in ("screen", "graphics") else 1.0
    if saturation != 1.0:
        why.append(f"màu nhạt ({sat:.2f})")
    if not why:
        return None
    params = {"black": [black] * 3, "white": [round(white / g, 4) for g in gains], "gamma": gamma, "saturation": saturation}
    return {"op": "levels", "tier": "ffmpeg", "params": params, "why": "; ".join(why)}


def levels_lut(params: dict, lut_dir: str | Path, *, size: int = 33) -> str:
    """The levels of a shot (black and white points per channel, gamma, saturation) baked into a 3D LUT, applied by `lut3d`
    at full depth. FFmpeg's own `colorlevels` gives black frames on 10-bit planar RGB and `eq` works in 8 bits, so neither is
    used for a 10-bit source. The same parameters always give the same file."""
    black = np.asarray(params.get("black", [0, 0, 0]), np.float64)
    white = np.asarray(params.get("white", [1, 1, 1]), np.float64)
    gamma, sat = float(params.get("gamma", 1.0)), float(params.get("saturation", 1.0))
    key = hashlib.sha1(np.concatenate([black, white, [gamma, sat, size]]).round(6).tobytes()).hexdigest()[:12]
    out = Path(lut_dir) / "levels" / f"levels_{key}.cube"
    if out.is_file():
        return str(out)
    g = np.linspace(0.0, 1.0, size)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")                 # .cube order: red changes fastest
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    x = np.clip((rgb - black) / np.maximum(white - black, 1e-6), 0.0, 1.0)
    if abs(gamma - 1.0) > 1e-6:
        x = np.power(x, 1.0 / gamma)
    if abs(sat - 1.0) > 1e-6:
        y = (x @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
        x = np.clip(y + (x - y) * sat, 0.0, 1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial")
    partial.write_text(f"TITLE \"NEXORA levels {key}\"\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n"
                       + "".join(f"{a:.6f} {c:.6f} {d:.6f}\n" for a, c, d in x))
    partial.replace(out)
    return str(out)


DENOISE_STRENGTHS = (1.0, 0.85, 0.7)
METHOD_NOISE_LIMIT = 1.0


def tune_denoise(render, sigma: float) -> tuple[float, float]:
    """The strength of a denoise for this picture, from its method noise: what the filter takes away (luma, 0..255) against
    the noise measured. Taking away more than the noise is taking texture: on a frame of foliage (0042) full strength took
    1.06–1.22 times the noise and cost SSIM 0.92 → 0.79; on flat footage (0059) it took 1.01. The first of
    `DENOISE_STRENGTHS` within `METHOD_NOISE_LIMIT` is kept, never under 0.7 (at 0.5 flat footage keeps most of its noise).
    Measured 2026-10-17 with noise σ 6, 12 and 25 added: every case comes out better than the noisy frame, foliage at σ 25
    by 3.6 dB instead of 2.4. `render(strength)` gives the frame (RGB, 0..1) with the denoise at that strength, None without."""
    base = M.luma(render(None))
    ratio = 0.0
    for strength in DENOISE_STRENGTHS:
        ratio = float((base - M.luma(render(strength))).std() * 255.0 / max(sigma, 0.1))
        if ratio <= METHOD_NOISE_LIMIT:
            return strength, round(ratio, 3)
    return DENOISE_STRENGTHS[-1], round(ratio, 3)


def plan_shot(shot: dict, *, profile: dict, colour: list[dict], have: set[str], options: dict) -> list[dict]:
    """The steps of one shot. `shot`: t_start, t_end, scores (display measures), defects (kinds with severity).
    `colour`: the colour steps of the source. `have`: the step tools at hand ("ffmpeg:hqdn3d", "apple_vt", "gyroflow")."""
    content = profile["content"]
    # A shot of flat graphics inside camera footage (an end card, a title) is treated as graphics.
    if content in ("camera", "ai") and shot.get("display", {}).get("flat_blocks", 0) > 0.3:
        content = "graphics"
    tech = profile["technical"]
    sev = {d["kind"]: d["severity"] for d in shot.get("defects", [])}
    camera_like = content in ("camera", "ai", "still")
    still = content == "still"
    steps: list[dict] = []
    if not still and str(tech.get("field_order") or "progressive") not in ("progressive", "unknown", "None", "") and "ffmpeg:bwdif" in have:
        steps.append({"op": "deinterlace", "tier": "ffmpeg", "params": {}, "why": f"xen kẽ dòng ({tech.get('field_order')})"})
    if not still and tech.get("variable_frame_rate") and "ffmpeg:fps" in have:
        fps = options.get("fps") or round(float(tech.get("nominal_frame_rate") or tech.get("frame_rate") or 30))
        steps.append({"op": "constant_rate", "tier": "ffmpeg", "params": {"fps": fps}, "why": "tốc độ khung thay đổi"})
    pixels = int(tech.get("width") or 0) * int(tech.get("height") or 0)
    # AI that makes detail up is offered for stills only, small enough, beside the classic step it must beat (the service checks).
    ai = still and "realesrgan" in have and 0 < pixels <= AI_PIXELS and options.get("ai", True)
    if sev.get("blocking", 0) > 0 and "ffmpeg:deblock" in have:
        classic = {"op": "deblock", "tier": "ffmpeg", "params": {}, "why": f"khối nén ({shot['scores']['blockiness']})"}
        if ai and sev["blocking"] >= 0.3:
            steps.append({"op": "restore", "tier": "realesrgan", "params": {"model": AI_MODEL}, "generative": True, "classic": classic,
                          "why": f"khối nén nặng ({shot['scores']['blockiness']}): phục hồi bằng Real-ESRGAN (AI, sinh chi tiết)"})
        else:
            steps.append(classic)
    if sev.get("banding", 0) > 0 and "ffmpeg:deband" in have:
        steps.append({"op": "deband", "tier": "ffmpeg", "params": {"threshold": round(0.02 + 0.02 * sev["banding"], 4), "range": 24}, "why": "dải màu"})
    if camera_like and sev.get("noise", 0) > 0 and options.get("denoise", True):
        sigma = float(shot["scores"]["noise"])
        if "apple_vt" in have and not still:
            strength = round(min(1.0, max(0.2, sigma / 12.0)), 2)
            steps.append({"op": "denoise", "tier": "apple_vt", "params": {"strength": strength, "sigma": sigma}, "why": f"nhiễu {sigma} (lọc theo thời gian)"})
        elif "ffmpeg:nlmeans" in have and still:
            steps.append({"op": "denoise", "tier": "ffmpeg", "params": {"sigma": sigma, "method": "nlmeans"}, "why": f"nhiễu {sigma}"})
        elif "ffmpeg:hqdn3d" in have:
            steps.append({"op": "denoise", "tier": "ffmpeg", "params": {"sigma": sigma}, "why": f"nhiễu {sigma} (lọc theo không gian và thời gian)"})
    steps += [dict(s) for s in colour]
    lv = exposure_balance(shot["display"], content=content) if options.get("exposure", True) else None
    if lv and "ffmpeg:lut3d" in have:
        if options.get("lut_dir"):
            lv["params"]["lut"] = levels_lut(lv["params"], options["lut_dir"])
        steps.append(lv)
    # A dark middle under bright parts (backlight, a window, a sunlit sky over shade): no single curve lifts the one without
    # clipping the other, so the shadows are lifted where they are. Checked by the service against leaving it to levels.
    disp = shot.get("display") or {}
    if camera_like and "local_tone" in have and options.get("relight", True) and disp.get("luma_p50", 1.0) < RELIGHT_MIDDLE and disp.get("luma_p99", 0.0) > RELIGHT_TOP:
        shadows = round(float(min(1.0, max(0.3, (RELIGHT_MIDDLE + 0.05 - disp["luma_p50"]) / 0.25))), 2)
        highlights = 0.5 if disp.get("clipped_high", 0.0) > 0.005 else 0.2
        steps.append({"op": "relight", "tier": "local_tone", "params": {"shadows": shadows, "highlights": highlights}, "classic": None,
                      "why": f"giữa tối ({disp['luma_p50']:.2f}) dưới phần sáng ({disp['luma_p99']:.2f}): nâng vùng tối tại chỗ"})
    if not still and sev.get("flicker", 0) > 0 and "ffmpeg:deflicker" in have:
        steps.append({"op": "deflicker", "tier": "ffmpeg", "params": {"size": 5}, "why": f"nhấp nháy {shot['scores']['flicker']}"})
    if not still and camera_like and sev.get("shake", 0) > 0.3 and options.get("stabilise", True):
        if "gyroflow" in have and tech.get("gyro"):
            steps.append({"op": "stabilise", "tier": "gyroflow", "params": {"smoothness": 0.5}, "why": f"rung {shot['scores']['shake']}px, có dữ liệu con quay"})
        elif "vidstab" in have:
            steps.append({"op": "stabilise", "tier": "vidstab", "params": {"smoothing": 15, "zoom": 0}, "why": f"rung {shot['scores']['shake']}px"})
    if camera_like and sev.get("soft", 0) > 0 and options.get("sharpen", True) and "ffmpeg:cas" in have:
        classic = {"op": "sharpen", "tier": "ffmpeg", "params": {"strength": round(0.15 + 0.2 * sev["soft"], 2)}, "why": f"mềm (độ nét {shot['scores']['sharpness']})"}
        # Blur that sharpening cannot undo is taken to a model, beside the sharpening it must beat: NAFNet here for stills and
        # video up to 720p; VRT on a rented GPU for larger video, only when the operator has let this recording leave the machine.
        if sev["soft"] >= DEBLUR_SEVERITY and options.get("deblur", True):
            if not still and options.get("allow_cloud") and "vrt_remote" in have:
                steps.append({"op": "deblur", "tier": "vrt_remote", "params": {}, "generative": True, "remote": True,
                              "why": f"mờ ({shot['scores']['sharpness']}): VRT trên GPU thuê, đã được phép gửi footage"})
            elif "nafnet" in have and (pixels <= (DEBLUR_STILL_PIXELS if still else DEBLUR_VIDEO_PIXELS)):
                steps.append({"op": "deblur", "tier": "nafnet", "params": {}, "generative": True, "classic": classic,
                              "why": f"mờ ({shot['scores']['sharpness']}): khử mờ bằng NAFNet (AI)"})
            else:
                steps.append({**classic, "why": classic["why"] + ("; khử mờ AI cho video lớn cần GPU thuê và sự cho phép gửi footage" if not still else "")})
        else:
            steps.append(classic)
    target_h = options.get("target_height")
    height = int(tech.get("display_height") or tech.get("height") or 0)
    if target_h and height and target_h > height * 1.2:
        factor = 2 if target_h <= height * 2.2 else 4
        classic = {"op": "upscale", "tier": "ffmpeg", "params": {"factor": factor}, "why": f"phóng ×{factor} tới {height * factor}p"}
        if "apple_sr" in have and not still and height <= 1080 and target_h >= height * 3:
            steps.append({"op": "upscale", "tier": "apple_vt", "params": {"factor": 4}, "why": f"phóng ×4 tới {height * 4}p"})
        elif ai and target_h <= height * 4:
            steps.append({"op": "upscale", "tier": "realesrgan", "params": {"height": int(target_h), "model": AI_MODEL}, "generative": True, "classic": classic,
                          "why": f"phóng tới {int(target_h)}p bằng Real-ESRGAN (AI, sinh chi tiết)"})
        else:
            steps.append(classic)
    # Faces of a still: offered where CodeFormer has something to give (a face small, or a picture noisy, soft or blocked), and
    # never where it would only redraw a large clean face; the service keeps it only if the faces measure more natural.
    faces = [f for f in shot.get("faces", []) if FACE_SIDES[0] <= min(f["box"][2], f["box"][3]) <= FACE_SIDES[1]]
    damaged = any(sev.get(k, 0) > 0 for k in ("noise", "soft", "blocking"))
    if still and faces and "faces" in have and options.get("faces", True) and (damaged or min(min(f["box"][2:]) for f in faces) < 160):
        steps.append({"op": "faces", "tier": "codeformer", "params": {"weight": 0.7}, "generative": True, "classic": None,
                      "why": f"{len(faces)} khuôn mặt: phục hồi bằng CodeFormer (AI, vẽ lại khuôn mặt)"})
    target_fps = options.get("target_fps")
    rate = float(tech.get("frame_rate") or 0)
    if not still and target_fps and rate and target_fps > rate * 1.2:
        tier = "apple_vt" if "apple_frc" in have else "ffmpeg"          # Apple's conversion, else motion-compensated minterpolate
        steps.append({"op": "interpolate", "tier": tier, "params": {"fps": target_fps}, "why": f"nội suy {rate:g} → {target_fps} khung/s"})
    return sorted(steps, key=lambda s: ORDER.index(s["op"]) if s["op"] in ORDER else 99)


def output_colour(profile: dict, colour: list[dict]) -> dict:
    """The colour description the result carries: Rec.709 once transformed, else what the source declared."""
    if any(s["op"] in ("tonemap", "color_transform") for s in colour):
        return {"color_primaries": "bt709", "color_transfer": "bt709", "color_space": "bt709"}
    t = profile["technical"]
    return {k: t.get(k) for k in ("color_primaries", "color_transfer", "color_space") if t.get(k)}
