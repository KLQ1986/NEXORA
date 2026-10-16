"""What one picture looks like, measured (Visual Quality, design 2026-10-16 §3.1). Numbers, not words: the planner and the
defect map read them. Every measure works on an RGB array in [0, 1] of any size; frames are measured at about 960 wide.

These are Visual Quality's own measures, so that the engine runs on any file without Video Intelligence; where Video
Intelligence has measured a recording already, the service may use its values instead.
"""
from dataclasses import asdict, dataclass

import numpy as np
from scipy.ndimage import convolve, uniform_filter

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


@dataclass(frozen=True)
class Look:
    luma_mean: float          # 0..1
    luma_p01: float
    luma_p50: float
    luma_p99: float
    contrast: float           # p95 - p05 of luma
    saturation: float         # mean chroma (max - min of RGB)
    clipped_high: float       # share of pixels at the top of the range
    clipped_low: float        # share at the bottom
    noise: float              # sigma of sensor noise, 0..255 scale (Immerkær)
    sharpness: float          # variance of the Laplacian of luma, 0..255 scale
    detail: float             # share of energy above half the frame's frequency band: low on an upscaled or soft picture
    blockiness: float         # how much stronger the 8×8 block edges are than the rest (1 = none)
    banding: float            # share of smooth area whose gradient comes in steps
    flat_blocks: float        # share of 8×8 blocks with no variation at all (screens, graphics)
    cast_r: float             # white balance: red / green of near-neutral pixels
    cast_b: float             # blue / green


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., :3] @ LUMA


def noise_sigma(y: np.ndarray) -> float:
    """Immerkær's fast noise estimate: the response to a mask that cancels edges and smooth slopes, on 0..255 luma."""
    m = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    r = np.abs(convolve(y * 255.0, m, mode="reflect"))
    h, w = y.shape
    return float(np.sqrt(np.pi / 2) * r[1:-1, 1:-1].sum() / (6.0 * (w - 2) * (h - 2)))


def laplacian_variance(y: np.ndarray) -> float:
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], np.float32)
    return float(convolve(y * 255.0, k, mode="reflect").var())


