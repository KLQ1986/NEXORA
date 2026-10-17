"""Matching a shot's colour to a reference: the grade that makes one picture's colours sit like another's.

For footage from different sources cut together (a DJI shot beside a phone's, stock, an AI clip): each is right on its own and
they still do not look like one film. The look of a picture is taken as the spread of its colours, not their average: the
pixels in OKLab are read along thirteen directions (lightness, the two colour axes and their mixes), at nineteen quantiles
each, with the quantiles of chroma, as in Merserk's Visual Enhancer (`color_analysis.cpp`, 2026). That catches what a white
balance cannot, highlights going cool while shadows go warm. The grade fitted to it is not a free mapping but the controls a
colourist would turn (exposure, contrast, shadows, highlights, temperature, tint, saturation), found by damped least squares
(Levenberg–Marquardt) and held near zero: the result can be read and changed by hand, and a reference whose content differs
(more sky, less foliage) moves the controls only as far as their bounds allow. Every control acts on each pixel alone, so the
grade is baked into a 3D LUT and applied like the levels, at the source's own depth.

Matching the whole spread is right only for two shots of the same scene. Between different scenes it copies the content: a café
under a blue sky matched to a close-up of yellow-green coconuts had its sky turned green and its temperature and highlights
driven to their bounds (2026-10-17, distance 9.4 → 6.2 only). So the default (`look`) matches what belongs to the camera and
not to the scene: the tone curve (lightness quantiles), the white balance read on the near-neutral pixels of each picture (the
least coloured fifth of its mid-tones: concrete, cloud, a white wall), and, lightly, saturation. `scene` matches the whole
spread, for shots of the same place.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

# The controls, their bounds and what a step of one means; all at 0 leave the picture as it is.
CONTROLS = ("exposure", "contrast", "shadows", "highlights", "temperature", "tint", "saturation")
LOW = np.array([-1.5, -0.4, -0.35, -0.35, -0.35, -0.25, -0.5])
HIGH = np.array([1.5, 0.4, 0.35, 0.35, 0.35, 0.25, 0.5])
# How hard the fit is held at zero: enough that a control the colours do not ask for stays put.
HOLD = 0.004
SAMPLES = 24_000

_DIRECTIONS = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 1, 1], [0, 1, -1], [1, 1, 0], [1, -1, 0], [1, 0, 1],
                        [1, 0, -1], [1, 1, 1], [1, 1, -1], [1, -1, 1], [1, -1, -1]], np.float64)
_DIRECTIONS /= np.linalg.norm(_DIRECTIONS, axis=1, keepdims=True)
_QUANTILES = np.array([0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.975, 0.99])
_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _encoded(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def oklab(rgb: np.ndarray) -> np.ndarray:
    """Display RGB (0..1, BT.709 primaries, sRGB-like curve) to OKLab, with a and b weighted 1.6 as lightness is."""
    lin = _linear(np.clip(rgb, 0.0, 1.0))
    lms = np.cbrt(lin @ np.array([[.4122214708, .5363325363, .0514459929], [.2119034982, .6806995451, .1073969566],
                                  [.0883024619, .2817188376, .6299787005]]).T)
    lab = lms @ np.array([[.2104542553, .7936177850, -.0040720468], [1.9779984951, -2.4285922050, .4505937099],
                          [.0259040371, .7827717662, -.8086757660]]).T
    return lab * np.array([1.0, 1.6, 1.6])


def features(rgb: np.ndarray) -> np.ndarray:
    """The spread of a picture's colours: quantiles along each direction in OKLab, and of chroma."""
    lab = oklab(rgb)
    along = lab @ _DIRECTIONS.T
    chroma = np.hypot(lab[:, 1], lab[:, 2])[:, None]
    return np.quantile(np.hstack([along, chroma]), _QUANTILES, axis=0).ravel()


NEUTRAL_SHARE = 0.2      # the least coloured fifth of the mid-tones is taken as what should be grey
NEUTRAL_CHROMA = 0.05   # the most colour (OKLab, a and b ×1.6) that pixels taken as grey may carry: a cast, not a thing
NEUTRAL_WEIGHT = 6.0     # the white balance against nineteen tone quantiles: one number each, so weighted up
CHROMA_WEIGHT = 0.4      # saturation follows the scene's content more than the camera's: weighted down


