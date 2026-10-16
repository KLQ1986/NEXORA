"""Temporal QA and before/after measures (Visual Quality, design 2026-10-16 §3.1: TemporalQA).

A recipe is judged on frames in a row, before and after, not on one frame: a filter that looks fine on a still can make a
shot flicker, its colour drift, or its texture crawl. Each check compares after with before, so a source's own flicker is
not blamed on the recipe. The verdict is "pass", "warn" (shown to the operator) or "fail" (the recipe is not approved
automatically).
"""
import numpy as np

from nexora.modules.visual_quality import measure as M
from nexora.modules.visual_quality.assess import niqe_of
from nexora.third_party.basicsr.metrics import psnr, ssim

VERSION = "2"


def _chroma_series(frames: list[np.ndarray]) -> np.ndarray:
    return np.array([[float((f[..., 0] - f[..., 1]).mean()), float((f[..., 2] - f[..., 1]).mean())] for f in frames])


def _crawl(frames: list[np.ndarray]) -> float:
    """Mean absolute change between frames in a row, on luma, 0..255: texture that moves on its own raises it."""
    if len(frames) < 2:
        return 0.0
    y = [M.luma(f) for f in frames]
    return float(np.mean([np.abs(a - b).mean() for a, b in zip(y, y[1:])]) * 255.0)


def _ranks(y: np.ndarray) -> np.ndarray:
    """Luma put through its own histogram equalisation: what is left is the order of brightness, which no tone curve changes."""
    flat = y.ravel()
    order = np.argsort(flat, kind="stable")
    out = np.empty_like(flat)
    out[order] = np.linspace(0.0, 255.0, flat.size)
    return out.reshape(y.shape)


def _structure(a: np.ndarray, b: np.ndarray) -> float:
    """SSIM of the two pictures after each is equalised: whether it is the same picture, whatever a grade (a LUT, a gamma,
    levels) did to its tones. A frame turned black, broken, blurred or redrawn still scores low."""
    if a.shape != b.shape:
        return 0.0
    return ssim(_ranks(M.luma(a)), _ranks(M.luma(b)))


POINTWISE = frozenset({"color_transform", "tonemap", "levels"})
# Frames are compared for motion at this width, sampled cubically. Measured (2026-10-17) on a pan over texture: the source
# predicts itself to 0.70 (0..255), a grade ×1.1 to 0.77; shimmer added each frame reads 4.33, texture that boils from frame to
# frame 3.37, a stain that does not follow the pan 2.25. At 240 wide the source alone read 2.4, too close to them.
FLOW_WIDTH = 480
FLOW_LEVELS = 3
FLOW_WINDOW = 9


