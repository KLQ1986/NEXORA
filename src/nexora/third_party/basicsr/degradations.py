"""Synthetic degradations, from BasicSR `basicsr/data/degradations.py` (commit 8d56e3a): known defects made on a clean
picture, so that the engine can be measured on a case whose right answer is known. `sigma_matrix2`, `mesh_grid`, `pdf2` and
`bivariate_Gaussian` are BasicSR's code unchanged; the noise functions follow BasicSR's; filtering, JPEG and resizing,
which BasicSR does with OpenCV, use scipy and Pillow. Images are float32 RGB in [0, 1], shape (h, w, 3)."""
import io

import numpy as np
from PIL import Image
from scipy.ndimage import convolve


# ------------------------------------------------------------------------------------------- BasicSR, unchanged
def sigma_matrix2(sig_x, sig_y, theta):
    d_matrix = np.array([[sig_x**2, 0], [0, sig_y**2]])
    u_matrix = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    return np.dot(u_matrix, np.dot(d_matrix, u_matrix.T))


def mesh_grid(kernel_size):
    ax = np.arange(-kernel_size // 2 + 1., kernel_size // 2 + 1.)
    xx, yy = np.meshgrid(ax, ax)
    xy = np.hstack((xx.reshape((kernel_size * kernel_size, 1)), yy.reshape(kernel_size * kernel_size,
                                                                           1))).reshape(kernel_size, kernel_size, 2)
    return xy, xx, yy


def pdf2(sigma_matrix, grid):
    inverse_sigma = np.linalg.inv(sigma_matrix)
    kernel = np.exp(-0.5 * np.sum(np.dot(grid, inverse_sigma) * grid, 2))
    return kernel


def bivariate_Gaussian(kernel_size, sig_x, sig_y, theta, grid=None, isotropic=True):
    if grid is None:
        grid, _, _ = mesh_grid(kernel_size)
    if isotropic:
        sigma_matrix = np.array([[sig_x**2, 0], [0, sig_x**2]])
    else:
        sigma_matrix = sigma_matrix2(sig_x, sig_y, theta)
    kernel = pdf2(sigma_matrix, grid)
    kernel = kernel / np.sum(kernel)
    return kernel


# -------------------------------------------------------------------------------- the degradations, without OpenCV
def blur(img: np.ndarray, sigma: float = 2.0, *, kernel_size: int = 21, sigma_y: float | None = None, theta: float = 0.0) -> np.ndarray:
    """Gaussian blur (isotropic, or anisotropic with `sigma_y` and `theta`): soft focus or a little motion."""
    k = bivariate_Gaussian(kernel_size, sigma, sigma_y or sigma, theta, isotropic=sigma_y is None)
    return np.clip(np.stack([convolve(img[..., c], k, mode="reflect") for c in range(3)], -1), 0, 1).astype(np.float32)


def motion_blur(img: np.ndarray, length: int = 15, angle_deg: float = 0.0) -> np.ndarray:
    """A straight streak of `length` pixels at an angle: the camera or the subject moved while the shutter was open."""
    k = np.zeros((length, length), np.float32)
    k[length // 2, :] = 1.0
    k = np.asarray(Image.fromarray((k * 255).astype(np.uint8)).rotate(angle_deg, resample=Image.BILINEAR), np.float32)
    k = k / max(k.sum(), 1e-6)
    return np.clip(np.stack([convolve(img[..., c], k, mode="reflect") for c in range(3)], -1), 0, 1).astype(np.float32)


def add_gaussian_noise(img: np.ndarray, sigma: float = 10.0, *, gray: bool = False, seed: int = 0) -> np.ndarray:
    """Sensor noise as BasicSR makes it: Gaussian, `sigma` on the 0..255 scale, colour or grey."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(img.shape[:2] + ((1,) if gray else (3,))).astype(np.float32) * sigma / 255.0
    return np.clip(img + noise, 0, 1).astype(np.float32)


def add_poisson_noise(img: np.ndarray, scale: float = 1.0, *, seed: int = 0) -> np.ndarray:
    """Shot noise as BasicSR makes it (after scikit-image): counts drawn per pixel."""
    rng = np.random.default_rng(seed)
    img = np.clip((img * 255.0).round(), 0, 255) / 255.0
    vals = 2 ** np.ceil(np.log2(len(np.unique(img))))
    out = np.float32(rng.poisson(img * vals) / float(vals))
    return np.clip(img + (out - img) * scale, 0, 1).astype(np.float32)


def jpeg(img: np.ndarray, quality: int = 30) -> np.ndarray:
    """JPEG compression at a quality: blocks and ringing, as a web copy carries."""
    buf = io.BytesIO()
    Image.fromarray((np.clip(img, 0, 1) * 255).round().astype(np.uint8)).save(buf, "JPEG", quality=int(quality))
    return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), np.float32) / 255.0


def downscale(img: np.ndarray, factor: float = 2.0, *, back: bool = True) -> np.ndarray:
    """Made smaller and, with `back`, enlarged again to its size: a "4K" that was really lower."""
    h, w = img.shape[:2]
    pil = Image.fromarray((np.clip(img, 0, 1) * 255).round().astype(np.uint8))
    small = pil.resize((max(1, int(w / factor)), max(1, int(h / factor))), Image.BICUBIC)
    out = small.resize((w, h), Image.BICUBIC) if back else small
    return np.asarray(out, np.float32) / 255.0


def band(img: np.ndarray, levels: int = 32) -> np.ndarray:
    """Too few levels: smooth gradients turn into steps (banding), as 8-bit or heavy compression leaves them."""
    return (np.round(np.clip(img, 0, 1) * (levels - 1)) / (levels - 1)).astype(np.float32)


def exposure(img: np.ndarray, stops: float = -1.0) -> np.ndarray:
    """Under (negative) or over (positive) exposure by a number of stops, in display light."""
    lin = np.power(np.clip(img, 0, 1), 2.2) * (2.0 ** stops)
    return np.power(np.clip(lin, 0, 1), 1 / 2.2).astype(np.float32)


def colour_cast(img: np.ndarray, rgb=(1.08, 1.0, 0.9)) -> np.ndarray:
    """A white balance gone warm (or cold): channels scaled."""
    return np.clip(img * np.asarray(rgb, np.float32), 0, 1).astype(np.float32)


def flatten_log(img: np.ndarray, contrast: float = 0.45, lift: float = 0.18, saturation: float = 0.45) -> np.ndarray:
    """A picture made to look like ungraded log: low contrast, raised blacks, little colour."""
    grey = img.mean(-1, keepdims=True)
    out = grey + (img - grey) * saturation
    return np.clip(lift + out * contrast, 0, 1).astype(np.float32)
