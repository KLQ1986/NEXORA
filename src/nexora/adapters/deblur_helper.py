"""Deblurring, run in its own environment (data/tools/nafnet: MLX, nafnet-mlx) by adapters/deblur.py.

    python -I deblur_helper.py <in> <out> <json>      in/out: one picture each, or a folder of frames each; json: {"model": path, "tile": 512}

NAFNet width64 trained on GoPro motion blur (Chen et al., ECCV 2022, MIT), in its MLX port (mlx-community/NAFNet-GoPro-width64,
with NAFNet's local pooling, TLC), on the Apple GPU. A picture is worked at its own size in overlapping tiles blended by a
ramp, so a 4K frame needs no more memory than a tile. Measured on an M4 (2026-10-17): 0.64 s a 512-pixel tile, the best size
(1024 tiles and whole frames were slower per pixel), so about 6 s a 1080p frame and 25 s a 4K one. Against OpenCV's ONNX
export of NAFNet on the same blurred picture: PSNR 23.7 against 22.0, SSIM 0.66 against 0.52, and twice as fast.
One JSON line on stdout says what was done.
"""
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
from PIL import Image
from nafnet_mlx import NAFNetConfig
from nafnet_mlx.pipeline import load_model

OVERLAP = 32


def tiles(length: int, tile: int) -> list[int]:
    if length <= tile:
        return [0]
    return sorted(set(list(range(0, length - tile, tile - OVERLAP)) + [length - tile]))


def ramp(size: int, at_start: bool, at_end: bool) -> np.ndarray:
    w = np.ones(size, np.float32)
    r = np.linspace(0, 1, OVERLAP + 2, dtype=np.float32)[1:-1]
    if not at_start:
        w[:OVERLAP] = r
    if not at_end:
        w[-OVERLAP:] = r[::-1]
    return w


def deblur(model, rgb: np.ndarray, tile: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    out = np.zeros((h, w, 3), np.float32)
    weight = np.zeros((h, w, 1), np.float32)
    ys, xs = tiles(h, tile), tiles(w, tile)
    for y in ys:
        for x in xs:
            patch = rgb[y:y + tile, x:x + tile]
            ph, pw = patch.shape[:2]
            done = np.array(model(mx.array(patch[None])))[0]
            m = (ramp(ph, y == ys[0], y == ys[-1])[:, None] * ramp(pw, x == xs[0], x == xs[-1])[None, :])[..., None]
            out[y:y + ph, x:x + pw] += np.clip(done, 0, 1) * m
            weight[y:y + ph, x:x + pw] += m
    return out / np.maximum(weight, 1e-6)


def main() -> None:
    src, dst, args = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
    model = load_model(args["model"], NAFNetConfig.gopro_width64())
    tile = int(args.get("tile", 512))
    pairs = [(src, dst)] if src.is_file() else [(f, dst / f.name) for f in sorted(src.glob("*.png"))]
    if not src.is_file():
        dst.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for a, b in pairs:
        with Image.open(a) as im:
            rgb = np.asarray(im.convert("RGB"), np.float32) / 255.0
        Image.fromarray((deblur(model, rgb, tile) * 255.0).round().astype(np.uint8)).save(b)
    print(json.dumps({"pictures": len(pairs), "seconds": round(time.time() - t0, 2)}))


if __name__ == "__main__":
    main()