def detail_share(y: np.ndarray) -> float:
    """Of the picture's (non-DC) spectral energy, the share in the upper half of frequencies. A frame enlarged from half its
    size has almost none there; a sharp native frame has a fair amount."""
    f = np.abs(np.fft.rfft2(y - y.mean())) ** 2
    h, w = y.shape
    fy = np.abs(np.fft.fftfreq(h))[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    r = np.maximum(fy, fx)                                       # 0..0.5
    total = f.sum() + 1e-12
    return float(f[r > 0.25].sum() / total)


def blockiness(y: np.ndarray, n: int = 8) -> float:
    """Mean absolute step across 8-pixel block borders over the mean step elsewhere: compression leaves visible block
    edges. Near 1 on clean footage, well above on a hard-compressed one."""
    dx = np.abs(np.diff(y, axis=1))
    dy = np.abs(np.diff(y, axis=0))
    col = np.arange(dx.shape[1])
    row = np.arange(dy.shape[0])
    on_x, on_y = (col % n) == n - 1, (row % n) == n - 1
    border = np.concatenate([dx[:, on_x].ravel(), dy[on_y, :].ravel()])
    inner = np.concatenate([dx[:, ~on_x].ravel(), dy[~on_y, :].ravel()])
    return float((border.mean() + 1e-6) / (inner.mean() + 1e-6))


def banding(y: np.ndarray, *, depth: int = 8) -> float:
    """In smooth regions (little local variance), the share whose change happens in discrete jumps of one code value or
    more with flat runs in between, the look of a sky in steps. Measured on 8-bit frames it says nothing of a source with
    more bits, which is processed at its own depth: `depth` above 8 gives 0."""
    if depth > 8:
        return 0.0
    q = np.round(y * 255.0)
    local = uniform_filter(y, 9)
    var = uniform_filter(y * y, 9) - local * local
    smooth = var < (1.5 / 255.0) ** 2
    if smooth.mean() < 0.02:
        return 0.0
    dx = np.diff(q, axis=1)
    sm = smooth[:, 1:] & smooth[:, :-1]
    steps = (np.abs(dx) >= 1) & sm
    flat = (dx == 0) & sm
    # Banding: many flat runs broken by single-code steps, and almost no in-between values (dithered noise would give them).
    if flat.sum() == 0:
        return 0.0
    return float(min(1.0, steps.sum() / max(1, sm.sum()) * 8.0) * (flat.sum() / max(1, sm.sum())))


def flat_blocks(rgb: np.ndarray, n: int = 8) -> float:
    h, w = rgb.shape[0] // n * n, rgb.shape[1] // n * n
    b = rgb[:h, :w].reshape(h // n, n, w // n, n, -1)
    rng = b.max(axis=(1, 3)) - b.min(axis=(1, 3))
    return float((rng.max(-1) < 1.0 / 255.0).mean())


def cast(rgb: np.ndarray) -> tuple[float, float]:
    """Red/green and blue/green of near-neutral, mid-bright pixels: 1, 1 when white is white."""
    # Relative chroma, so that a grey pushed warm by a cast is still taken for grey; the least coloured fifth of the
    # mid-bright pixels stands for white (a scene of leaves has few true greys, and their colour must not be taken for it).
    mx, mn = rgb.max(-1), rgb.min(-1)
    y = luma(rgb)
    mid = (y > 0.15) & (y < 0.92)
    if mid.mean() < 0.01:
        return 1.0, 1.0
    rel = (mx - mn) / np.maximum(mx, 1e-3)
    cut = np.percentile(rel[mid], 20)
    neutral = mid & (rel <= max(cut, 0.02)) & (rel < 0.25)
    if neutral.sum() < 50:
        return 1.0, 1.0
    p = rgb[neutral]
    g = max(float(p[:, 1].mean()), 1e-4)
    return float(p[:, 0].mean() / g), float(p[:, 2].mean() / g)


def look(rgb: np.ndarray, *, depth: int = 8) -> Look:
    rgb = np.clip(np.asarray(rgb, np.float32), 0, 1)
    y = luma(rgb)
    p = np.percentile(y, [1, 5, 50, 95, 99])
    cr, cb = cast(rgb)
    return Look(luma_mean=float(y.mean()), luma_p01=float(p[0]), luma_p50=float(p[2]), luma_p99=float(p[4]), contrast=float(p[3] - p[1]),
                saturation=float((rgb.max(-1) - rgb.min(-1)).mean()), clipped_high=float((y > 0.985).mean()), clipped_low=float((y < 0.015).mean()),
                noise=noise_sigma(y), sharpness=laplacian_variance(y), detail=detail_share(y), blockiness=blockiness(y), banding=banding(y, depth=depth),
                flat_blocks=flat_blocks(rgb), cast_r=cr, cast_b=cb)


def as_dict(lk: Look) -> dict:
    return {k: round(v, 5) for k, v in asdict(lk).items()}


def flicker(means: list[float]) -> float:
    """How much the brightness jumps from frame to frame beyond its slow drift: the standard deviation of the luma series
    minus its running mean, in 0..255. A steady shot is under 0.5; a flickering one is several."""
    m = np.asarray(means, np.float64) * 255.0
    if len(m) < 5:
        return 0.0
    k = min(9, len(m) // 2 * 2 + 1)
    trend = np.convolve(np.pad(m, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
    return float(np.std(m - trend))


def shake(frames: list[np.ndarray]) -> float:
    """Jitter of the camera: the frame-to-frame global shift (by phase correlation on luma) minus its smooth path, in
    pixels at the measured size. A tripod is near 0; walking handheld several."""
    if len(frames) < 4:
        return 0.0
    shifts = [(0.0, 0.0)]
    for a, b in zip(frames, frames[1:]):
        fa, fb = np.fft.fft2(luma(a)), np.fft.fft2(luma(b))
        r = fa * np.conj(fb)
        r /= np.abs(r) + 1e-9
        c = np.abs(np.fft.ifft2(r))
        dy, dx = np.unravel_index(np.argmax(c), c.shape)
        h, w = c.shape
        shifts.append((float(dx if dx < w // 2 else dx - w), float(dy if dy < h // 2 else dy - h)))
    path = np.cumsum(np.asarray(shifts), axis=0)
    k = min(7, len(path) // 2 * 2 + 1)
    smooth = np.stack([np.convolve(np.pad(path[:, i], k // 2, mode="edge"), np.ones(k) / k, mode="valid") for i in range(2)], -1)
    return float(np.sqrt(((path - smooth) ** 2).sum(-1)).mean())


def grid_map(rgb: np.ndarray, measure, cells: int = 4) -> list[list[float]]:
    """A measure taken on each cell of a cells×cells grid over the frame: where in the picture a defect is."""
    h, w = rgb.shape[:2]
    out = []
    for i in range(cells):
        row = []
        for j in range(cells):
            part = rgb[i * h // cells:(i + 1) * h // cells, j * w // cells:(j + 1) * w // cells]
            row.append(round(float(measure(part)), 4))
        out.append(row)
    return out