def _down(y: np.ndarray) -> np.ndarray:
    h, w = (y.shape[0] // 2) * 2, (y.shape[1] // 2) * 2
    return y[:h, :w].reshape(h // 2, 2, w // 2, 2).mean((1, 3))


def _warp(y: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """`y` sampled at each pixel moved by (u, v): the picture as the motion says it is one frame on."""
    from scipy.ndimage import map_coordinates
    h, w = y.shape
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    return map_coordinates(y, [gy + v, gx + u], order=3, mode="nearest")


def flow(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Dense motion from luma `a` to luma `b` (pixels): pyramidal Lucas–Kanade, coarse to fine, two refinements a level."""
    from scipy.ndimage import uniform_filter, zoom
    pa, pb = [a * 255.0], [b * 255.0]                       # in code values, where gradients are large enough to solve on
    for _ in range(FLOW_LEVELS - 1):
        if min(pa[-1].shape) < 24:
            break
        pa.append(_down(pa[-1]))
        pb.append(_down(pb[-1]))
    u = np.zeros_like(pa[-1])
    v = np.zeros_like(pa[-1])
    for level in range(len(pa) - 1, -1, -1):
        A, B = pa[level], pb[level]
        if u.shape != A.shape:
            u = zoom(u, (A.shape[0] / u.shape[0], A.shape[1] / u.shape[1]), order=1) * 2.0
            v = zoom(v, (A.shape[0] / v.shape[0], A.shape[1] / v.shape[1]), order=1) * 2.0
            u, v = u[:A.shape[0], :A.shape[1]], v[:A.shape[0], :A.shape[1]]
        iy, ix = np.gradient(A)
        sxx, syy, sxy = (uniform_filter(q, FLOW_WINDOW) for q in (ix * ix, iy * iy, ix * iy))
        det = sxx * syy - sxy * sxy
        ok = det > 1e-6
        for _ in range(2):
            it = _warp(B, u, v) - A
            sxt, syt = uniform_filter(ix * it, FLOW_WINDOW), uniform_filter(iy * it, FLOW_WINDOW)
            du = np.where(ok, (-syy * sxt + sxy * syt) / np.where(ok, det, 1), 0.0)
            dv = np.where(ok, (sxy * sxt - sxx * syt) / np.where(ok, det, 1), 0.0)
            u, v = u + np.clip(du, -2, 2), v + np.clip(dv, -2, 2)
    return u.astype(np.float32), v.astype(np.float32)


def _small_luma(f: np.ndarray) -> np.ndarray:
    y = M.luma(f)
    k = max(1, y.shape[1] // FLOW_WIDTH)
    h, w = (y.shape[0] // k) * k, (y.shape[1] // k) * k
    return y[:h, :w].reshape(h // k, k, w // k, k).mean((1, 3)).astype(np.float32)


def warp_error(before: list[np.ndarray], after: list[np.ndarray]) -> tuple[float, float]:
    """How far each picture strays from where the source's own motion says it should be, before and after (luma, 0..255).

    The motion is measured once, on the source; each next frame is predicted from the one before by it, in both the source
    and the result. A recipe that is steady from frame to frame (a grade, a temporal denoise) keeps the result as predictable
    as the source; one that redraws each frame on its own (an AI working frame by frame, a texture that shimmers) does not.
    The worst tenth of pixels, where things come into view or the motion is unclear, is left out of both."""
    eb, ea = [], []
    for (b0, b1), (a0, a1) in zip(zip(before, before[1:]), zip(after, after[1:])):
        yb0, yb1, ya0, ya1 = (_small_luma(f) for f in (b0, b1, a0, a1))
        if ya0.shape != yb0.shape:
            continue
        u, v = flow(yb1, yb0)
        rb, ra = np.abs(_warp(yb0, u, v) - yb1), np.abs(_warp(ya0, u, v) - ya1)
        keep = rb <= np.quantile(rb, 0.9)
        eb.append(float(rb[keep].mean() * 255.0))
        ea.append(float(ra[keep].mean() * 255.0))
    return (float(np.mean(eb)), float(np.mean(ea))) if eb else (0.0, 0.0)


def compare(before: list[np.ndarray], after: list[np.ndarray], *, colour_changed: bool, ops: list[str] | None = None) -> dict:
    """Measures of a stretch before and after a recipe, and the verdict.

    A recipe of pointwise steps only (a LUT, levels, a tone map) maps each pixel the same way in every frame: it cannot make
    flicker, drift or crawl, it can only scale what the shot already has by how much it raises contrast and colour. Its
    temporal measures are therefore held against the before ones times that gain, so that a grade of a panning shot is not
    blamed for the pan."""
    n = min(len(before), len(after))
    before, after = before[:n], after[:n]
    if n == 0:
        return {"verdict": "fail", "reasons": ["không đọc được khung nào"], "metrics": {}}
    mid = n // 2
    fb, fa = M.flicker([float(M.luma(f).mean()) for f in before]), M.flicker([float(M.luma(f).mean()) for f in after])
    cb, ca = _chroma_series(before), _chroma_series(after)
    drift_b, drift_a = float(cb.std(0).max() * 255) if n > 2 else 0.0, float(ca.std(0).max() * 255) if n > 2 else 0.0
    crawl_b, crawl_a = _crawl(before), _crawl(after)
    struct = _structure(before[mid], after[mid])
    nb, na = niqe_of(before[mid]), niqe_of(after[mid])
    lb, la = M.look(before[mid]), M.look(after[mid])
    pointwise = bool(ops) and set(ops) <= POINTWISE
    gain_l = gain_c = 1.0
    if pointwise:
        gain_l = float(M.luma(after[mid]).std() / max(M.luma(before[mid]).std(), 1e-4))
        spread = lambda f: float(np.std(np.stack([f[..., 0] - f[..., 1], f[..., 2] - f[..., 1]])))
        gain_c = spread(after[mid]) / max(spread(before[mid]), 1e-4)
    metrics = {"flicker": (round(fb, 3), round(fa, 3)), "colour_drift": (round(drift_b, 3), round(drift_a, 3)),
               "crawl": (round(crawl_b, 3), round(crawl_a, 3)), "structure": (1.0, round(struct, 4)),
               "niqe": (None if nb is None else round(nb, 3), None if na is None else round(na, 3)),
               "exposure": (round(lb.luma_p50, 3), round(la.luma_p50, 3)), "contrast": (round(lb.contrast, 3), round(la.contrast, 3)),
               "saturation": (round(lb.saturation, 3), round(la.saturation, 3)), "clipped_high": (round(lb.clipped_high, 4), round(la.clipped_high, 4)),
               "noise": (round(lb.noise, 3), round(la.noise, 3)), "sharpness": (round(lb.sharpness, 1), round(la.sharpness, 1))}
    if not colour_changed:
        metrics["psnr"] = (None, round(psnr(before[mid] * 255, after[mid] * 255), 2))
    wb, wa = warp_error(before, after) if n > 2 else (0.0, 0.0)
    metrics["warp_error"] = (round(wb, 3), round(wa, 3))
    reasons_fail, reasons_warn = [], []
    metrics["gain"] = (1.0, round(gain_l, 3)) if pointwise else (None, None)
    if fa > fb * gain_l * 1.3 + 0.3:
        reasons_fail.append(f"làm nhấp nháy hơn ({fb:.2f} → {fa:.2f})")
    if drift_a > drift_b * gain_c * 1.5 + 0.5:
        reasons_fail.append(f"màu trôi theo thời gian ({drift_b:.2f} → {drift_a:.2f})")
    if crawl_a > crawl_b * gain_l * 1.25 + 0.3:
        reasons_warn.append(f"texture chuyển động nhiều hơn giữa các khung ({crawl_b:.2f} → {crawl_a:.2f})")
    # Against the source's own predictability, scaled by the contrast a grade adds (a brighter picture strays further in units).
    if n > 2 and wa > wb * max(gain_l, 1.0) * 2.0 + 2.0:
        reasons_fail.append(f"hình không theo chuyển động của nguồn, từng khung tự vẽ lại (lệch theo optical flow {wb:.2f} → {wa:.2f})")
    elif n > 2 and wa > wb * max(gain_l, 1.0) * 1.3 + 0.5:
        reasons_warn.append(f"hình kém ổn định theo chuyển động (lệch theo optical flow {wb:.2f} → {wa:.2f})")
    if struct < 0.80:
        reasons_fail.append(f"hình bị thay đổi cấu trúc (SSIM chuẩn hoá {struct:.2f})")
    elif struct < 0.9:
        reasons_warn.append(f"cấu trúc hình đổi đáng kể (SSIM chuẩn hoá {struct:.2f})")
    if nb is not None and na is not None and na > nb + 1.0:
        reasons_warn.append(f"kém tự nhiên hơn (NIQE {nb:.2f} → {na:.2f})")
    if la.clipped_high > lb.clipped_high + 0.01:
        reasons_warn.append(f"cháy sáng thêm ({lb.clipped_high:.1%} → {la.clipped_high:.1%})")
    verdict = "fail" if reasons_fail else "warn" if reasons_warn else "pass"
    return {"verdict": verdict, "reasons": reasons_fail + reasons_warn, "metrics": metrics}
