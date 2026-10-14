"""What can be measured from the picture without asking a model: how much each frame differs from the one before, how the
camera moves, how much the subject moves, where the eye is drawn, how bright and how sharp the picture is.

Every measure is a row of numbers over time, one per analysed frame. They are computed in one pass over small copies of the
frames (96 by 54), in bounded memory however long the recording is, and kept beside the footage so that a change of
threshold never means decoding the file again.

Three of the measures follow methods read in FilmCraft's source (MIT or Apache-2.0), rewritten here from the description
of the method, with no code taken: the frame signature and its difference (crates/render/src/scene.rs), the camera path
(crates/render/src/vfx/temporal.rs) and the centre of attention (the same file, `saliency_centroid`).
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

WIDTH, HEIGHT = 96, 54                 # the size frames are analysed at
GRID_W, GRID_H = 32, 18                # the signature's grid of mean brightness
BINS = 16                              # histogram bins per colour channel
FAR_SECONDS = 0.5                      # a frame is also compared with the one this long before it, to see slow changes
MOTION_SECONDS = 0.2                   # motion is measured across this long, so that slow movement is still more than a pixel
SIGNATURE_RATE = 10.0                  # signatures kept per second, for comparing stretches of footage later
BRIGHT, DARK = 250, 6                  # a pixel at or beyond these has lost its detail
BAR_LUMA = 16 / 255                    # a row or column that never gets brighter than this is a black bar
MARGIN = 8                             # pixels left out at each edge when the frame is compared with a shifted copy of itself
VERSION = 2


@dataclass
class Signals:
    fps: float
    diff: np.ndarray                   # how different each frame is from the one before, 0 to 1
    far: np.ndarray                    # how different its colours are from the frame half a second before, 0 to 1
    pan_x: np.ndarray                  # camera movement to the right, in frame widths a second
    pan_y: np.ndarray                  # camera movement downwards, in frame heights a second
    zoom: np.ndarray                   # growth of the picture a second: above zero the camera is pushing in
    subject: np.ndarray                # movement left once the camera's own is taken out, 0 to 1
    luma: np.ndarray                   # mean brightness, 0 to 1
    clip_hi: np.ndarray                # share of pixels burnt out
    clip_lo: np.ndarray                # share of pixels crushed to black
    cx: np.ndarray                     # where the eye is drawn, 0 (left) to 1 (right)
    cy: np.ndarray                     # the same, 0 (top) to 1 (bottom)
    sig_rate: float
    sig_grid: np.ndarray               # signatures kept at `sig_rate`: brightness grids
    sig_hist: np.ndarray               # and colour histograms
    bars: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)      # black bars: top, bottom, left, right, as shares of the frame
    blur: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))     # blurriness at `blur_rate`, when the tool can measure it
    blur_rate: float = 0.0

    @property
    def frames(self) -> int:
        return len(self.diff)

    @property
    def duration(self) -> float:
        return self.frames / self.fps if self.fps else 0.0

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        with open(partial, "wb") as out:
            np.savez_compressed(out, version=VERSION, fps=self.fps, sig_rate=self.sig_rate, bars=np.array(self.bars), blur_rate=self.blur_rate,
                                **{name: getattr(self, name) for name in _ARRAYS})
        partial.replace(path)

    @classmethod
    def load(cls, path: str | Path) -> "Signals | None":
        """The measures saved at `path`, or None when there are none or they were made by another version of this module."""
        path = Path(path)
        if not path.is_file():
            return None
        try:
            with np.load(path) as data:
                if int(data["version"]) != VERSION:
                    return None
                return cls(fps=float(data["fps"]), sig_rate=float(data["sig_rate"]), bars=tuple(float(v) for v in data["bars"]),
                           blur_rate=float(data["blur_rate"]), **{name: data[name] for name in _ARRAYS})
        except (OSError, ValueError, KeyError):
            return None


_ARRAYS = ("diff", "far", "pan_x", "pan_y", "zoom", "subject", "luma", "clip_hi", "clip_lo", "cx", "cy", "sig_grid", "sig_hist", "blur")


def read_frames(path: str | Path, *, chunk: int = 256) -> Iterator[np.ndarray]:
    """Raw RGB frames of the analysis size from a file, a few hundred at a time."""
    size = WIDTH * HEIGHT * 3
    with open(path, "rb") as source:
        while True:
            data = source.read(size * chunk)
            count = len(data) // size
            if not count:
                return
            yield np.frombuffer(data[:count * size], np.uint8).reshape(count, HEIGHT, WIDTH, 3)


def difference(grid_a: np.ndarray, hist_a: np.ndarray, grid_b: np.ndarray, hist_b: np.ndarray) -> np.ndarray:
    """How different two frames look, 0 (the same) to 1. A cut changes both the colours and where the light is; movement
    changes where the light is and keeps the colours; a change of light shifts the colours a little at a time."""
    colours = np.abs(hist_a - hist_b).sum(-1) / 6.0
    light = np.abs(grid_a - grid_b).mean(-1)
    return np.clip(0.5 * colours + 0.5 * np.minimum(2.0 * light, 1.0), 0.0, 1.0)


def colour_difference(hist_a: np.ndarray, hist_b: np.ndarray) -> np.ndarray:
    return np.clip(np.abs(hist_a - hist_b).sum(-1) / 6.0, 0.0, 1.0)


def _signature(frames: np.ndarray, luma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    count = len(frames)
    grid = luma.reshape(count, GRID_H, HEIGHT // GRID_H, GRID_W, WIDTH // GRID_W).mean((2, 4)).reshape(count, -1)
    hist = np.empty((count, 3 * BINS), np.float32)
    offsets = (np.arange(count, dtype=np.int64) * BINS)[:, None]
    for channel in range(3):
        bins = (frames[..., channel].reshape(count, -1) >> 4).astype(np.int64) + offsets
        hist[:, channel * BINS:(channel + 1) * BINS] = np.bincount(bins.ravel(), minlength=count * BINS).reshape(count, BINS)
    return grid.astype(np.float32), hist / float(WIDTH * HEIGHT)


def _window(height: int, width: int) -> np.ndarray:
    return np.outer(np.hanning(height), np.hanning(width)).astype(np.float32)


def _shift(earlier: np.ndarray, later: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """How far the picture moved between two stacks of frames, in pixels (to the right and downwards), by phase correlation:
    the peak of the whitened cross-spectrum sits at the displacement. The peak is refined to a fraction of a pixel."""
    count, height, width = earlier.shape
    window = _window(height, width)
    a, b = np.fft.rfft2(earlier * window), np.fft.rfft2(later * window)
    cross = b * np.conj(a)
    cross /= np.abs(cross) + 1e-9
    surface = np.fft.irfft2(cross, s=(height, width))
    flat = surface.reshape(count, -1).argmax(1)
    py, px = flat // width, flat % width
    rows = np.arange(count)

    def refine(centre, before, after):
        denominator = before - 2 * centre + after
        return np.where(np.abs(denominator) > 1e-9, 0.5 * (before - after) / np.where(np.abs(denominator) > 1e-9, denominator, 1.0), 0.0)

    peak = surface[rows, py, px]
    dx = px + refine(peak, surface[rows, py, (px - 1) % width], surface[rows, py, (px + 1) % width])
    dy = py + refine(peak, surface[rows, (py - 1) % height, px], surface[rows, (py + 1) % height, px])
    dx = np.where(dx > width / 2, dx - width, dx)
    dy = np.where(dy > height / 2, dy - height, dy)
    return dx.astype(np.float32), dy.astype(np.float32)


def _attention(luma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Where the eye is drawn in each frame: the centre of the picture's detail, leaning a little towards the middle."""
    gx = luma[:, 1:-1, 2:] - luma[:, 1:-1, :-2]
    gy = luma[:, 2:, 1:-1] - luma[:, :-2, 1:-1]
    height, width = luma.shape[1] - 2, luma.shape[2] - 2
    u = (np.arange(1, width + 1) / luma.shape[2] - 0.5)[None, None, :]
    v = (np.arange(1, height + 1) / luma.shape[1] - 0.5)[None, :, None]
    energy = ((gx * gx + gy * gy) * np.maximum(1.0 - (u * u + v * v) * 0.8, 0.1)) ** 2
    total = energy.sum((1, 2))
    xs = (energy.sum(1) * np.arange(1, width + 1)[None, :]).sum(1)
    ys = (energy.sum(2) * np.arange(1, height + 1)[None, :]).sum(1)
    safe = np.where(total > 1e-12, total, 1.0)
    cx = np.where(total > 1e-12, (xs / safe + 0.5) / luma.shape[2], 0.5)
    cy = np.where(total > 1e-12, (ys / safe + 0.5) / luma.shape[1], 0.5)
    return cx.astype(np.float32), cy.astype(np.float32)


