"""NIQE, PSNR and SSIM, from BasicSR `basicsr/metrics/{niqe,psnr_ssim}.py` and `basicsr/utils/matlab_functions.py`
(commit 8d56e3a). `estimate_aggd_param`, `compute_feature` and `niqe` are BasicSR's code unchanged. `imresize` is BasicSR's
MATLAB-style bicubic resize moved from PyTorch to numpy. `ssim` uses scipy for what BasicSR did with `cv2.filter2D` (same
11-tap Gaussian window, sigma 1.5, valid region)."""
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import convolve, correlate
from scipy.special import gamma

_PARAMS = Path(__file__).with_name("niqe_pris_params.npz")


# ------------------------------------------------------------------------------------------- BasicSR, unchanged
def estimate_aggd_param(block):
    block = block.flatten()
    gam = np.arange(0.2, 10.001, 0.001)  # len = 9801
    gam_reciprocal = np.reciprocal(gam)
    r_gam = np.square(gamma(gam_reciprocal * 2)) / (gamma(gam_reciprocal) * gamma(gam_reciprocal * 3))

    left_std = np.sqrt(np.mean(block[block < 0]**2))
    right_std = np.sqrt(np.mean(block[block > 0]**2))
    gammahat = left_std / right_std
    rhat = (np.mean(np.abs(block)))**2 / np.mean(block**2)
    rhatnorm = (rhat * (gammahat**3 + 1) * (gammahat + 1)) / ((gammahat**2 + 1)**2)
    array_position = np.argmin((r_gam - rhatnorm)**2)

    alpha = gam[array_position]
    beta_l = left_std * np.sqrt(gamma(1 / alpha) / gamma(3 / alpha))
    beta_r = right_std * np.sqrt(gamma(1 / alpha) / gamma(3 / alpha))
    return (alpha, beta_l, beta_r)


def compute_feature(block):
    feat = []
    alpha, beta_l, beta_r = estimate_aggd_param(block)
    feat.extend([alpha, (beta_l + beta_r) / 2])
    shifts = [[0, 1], [1, 0], [1, 1], [1, -1]]
    for i in range(len(shifts)):
        shifted_block = np.roll(block, shifts[i], axis=(0, 1))
        alpha, beta_l, beta_r = estimate_aggd_param(block * shifted_block)
        mean = (beta_r - beta_l) * (gamma(2 / alpha) / gamma(1 / alpha))
        feat.extend([alpha, mean, beta_l, beta_r])
    return feat


