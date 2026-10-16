"""Deblurring, run in the ONNX environment (data/tools/faces: onnxruntime, OpenCV) by adapters/deblur.py.

    python -I deblur_helper.py <in> <out> <json>      in/out: one picture each, or a folder of frames each; json: {"model": path, "tile": 512}

NAFNet (Chen et al., ECCV 2022) trained on GoPro motion blur, as OpenCV's model zoo exports it (MIT): RGB in 0..1, NCHW, any
size. A picture is worked in overlapping tiles blended by a ramp, so a 4K frame needs no more memory than a tile.
One JSON line on stdout says what was done.
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

OVERLAP = 32
MIN_SIDE = 384


def tiles(length: int, tile: int) -> list[int]:
    if length <= tile:
        return [0]
    step = tile - OVERLAP
    starts = list(range(0, length - tile, step)) + [length - tile]
    return sorted(set(starts))


def ramp(size: int, at_start: bool, at_end: bool) -> np.ndarray:
    w = np.ones(size, np.float32)
    r = np.linspace(0, 1, OVERLAP + 2, dtype=np.float32)[1:-1]
    if not at_start:
        w[:OVERLAP] = r
    if not at_end:
        w[-OVERLAP:] = r[::-1]
    return w


def deblur(session, rgb: np.ndarray, tile: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    out = np.zeros((h, w, 3), np.float32)
    weight = np.zeros((h, w, 1), np.float32)
    ys, xs = tiles(h, tile), tiles(w, tile)
    for y in ys:
        for x in xs:
            patch = rgb[y:y + tile, x:x + tile]
            ph, pw = patch.shape[:2]
            # The network halves the size four times, and this export pools over a window fixed in training that needs at
            # least 384 pixels a side (smaller fails in its Pad node): a patch is padded to that and to a multiple of 16, and
            # cut back after.
            pad_h, pad_w = max(MIN_SIDE - ph, (-ph) % 16), max(MIN_SIDE - pw, (-pw) % 16)
            pad_h, pad_w = pad_h + (-(ph + pad_h)) % 16, pad_w + (-(pw + pad_w)) % 16
            padded = np.pad(patch, ((0, pad_h), (0, pad_w), (0, 0)), mode="symmetric")
            y_ = session.run(None, {"lq": padded.transpose(2, 0, 1)[None]})[0][0].transpose(1, 2, 0)[:ph, :pw]
            wy = ramp(ph, y == ys[0], y == ys[-1])[:, None]
            wx = ramp(pw, x == xs[0], x == xs[-1])[None, :]
            m = (wy * wx)[..., None]
            out[y:y + ph, x:x + pw] += np.clip(y_, 0, 1) * m
            weight[y:y + ph, x:x + pw] += m
    return out / np.maximum(weight, 1e-6)


def main() -> None:
    src, dst, args = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
    options = ort.SessionOptions()
    options.log_severity_level = 3
    session = ort.InferenceSession(args["model"], options, providers=["CPUExecutionProvider"])
    tile = int(args.get("tile", 512))
    pairs = [(src, dst)] if src.is_file() else [(f, dst / f.name) for f in sorted(src.glob("*.png"))]
    if not src.is_file():
        dst.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for a, b in pairs:
        image = cv2.imread(str(a), cv2.IMREAD_COLOR)
        if image is None:
            raise SystemExit(json.dumps({"error": f"cannot read {a}"}))
        rgb = image[:, :, ::-1].astype(np.float32) / 255.0
        fixed = deblur(session, rgb, tile)
        cv2.imwrite(str(b), (fixed[:, :, ::-1] * 255.0).round().astype(np.uint8))
    print(json.dumps({"pictures": len(pairs), "seconds": round(time.time() - t0, 2)}))


if __name__ == "__main__":
    main()