def analyse(chunks: Iterable[np.ndarray], fps: float) -> Signals:
    """Measure a recording from its small frames, given a few hundred at a time. Memory stays the size of one such group plus
    one number per frame for each measure, whatever the length."""
    far_back, step = max(1, round(fps * FAR_SECONDS)), max(1, round(fps * MOTION_SECONDS))
    keep_every = max(1, round(fps / SIGNATURE_RATE))
    reach = max(far_back, step)
    out = {name: [] for name in ("diff", "far", "pan_x", "pan_y", "zoom", "subject", "luma", "clip_hi", "clip_lo", "cx", "cy", "sig_grid", "sig_hist")}
    tail_luma = np.zeros((0, HEIGHT, WIDTH), np.float32)
    tail_grid, tail_hist = np.zeros((0, GRID_W * GRID_H), np.float32), np.zeros((0, 3 * BINS), np.float32)
    row_max, col_max = np.zeros(HEIGHT, np.float32), np.zeros(WIDTH, np.float32)
    seen = 0
    half_h, half_w = HEIGHT // 2, WIDTH // 2
    # Each quarter of the frame, the way from the middle of the frame to its own middle, and how far that is.
    quarters = [(slice(0, half_h), slice(0, half_w), -1, -1), (slice(0, half_h), slice(half_w, WIDTH), 1, -1),
                (slice(half_h, HEIGHT), slice(0, half_w), -1, 1), (slice(half_h, HEIGHT), slice(half_w, WIDTH), 1, 1)]
    crop = None                                  # the rows and columns that hold picture, once black bars have been seen
    for frames in chunks:
        count = len(frames)
        whole = (0.2126 * frames[..., 0].astype(np.float32) + 0.7152 * frames[..., 1] + 0.0722 * frames[..., 2]) / 255.0
        row_max, col_max = np.maximum(row_max, whole.max((0, 2))), np.maximum(col_max, whole.max((0, 1)))
        if crop is None and whole.max() > BAR_LUMA:
            # Black bars are the same in every frame, so they water down every comparison between frames. From the first frames
            # that show a picture on, only the part between the bars is measured, spread back over the full size.
            top, bottom, left, right = (round(v * n) for v, n in zip(_bars(whole.max((0, 2)), whole.max((0, 1))), (HEIGHT, HEIGHT, WIDTH, WIDTH)))
            crop = (np.linspace(top, HEIGHT - bottom - 1, HEIGHT).round().astype(int), np.linspace(left, WIDTH - right - 1, WIDTH).round().astype(int))
        if crop is not None and (crop[0][0] or crop[0][-1] != HEIGHT - 1 or crop[1][0] or crop[1][-1] != WIDTH - 1):
            frames = frames[:, crop[0]][:, :, crop[1]]
        rgb = frames.astype(np.float32)
        luma = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0
        grid, hist = _signature(frames, luma)
        all_luma, all_grid, all_hist = np.concatenate([tail_luma, luma]), np.concatenate([tail_grid, grid]), np.concatenate([tail_hist, hist])
        had = len(tail_luma)
        at = np.arange(had, had + count)

        prev = np.maximum(at - 1, 0)
        diff = difference(all_grid[prev], all_hist[prev], all_grid[at], all_hist[at])
        back = np.maximum(at - far_back, 0)
        far = colour_difference(all_hist[back], all_hist[at])
        if seen == 0:
            diff[0] = 0.0
        far[seen + np.arange(count) < far_back] = 0.0

        before = np.maximum(at - step, 0)
        earlier, later = all_luma[before], all_luma[at]
        dx, dy = _shift(earlier, later)
        spread = np.zeros(count, np.float32)
        for rows, cols, sx, sy in quarters:
            qx, qy = _shift(earlier[:, rows, cols], later[:, rows, cols])
            spread += ((qx - dx) * sx / (WIDTH / 4) + (qy - dy) * sy / (HEIGHT / 4)) / 2
        spread /= len(quarters)
        seconds = step / fps
        started = seen + np.arange(count) >= step
        residual = np.zeros(count, np.float32)
        for i in np.nonzero(started)[0]:
            moved = np.roll(earlier[i], (int(round(float(dy[i]))), int(round(float(dx[i])))), (0, 1))
            residual[i] = np.abs(later[i, MARGIN:-MARGIN, MARGIN:-MARGIN] - moved[MARGIN:-MARGIN, MARGIN:-MARGIN]).mean()
        cx, cy = _attention(luma)

        out["diff"].append(diff.astype(np.float32)); out["far"].append(far.astype(np.float32))
        out["pan_x"].append(np.where(started, -dx / WIDTH / seconds, 0.0).astype(np.float32))       # the picture sliding left is the camera turning right
        out["pan_y"].append(np.where(started, -dy / HEIGHT / seconds, 0.0).astype(np.float32))
        out["zoom"].append(np.where(started, spread / seconds, 0.0).astype(np.float32))
        out["subject"].append(np.clip(residual * 4.0, 0.0, 1.0))
        out["luma"].append(luma.mean((1, 2)).astype(np.float32))
        values = np.rint(luma * 255.0)
        out["clip_hi"].append((values >= BRIGHT).mean((1, 2)).astype(np.float32)); out["clip_lo"].append((values <= DARK).mean((1, 2)).astype(np.float32))
        out["cx"].append(cx); out["cy"].append(cy)
        kept = np.nonzero((seen + np.arange(count)) % keep_every == 0)[0]
        out["sig_grid"].append(grid[kept].astype(np.float16)); out["sig_hist"].append(hist[kept].astype(np.float16))

        tail_luma, tail_grid, tail_hist = all_luma[-reach:], all_grid[-reach:], all_hist[-reach:]
        seen += count

    def joined(name, width=None):
        parts = out[name]
        if parts:
            return np.concatenate(parts)
        return np.zeros((0, width), np.float16) if width else np.zeros(0, np.float32)

    signals = Signals(fps=fps, sig_rate=fps / keep_every, sig_grid=joined("sig_grid", GRID_W * GRID_H), sig_hist=joined("sig_hist", 3 * BINS),
                      **{name: joined(name) for name in ("diff", "far", "pan_x", "pan_y", "zoom", "subject", "luma", "clip_hi", "clip_lo", "cx", "cy")})
    if seen:
        signals.bars = _bars(row_max, col_max)          # named from the whole recording: a dark edge in the first seconds is not a bar
    return signals


def _bars(row_max: np.ndarray, col_max: np.ndarray) -> tuple[float, float, float, float]:
    """Rows and columns at the edges that stayed black through the whole recording. A recording that is black throughout has no bars."""
    def edge(values: np.ndarray) -> tuple[int, int]:
        dark = values <= BAR_LUMA
        if dark.all():
            return 0, 0
        first = int(np.argmin(dark))
        last = int(np.argmin(dark[::-1]))
        return first, last

    top, bottom = edge(row_max)
    left, right = edge(col_max)
    share = lambda n, of: round(n / of, 3) if n >= 2 else 0.0          # a single dark row is the edge of the picture, not a bar
    return share(top, HEIGHT), share(bottom, HEIGHT), share(left, WIDTH), share(right, WIDTH)
