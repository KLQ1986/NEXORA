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
    blur: float = 0.0         # Crete's re-blur measure, 0 sharp .. 1 all blur: how little blurring the picture again changes it


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., :3] @ LUMA


NOISE_BLOCK = 16           # side of the blocks the noise is estimated in
NOISE_PERCENTILE = 10      # the quietest blocks decide: there only the noise answers the mask
NOISE_BIAS = 1.1           # a low percentile of estimates reads about a tenth under the noise itself (measured on pure noise)


def noise_sigma(y: np.ndarray) -> float:
    """Immerkær's fast noise estimate, on 0..255 luma: the response to a mask that cancels edges and smooth slopes.

    Texture answers the mask too (foliage, gravel, fabric): over a whole frame of leaves it reads a clean photo as σ 10.8
    (2026-10-17, frame 0042). It is therefore taken in blocks and from the quietest of them, where only the noise is left:
    the same photo reads 3.2, and noise added to it is read within a tenth of what was added on flat footage (0059)."""
    m = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    r = np.abs(convolve(y * 255.0, m, mode="reflect"))[1:-1, 1:-1]
    scale = np.sqrt(np.pi / 2) / 6.0
    b = NOISE_BLOCK
    h, w = (r.shape[0] // b) * b, (r.shape[1] // b) * b
    if h // b * (w // b) < 16:
        return float(scale * r.mean())
    blocks = r[:h, :w].reshape(h // b, b, w // b, b).mean((1, 3)) * scale
    return float(min(scale * r.mean(), np.percentile(blocks, NOISE_PERCENTILE) * NOISE_BIAS))


def reblur(y: np.ndarray, k: int = 9) -> float:
    """Crete et al.'s no-reference blur measure (2007): the picture is blurred again along each axis, and what share of its
    steps between neighbours survive is read; a picture already blurred loses little. Unlike the Laplacian's variance it does
    not read busy texture as sharp: measured (2026-10-17) clean frames read 0.17–0.29 and each blurred version of them
    (Gaussian σ 1.4, motion of 11 pixels) 0.39 or more, where the Laplacian still called motion-blurred foliage sharp (183)."""
    from scipy.ndimage import uniform_filter1d

    def along(axis: int) -> float:
        d = np.abs(np.diff(y, axis=axis))
        survive = np.maximum(0.0, d - np.abs(np.diff(uniform_filter1d(y, k, axis=axis), axis=axis)))
        total = float(d.sum())
        return (total - float(survive.sum())) / max(total, 1e-9)
    return float(max(along(0), along(1)))


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
                noise=noise_sigma(y), sharpness=laplacian_variance(y), blur=reblur(y), detail=detail_share(y), blockiness=blockiness(y), banding=banding(y, depth=depth),
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


def chroma_offset(rgb: np.ndarray, reach: int = 8) -> tuple[float, float]:
    """How far the colour sits to the side of the picture (pixels, Cb and Cr; positive to the right), as on tape where the
    colour is carried late: the shift that best lines the edges of each colour difference up with the edges of luma, to a
    tenth of a pixel. Edges are horizontal gradients, read on rows with some detail."""
    x = rgb.astype(np.float64)
    y = x @ np.array([0.2126, 0.7152, 0.0722])
    cb, cr = x[..., 2] - y, x[..., 0] - y
    gy = np.abs(np.diff(y, axis=1))
    rows = gy.mean(axis=1) > np.percentile(gy.mean(axis=1), 50)          # the rows with most detail
    out = []
    for c in (cb, cr):
        gc = np.abs(np.diff(c, axis=1))
        a, b = gy[rows] - gy[rows].mean(), gc[rows] - gc[rows].mean()
        w = a.shape[1]
        score = np.array([float((a[:, max(0, -d):w - max(0, d)] * b[:, max(0, d):w - max(0, -d)]).mean()) for d in range(-reach, reach + 1)])
        k = int(score.argmax())
        frac = 0.0
        if 0 < k < len(score) - 1:                                       # a parabola through the peak and its neighbours
            l, m, r = score[k - 1], score[k], score[k + 1]
            den = l - 2 * m + r
            frac = 0.5 * (l - r) / den if den else 0.0
        out.append(round(k - reach + frac, 2))
    return out[0], out[1]


def bottom_band(frames: list[np.ndarray], *, depth: int = 20) -> int:
    """Rows at the foot of the picture torn sideways, as a tape's head switch leaves them: how the edges along each row line
    up with those two rows above, in the same field (correlation of horizontal gradients, the median over the frames: next
    rows of interlaced footage come from two moments and never line up, and values alone stay alike in a smooth picture when
    a row slides), counted up from the bottom while it is much worse (under 0.6 of) than rows
    in the picture, one good row in between allowed. 0 when there is none."""
    per_frame = []
    for f in frames:
        y = luma(f)
        if y.shape[0] < depth * 4:
            continue
        rows = np.diff(y, axis=1)                                   # the edges along each row: a torn row loses their place
        rows = rows - rows.mean(axis=1, keepdims=True)
        norm = np.linalg.norm(rows, axis=1) + 1e-6
        corr = (rows[2:] * rows[:-2]).sum(axis=1) / (norm[2:] * norm[:-2])     # two apart: the same field
        # A row with little detail (a table top, sky) has edges of noise only: it cannot show a tear, so it never counts as one.
        corr[norm[2:] < 0.3 * np.median(norm)] = np.nan
        per_frame.append(corr)
    if not per_frame:
        return 0
    corr = np.nanmedian(np.stack(per_frame), axis=0)                # corr[r]: row r+2 against row r
    n = len(corr)
    typical = float(np.nanmedian(corr[n // 4: 3 * n // 4]))
    broken = np.nan_to_num(corr, nan=typical) < 0.6 * typical
    k, gap = 0, 0
    for r in range(n - 1, n - 1 - depth, -1):
        if broken[r]:
            k, gap = n - r, 0
        elif gap == 0 and k:
            gap = 1
        else:
            break
    # A tear is short and sudden: the rows just above it are whole. A foot of grass or water that matches poorly all the way up
    # (two library clips read 24 rows, the whole depth) is the scene, not the tape.
    if k == 0 or k >= depth - 2:
        return 0
    above = corr[max(0, n - k - 14): n - k - 2]
    return int(k) if np.isfinite(above).any() and float(np.nanmedian(above)) >= 0.75 * typical else 0