def neutrals(rgb: np.ndarray) -> np.ndarray | None:
    """Which pixels are taken as grey: the share of the mid-tones nearest the picture's cast (None when too few to trust).
    Nearest the cast, not least coloured: under a warm cast the least coloured pixels are the slightly blue things it has
    cancelled, and a match read on them found a third of a known shift of temperature. The cast is found by taking the share
    nearest the current estimate, three times over, from no cast."""
    lab = oklab(rgb)
    mid = (lab[:, 0] > 0.25) & (lab[:, 0] < 0.92)
    if mid.sum() < 500:
        return None
    ab, cast, chosen = lab[:, 1:], np.zeros(2), mid
    for _ in range(3):
        d = np.hypot(*(ab - cast).T)
        chosen = mid & (d <= np.quantile(d[mid], NEUTRAL_SHARE))
        cast = ab[chosen].mean(axis=0)
    # What is chosen must be nearly grey to be read as grey: in a frame of foliage the nearest share is a green that moves
    # with the scene, not with the light (a known warm shift was read as a quarter of itself there).
    return chosen if float(np.hypot(*cast)) <= NEUTRAL_CHROMA else None


def look(rgb: np.ndarray, grey: np.ndarray | None) -> np.ndarray:
    """What belongs to the camera rather than the scene: the tone curve, the white balance on `grey`, and saturation."""
    lab = oklab(rgb)
    tone = np.quantile(lab[:, 0], _QUANTILES)
    chroma = np.quantile(np.hypot(lab[:, 1], lab[:, 2]), _QUANTILES) * CHROMA_WEIGHT
    balance = lab[grey, 1:].mean(axis=0) * NEUTRAL_WEIGHT if grey is not None else np.zeros(2)
    return np.concatenate([tone, chroma, balance])


def grade(rgb: np.ndarray, c: np.ndarray | dict) -> np.ndarray:
    """The controls applied to display RGB (n×3, 0..1). White balance and exposure in linear light; the tone controls on the
    encoded values, each holding black, white and (for contrast) the middle where they are."""
    c = as_vector(c)
    exposure, contrast, shadows, highlights, temperature, tint, saturation = c
    lin = _linear(np.clip(rgb, 0.0, 1.0))
    gains = np.array([np.exp(temperature), np.exp(-tint), np.exp(-temperature)])
    gains /= gains @ _LUMA                                         # white balance moves colour, not brightness
    y = _encoded(lin * gains * 2.0 ** exposure)
    y = np.clip(y, 0.0, 1.0)
    y = y + 2.0 * contrast * y * (1 - y) * (2 * y - 1)            # an S around the middle (inverted below zero)
    y = y + 2.5 * shadows * y * (1 - y) ** 2                       # lifts or sinks the darks, black stays
    y = y + 2.5 * highlights * y ** 2 * (1 - y)                    # the lights, white stays
    luma = (y @ _LUMA)[:, None]
    y = luma + (y - luma) * (1.0 + saturation)
    return np.clip(y, 0.0, 1.0)


def as_vector(c: np.ndarray | dict) -> np.ndarray:
    if isinstance(c, dict):
        return np.array([float(c.get(k, 0.0)) for k in CONTROLS])
    return np.asarray(c, np.float64)


def _sample(rgb: np.ndarray, n: int = SAMPLES, seed: int = 7) -> np.ndarray:
    rgb = np.asarray(rgb, np.float64).reshape(-1, 3)
    if len(rgb) > n:
        rgb = rgb[np.random.default_rng(seed).choice(len(rgb), n, replace=False)]
    return rgb


def distance(a: np.ndarray, b: np.ndarray) -> float:
    """How far two pictures' colours sit apart: the root mean square of their features' difference (OKLab units ×100)."""
    return float(np.sqrt(np.mean((features(_sample(a)) - features(_sample(b))) ** 2)) * 100)


