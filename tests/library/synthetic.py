"""Frames made up for tests of the measuring and dividing rules: each shot is its own textured picture, which can slide
(a pan), grow (a push in), fade into another (a dissolve) or stand still, with a little noise on top like a real sensor."""
import numpy as np

from nexora.modules.library.signals import HEIGHT, WIDTH

CANVAS = 4          # the picture a shot is cut from is this many times the frame, so that a window can slide and grow in it


def picture(shot: int, colour_of: int | None = None) -> np.ndarray:
    """A large textured colour picture, the same for the same `shot` and unlike that of any other. With `colour_of`, it takes
    the overall colour of that other shot, as two shots of one scene do."""
    rng = np.random.default_rng(1000 + shot)
    h, w = HEIGHT * CANVAS, WIDTH * CANVAS
    coarse = rng.random((h // 6 + 2, w // 6 + 2, 3)).astype(np.float32)
    big = np.kron(coarse, np.ones((6, 6, 1), np.float32))[:h, :w]
    for _ in range(2):                                                  # soften the blocks so that it reads as a picture, not a grid
        big = (big + np.roll(big, 1, 0) + np.roll(big, -1, 0) + np.roll(big, 1, 1) + np.roll(big, -1, 1)) / 5
    tint = rng.random(3).astype(np.float32) * 0.9 + 0.05           # shots differ in colour and in brightness, as real ones do
    if colour_of is not None:
        other = np.random.default_rng(1000 + colour_of)
        other.random((h // 6 + 2, w // 6 + 2, 3))
        tint = other.random(3).astype(np.float32) * 0.9 + 0.05
    return np.clip(big * 0.5 + tint * 0.5, 0, 1)


def view(shot: int, *, x: float = 0.0, y: float = 0.0, scale: float = 1.0, noise: int = 0, colour_of: int | None = None) -> np.ndarray:
    """One frame: the window of the shot's picture at offset (x, y) pixels from its middle, `scale` times magnified."""
    big = picture(shot, colour_of)
    h, w = big.shape[:2]
    ys = (np.arange(HEIGHT) - HEIGHT / 2) / scale + h / 2 + y
    xs = (np.arange(WIDTH) - WIDTH / 2) / scale + w / 2 + x
    y0, x0 = np.clip(np.floor(ys).astype(int), 0, h - 2), np.clip(np.floor(xs).astype(int), 0, w - 2)
    fy, fx = (ys - y0)[:, None, None], (xs - x0)[None, :, None]
    out = (big[y0][:, x0] * (1 - fy) * (1 - fx) + big[y0][:, x0 + 1] * (1 - fy) * fx + big[y0 + 1][:, x0] * fy * (1 - fx) + big[y0 + 1][:, x0 + 1] * fy * fx)
    out = out * 255
    if noise:
        out = out + np.random.default_rng(noise).integers(-2, 3, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def film(frames: list[np.ndarray], chunk: int = 64):
    """The frames in groups, the way they come off a file."""
    for i in range(0, len(frames), chunk):
        yield np.stack(frames[i:i + chunk])


def still_shot(shot: int, count: int) -> list[np.ndarray]:
    return [view(shot, noise=shot * 10_000 + i + 1) for i in range(count)]


def panning_shot(shot: int, count: int, *, per_frame: float) -> list[np.ndarray]:
    """The camera turns right: the picture slides left by `per_frame` pixels each frame."""
    return [view(shot, x=per_frame * i - per_frame * count / 2, noise=shot * 10_000 + i + 1) for i in range(count)]


def dissolve(a: np.ndarray, b: np.ndarray, count: int) -> list[np.ndarray]:
    return [np.clip(a.astype(np.float32) * (1 - k / (count + 1)) + b.astype(np.float32) * (k / (count + 1)), 0, 255).astype(np.uint8) for k in range(1, count + 1)]
