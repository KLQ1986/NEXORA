"""Face recovery, run in its own environment (data/tools/faces: onnxruntime, OpenCV) by adapters/faces.py.

    python -I faces_helper.py <in> <out> <json>      json: {"model": path, "faces": [[[x, y] × 5], …], "weight": 0..1, "blend": 0..1}

Each face is aligned by its five points (eyes, nose, mouth corners, found by Apple Vision) onto the FFHQ 512 template,
restored by CodeFormer, put back by the inverse warp through a feathered mask, and blended with what was there. The way
the face is cut, restored and pasted follows FaceFusion's face enhancer (facefusion/processors/modules/face_enhancer.py);
the template is FaceFusion's `ffhq_512`. CodeFormer's `weight` is its fidelity: 0 rebuilds the face freely, 1 keeps to it.
One JSON line on stdout says what was done.
"""
import json
import sys

import cv2
import numpy as np
import onnxruntime as ort

FFHQ_512 = np.array([[0.37691676, 0.46864664], [0.62285697, 0.46912813], [0.50123859, 0.61331904],
                     [0.39308822, 0.72541100], [0.61150205, 0.72490465]], np.float32) * 512.0


def restore(session, crop: np.ndarray, weight: float) -> np.ndarray:
    x = crop[:, :, ::-1].astype(np.float32) / 255.0
    x = ((x - 0.5) / 0.5).transpose(2, 0, 1)[None]
    feed = {"input": x}
    if any(i.name == "weight" for i in session.get_inputs()):
        feed["weight"] = np.array(weight, dtype=np.float64)
    y = session.run(None, feed)[0][0]
    y = (np.clip(y, -1, 1) + 1) / 2
    return (y.transpose(1, 2, 0) * 255.0).round().astype(np.uint8)[:, :, ::-1]


def mask(size: int = 512, feather: float = 0.1, pad: float = 0.0) -> np.ndarray:
    """A box with soft edges, the shape a restored face is pasted through."""
    m = np.ones((size, size), np.float32)
    edge = max(1, int(size * feather / 2))
    m[:edge + int(size * pad), :] = 0
    m[-edge:, :] = 0
    m[:, :edge] = 0
    m[:, -edge:] = 0
    return cv2.GaussianBlur(m, (0, 0), edge * 0.5 + 1)


def main() -> None:
    src, out, args = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
    image = cv2.imread(src, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise SystemExit(json.dumps({"error": f"cannot read {src}"}))
    deep = image.dtype == np.uint16
    work = (image / 257.0).round().astype(np.uint8) if deep else image
    if work.ndim == 2:
        work = cv2.cvtColor(work, cv2.COLOR_GRAY2BGR)
    work = work[:, :, :3]
    session = ort.InferenceSession(args["model"], providers=["CPUExecutionProvider"])
    weight, blend = float(args.get("weight", 0.7)), float(args.get("blend", 0.8))
    h, w = work.shape[:2]
    result = work.astype(np.float32)
    done = 0
    for points in args["faces"]:
        matrix, _ = cv2.estimateAffinePartial2D(np.array(points, np.float32), FFHQ_512, method=cv2.RANSAC, ransacReprojThreshold=100)
        if matrix is None:
            continue
        crop = cv2.warpAffine(work, matrix, (512, 512), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_AREA)
        fixed = restore(session, crop, weight)
        inverse = cv2.invertAffineTransform(matrix)
        back = cv2.warpAffine(fixed, inverse, (w, h), borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        alpha = np.clip(cv2.warpAffine(mask(), inverse, (w, h)), 0, 1)[:, :, None] * blend
        result = result * (1 - alpha) + back * alpha
        done += 1
    final = np.clip(result, 0, 255).round().astype(np.uint8)
    if deep:
        # Only the faces were made at 8 bits: the rest of a 16-bit picture keeps its own values.
        change = np.abs(final.astype(np.int16) - work.astype(np.int16)).max(2, keepdims=True) > 0
        final = np.where(change, final.astype(np.uint16) * 257, image[:, :, :3])
    cv2.imwrite(out, final)
    print(json.dumps({"faces": done, "weight": weight, "blend": blend}))


if __name__ == "__main__":
    main()