MODES = ("look", "scene")


def fit(source: np.ndarray, reference: np.ndarray, *, mode: str = "look", iterations: int = 40) -> dict:
    """The controls that bring `source`'s colours to `reference`'s (both display RGB, any shape ending in 3, 0..1), with the
    distance before and after. Levenberg–Marquardt on a numeric Jacobian, every control held within its bounds. `look` matches
    tone, white balance and saturation (any two scenes); `scene` the whole spread of colours (two shots of one place). Without
    grey enough in both pictures the white balance is left alone."""
    if mode not in MODES:
        raise ValueError(f"mode is one of {MODES}")
    src, ref = _sample(source), _sample(reference)
    grey_src = None
    if mode == "scene":
        measure, target = features, features(ref)
    else:
        grey_src, grey_ref = neutrals(src), neutrals(ref)
        if grey_src is None or grey_ref is None:
            grey_src = grey_ref = None
        measure, target = (lambda x: look(x, grey_src)), look(ref, grey_ref)
    scale = 1.0 / np.sqrt(target.size)

    def residual(v: np.ndarray) -> np.ndarray:
        return np.concatenate([(measure(grade(src, v)) - target) * scale, v * HOLD])

    v = np.zeros(len(CONTROLS))
    err = residual(v)
    score, damping = float(err @ err), 1e-3
    before = float(np.sqrt(np.mean(((err[:target.size]) / scale) ** 2)) * 100)
    for _ in range(iterations):
        jac = np.empty((err.size, v.size))
        for j in range(v.size):
            step = 2e-3 if v[j] + 2e-3 <= HIGH[j] else -2e-3
            trial = v.copy()
            trial[j] += step
            jac[:, j] = (residual(trial) - err) / step
        normal, gradient = jac.T @ jac, -jac.T @ err
        for _attempt in range(8):
            delta = np.linalg.solve(normal + damping * np.diag(np.diag(normal) + 1e-9), gradient)
            candidate = np.clip(v + np.clip(delta, -0.35, 0.35), LOW, HIGH)
            cand_err = residual(candidate)
            cand_score = float(cand_err @ cand_err)
            if cand_score < score:
                gain, v, err, score = score - cand_score, candidate, cand_err, cand_score
                damping = max(1e-9, damping * 0.3)
                break
            damping *= 4
        else:
            break
        if gain < 1e-10:
            break
    after = float(np.sqrt(np.mean((err[:target.size] / scale) ** 2)) * 100)
    pinned = [k for k, x, lo, hi in zip(CONTROLS, v, LOW, HIGH) if x <= lo + 1e-3 or x >= hi - 1e-3]
    # A match that had to push controls to their ends, or closed little of the gap, is reaching for what a grade cannot give
    # (the reference's content, not its look): said, so the operator looks before approving.
    doubtful = len(pinned) >= 2 or (before > 1.0 and after > 0.5 * before)
    return {"controls": {k: round(float(x), 4) for k, x in zip(CONTROLS, v)}, "before": round(before, 3), "after": round(after, 3),
            "mode": mode, "pinned": pinned, "doubtful": doubtful, "balanced": mode == "scene" or grey_src is not None}


def bake(controls: dict, lut_dir: str | Path, *, amount: float = 1.0, size: int = 33) -> str:
    """The grade (its controls times `amount`) as a 3D LUT for `lut3d`. The same numbers always give the same file."""
    v = as_vector(controls) * float(amount)
    key = hashlib.sha1(np.concatenate([v, [size]]).round(5).tobytes()).hexdigest()[:12]
    out = Path(lut_dir) / "match" / f"match_{key}.cube"
    if out.is_file():
        return str(out)
    g = np.linspace(0.0, 1.0, size)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")                 # .cube order: red changes fastest
    x = grade(np.stack([r, gg, b], -1).reshape(-1, 3), v)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial")
    partial.write_text(f"TITLE \"NEXORA match {key}\"\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n"
                       + "".join(f"{a:.6f} {c:.6f} {d:.6f}\n" for a, c, d in x))
    partial.replace(out)
    return str(out)