def niqe(img, mu_pris_param, cov_pris_param, gaussian_window, block_size_h=96, block_size_w=96):
    assert img.ndim == 2, ('Input image must be a gray or Y (of YCbCr) image with shape (h, w).')
    h, w = img.shape
    num_block_h = math.floor(h / block_size_h)
    num_block_w = math.floor(w / block_size_w)
    img = img[0:num_block_h * block_size_h, 0:num_block_w * block_size_w]

    distparam = []
    for scale in (1, 2):
        mu = convolve(img, gaussian_window, mode='nearest')
        sigma = np.sqrt(np.abs(convolve(np.square(img), gaussian_window, mode='nearest') - np.square(mu)))
        img_nomalized = (img - mu) / (sigma + 1)

        feat = []
        for idx_w in range(num_block_w):
            for idx_h in range(num_block_h):
                block = img_nomalized[idx_h * block_size_h // scale:(idx_h + 1) * block_size_h // scale,
                                      idx_w * block_size_w // scale:(idx_w + 1) * block_size_w // scale]
                feat.append(compute_feature(block))

        distparam.append(np.array(feat))

        if scale == 1:
            img = imresize(img / 255., scale=0.5, antialiasing=True)
            img = img * 255.

    distparam = np.concatenate(distparam, axis=1)
    mu_distparam = np.nanmean(distparam, axis=0)
    distparam_no_nan = distparam[~np.isnan(distparam).any(axis=1)]
    cov_distparam = np.cov(distparam_no_nan, rowvar=False)
    invcov_param = np.linalg.pinv((cov_pris_param + cov_distparam) / 2)
    quality = np.matmul(
        np.matmul((mu_pris_param - mu_distparam), invcov_param), np.transpose((mu_pris_param - mu_distparam)))
    quality = np.sqrt(quality)
    quality = float(np.squeeze(quality))
    return quality


# --------------------------------------------------------------------------- BasicSR's imresize, in numpy
def _cubic(x):
    absx = np.abs(x)
    absx2, absx3 = absx**2, absx**3
    return (1.5 * absx3 - 2.5 * absx2 + 1) * (absx <= 1) + (-0.5 * absx3 + 2.5 * absx2 - 4 * absx + 2) * ((absx > 1) & (absx <= 2))


def _weights_indices(in_length, out_length, scale, kernel_width, antialiasing):
    if scale < 1 and antialiasing:
        kernel_width = kernel_width / scale
    x = np.linspace(1, out_length, out_length)
    u = x / scale + 0.5 * (1 - 1 / scale)
    left = np.floor(u - kernel_width / 2)
    p = math.ceil(kernel_width) + 2
    indices = left[:, None] + np.arange(p)[None, :]
    distance_to_center = u[:, None] - indices
    weights = scale * _cubic(distance_to_center * scale) if (scale < 1 and antialiasing) else _cubic(distance_to_center)
    weights = weights / weights.sum(1, keepdims=True)
    zeros = (weights == 0).sum(0)
    if not math.isclose(zeros[0], 0, rel_tol=1e-6):
        indices, weights = indices[:, 1:p - 1], weights[:, 1:p - 1]
    if not math.isclose(zeros[-1], 0, rel_tol=1e-6):
        indices, weights = indices[:, 0:p - 2], weights[:, 0:p - 2]
    return weights, indices.astype(int) - 1                         # 1-based like MATLAB, made 0-based


def _resize_axis(img: np.ndarray, out_length: int, scale: float, axis: int, antialiasing: bool) -> np.ndarray:
    in_length = img.shape[axis]
    weights, indices = _weights_indices(in_length, out_length, scale, 4, antialiasing)
    # Symmetric padding, as BasicSR does, by reflecting indices that fall outside.
    idx = np.where(indices < 0, -indices - 1, indices)
    idx = np.where(idx >= in_length, 2 * in_length - idx - 1, idx)
    moved = np.moveaxis(img, axis, 0)
    out = np.einsum("op,op...->o...", weights, moved[idx])
    return np.moveaxis(out, 0, axis)


def imresize(img, scale, antialiasing=True):
    """MATLAB's bicubic imresize, [0, 1] range, (h, w) or (h, w, c)."""
    img = np.asarray(img, np.float64)
    out_h, out_w = math.ceil(img.shape[0] * scale), math.ceil(img.shape[1] * scale)
    return _resize_axis(_resize_axis(img, out_h, scale, 0, antialiasing), out_w, scale, 1, antialiasing)


# ------------------------------------------------------------------------------------------------------- the API
def to_y(rgb: np.ndarray) -> np.ndarray:
    """The Y channel of MATLAB's rgb2ycbcr, [0, 255], from an RGB image in [0, 255]."""
    rgb = np.asarray(rgb, np.float64) / 255.0
    return (np.dot(rgb[..., :3], [65.481, 128.553, 24.966]) + 16.0)


def calculate_niqe(img: np.ndarray, crop_border: int = 0) -> float:
    """NIQE of an RGB (or grey) image in [0, 255]: lower is more natural. Needs at least 192×192 pixels."""
    params = np.load(_PARAMS)
    mu_pris_param, cov_pris_param, gaussian_window = params["mu_pris_param"], params["cov_pris_param"], params["gaussian_window"]
    y = to_y(img) if img.ndim == 3 else np.asarray(img, np.float64)
    y = np.round(y)
    if crop_border:
        y = y[crop_border:-crop_border, crop_border:-crop_border]
    return niqe(y, mu_pris_param, cov_pris_param, gaussian_window)


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    """Peak signal-to-noise ratio between two images in [0, 255]; inf when equal."""
    mse = np.mean((np.asarray(a, np.float64) - np.asarray(b, np.float64)) ** 2)
    return float("inf") if mse == 0 else float(10.0 * np.log10(255.0 * 255.0 / mse))


def _ssim_channel(img, img2):
    c1, c2 = (0.01 * 255)**2, (0.03 * 255)**2
    ax = np.arange(11) - 5
    k = np.exp(-(ax**2) / (2 * 1.5**2)); k = k / k.sum()
    window = np.outer(k, k)
    f = lambda x: correlate(x, window, mode="reflect")[5:-5, 5:-5]
    mu1, mu2 = f(img), f(img2)
    mu1_sq, mu2_sq, mu1_mu2 = mu1**2, mu2**2, mu1 * mu2
    sigma1_sq, sigma2_sq, sigma12 = f(img**2) - mu1_sq, f(img2**2) - mu2_sq, f(img * img2) - mu1_mu2
    ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
    return float(ssim_map.mean())


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Structural similarity of two images in [0, 255], on the Y channel as BasicSR reports it."""
    ya = to_y(a) if np.asarray(a).ndim == 3 else np.asarray(a, np.float64)
    yb = to_y(b) if np.asarray(b).ndim == 3 else np.asarray(b, np.float64)
    return _ssim_channel(ya.astype(np.float64), yb.astype(np.float64))
