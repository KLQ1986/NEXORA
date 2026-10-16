"""Scores by dimension and the defect map, shot by shot (Visual Quality, design 2026-10-16 §3.1: Assessor, DefectMapper).

Measured on the picture as it will be shown: after the colour transform the profile chose, so that a log source is judged
on its graded look, not on its flat one. Each shot gets a score per dimension and a list of defects, each with a severity
from 0 to 1 and, for those that sit in one part of the frame, the cells of a 4×4 grid where they are.
"""
from dataclasses import dataclass

import numpy as np

from nexora.modules.visual_quality import measure as M
from nexora.third_party.basicsr.metrics import calculate_niqe

VERSION = "1"

# Where a measure starts to be a defect (moderate) and where it is severe; on the display picture at about 960 wide.
THRESHOLDS = {
    "noise": (2.5, 6.0),               # sigma, 0..255
    "soft": (30.0, 8.0),               # Laplacian variance: below is soft (reversed)
    "blocking": (1.35, 1.9),           # block edge ratio
    "banding": (0.12, 0.3),
    "underexposed": (0.28, 0.15),      # median luma: below is dark (reversed)
    "overexposed": (0.02, 0.08),       # share clipped high
    "crushed": (0.04, 0.12),           # share clipped low
    "flicker": (1.2, 3.0),             # luma jitter, 0..255
    "shake": (1.5, 4.0),               # px of jitter at 480 wide
    "cast": (0.06, 0.14),              # departure of red/green or blue/green from 1
    "dull": (0.11, 0.06),              # saturation: below is dull (reversed)
    "flat": (0.32, 0.22),              # contrast: below is flat (reversed)
}


def severity(kind: str, value: float) -> float:
    lo, hi = THRESHOLDS[kind]
    if hi >= lo:
        return float(np.clip((value - lo) / (hi - lo + 1e-9), 0.0, 1.0)) if value > lo else 0.0
    return float(np.clip((lo - value) / (lo - hi + 1e-9), 0.0, 1.0)) if value < lo else 0.0


@dataclass
class ShotScore:
    t_start: float
    t_end: float
    look: M.Look
    flicker: float
    shake: float
    niqe: float | None

    def scores(self) -> dict:
        lk = self.look
        return {"exposure": round(lk.luma_p50, 3), "contrast": round(lk.contrast, 3), "saturation": round(lk.saturation, 3),
                "clipped_high": round(lk.clipped_high, 4), "clipped_low": round(lk.clipped_low, 4), "noise": round(lk.noise, 2),
                "sharpness": round(lk.sharpness, 1), "blockiness": round(lk.blockiness, 3), "banding": round(lk.banding, 3),
                "white_balance": [round(lk.cast_r, 3), round(lk.cast_b, 3)], "flicker": round(self.flicker, 2), "shake": round(self.shake, 2),
                "niqe": None if self.niqe is None else round(self.niqe, 2)}


def defects_of(shot: ShotScore, *, content: str, frame: np.ndarray | None = None) -> list[dict]:
    """What is wrong with a shot, worst first. Screens and graphics are not held to camera measures (no noise, no softness)."""
    lk = shot.look
    raw = {"noise": lk.noise, "soft": lk.sharpness, "blocking": lk.blockiness, "banding": lk.banding, "underexposed": lk.luma_p50,
           "overexposed": lk.clipped_high, "crushed": lk.clipped_low, "flicker": shot.flicker, "shake": shot.shake,
           "cast": max(abs(lk.cast_r - 1.0), abs(lk.cast_b - 1.0)), "dull": lk.saturation, "flat": lk.contrast}
    if content in ("screen", "graphics"):
        for k in ("noise", "soft", "shake", "cast", "dull", "flat"):
            raw.pop(k)
    if content == "still":
        for k in ("flicker", "shake"):
            raw.pop(k)
    out = []
    for kind, value in raw.items():
        s = severity(kind, value)
        if s > 0:
            d = {"t_start": shot.t_start, "t_end": shot.t_end, "kind": kind, "severity": round(s, 3), "value": round(float(value), 4)}
            if frame is not None and kind in ("noise", "underexposed", "overexposed", "soft", "blocking"):
                measure = {"noise": lambda p: M.noise_sigma(M.luma(p)), "underexposed": lambda p: float(np.median(M.luma(p))),
                           "overexposed": lambda p: float((M.luma(p) > 0.985).mean()), "soft": lambda p: M.laplacian_variance(M.luma(p)),
                           "blocking": lambda p: M.blockiness(M.luma(p))}[kind]
                d["region"] = M.grid_map(frame, measure)
            out.append(d)
    return sorted(out, key=lambda d: -d["severity"])


def niqe_of(frame: np.ndarray) -> float | None:
    """NIQE of a frame (lower is more natural), on its centre at up to 768×768; None when too small to say."""
    h, w = frame.shape[:2]
    if min(h, w) < 192:
        return None
    s = min(768, h, w)
    crop = frame[(h - s) // 2:(h + s) // 2, (w - s) // 2:(w + s) // 2]
    import warnings
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)          # a flat block (sky, wall) has no texture to describe
            q = float(calculate_niqe(crop * 255.0))
        return q if np.isfinite(q) else None
    except (ValueError, np.linalg.LinAlgError):
        return None
