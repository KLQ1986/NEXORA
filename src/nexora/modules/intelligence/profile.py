"""The footage profile (design 2026-10-14): everything that can be known about a recording from measurement and from Apple's
recognisers, beat by beat and for the whole file, before any language model is asked.

A run of `library.profile` draws frames twice a second, has every one of them looked at (people, faces, poses, text, horizon,
salient regions, a classification, a feature print), measures each frame's light, colour, composition and noise, listens to
the sound (kinds of sound, loudness to the EBU R 128 standard, clipping, wind, silence), and joins all of it with the shots
and beats already worked out and the words already heard. What comes out:

- for each beat, a set of fields, every one with its value, its source (`measured`, `recognized`), a confidence worked out
  by code and the evidence it rests on (`profile_beat`);
- stretches of text seen on screen, with when they show and what kind of text they are (`text_spans`);
- stretches of sound of one kind (`sound_events`);
- a profile of the whole file: pacing, the first three seconds, how well it suits each platform, a style card (`asset_profile`).

Every function here is pure: numbers and records in, records out. The `Profile` class at the end runs them as stages.
"""
import difflib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nexora.modules.intelligence import vocab

VERSION = "2"
LOOK_FPS = 2.0                    # frames looked at a second
LOOK_WIDTH = 960                  # wide enough to read the text on a phone held in the frame; at 448 it came out garbled
LEVEL_RATE = 10                   # loudness values a second


def label(value, source: str, confidence: str, **evidence) -> dict:
    out = {"value": value, "source": source, "confidence": confidence}
    out.update({k: v for k, v in evidence.items() if v is not None})
    return out


# ---------------------------------------------------------------------------------------------------------------- pictures
@dataclass
class FrameMeasure:
    """What one frame's pixels say, measured on a small copy of it."""
    brightness: float
    contrast: float
    saturation: float
    warmth: float                  # red over blue of the near-neutral pixels: above 1 is warm
    kelvin: float | None
    noise: float
    symmetry: float
    empty: float                   # share of the frame with little detail
    empty_left: float
    empty_right: float
    sharp_ratio: float | None      # detail inside the salient region over detail outside it
    subject_luma: float | None
    surround_luma: float | None
    palette: list                  # [[hex, share, name], ...]


COLOUR_NAMES = (("đỏ", 0), ("cam", 30), ("vàng", 55), ("xanh lá", 120), ("xanh ngọc", 175), ("xanh dương", 220), ("tím", 275), ("hồng", 330), ("đỏ", 360))


def colour_name(rgb) -> str:
    r, g, b = (float(v) / 255 for v in rgb)
    top, low = max(r, g, b), min(r, g, b)
    if top < 0.16:
        return "đen"
    if top - low < 0.08:
        return "trắng" if top > 0.85 else "xám"
    if top - low < 0.2 and top < 0.55 and r >= g >= b:
        return "nâu"
    if top == r:
        hue = (60 * ((g - b) / (top - low))) % 360
    elif top == g:
        hue = 60 * ((b - r) / (top - low)) + 120
    else:
        hue = 60 * ((r - g) / (top - low)) + 240
    if 15 <= hue <= 45 and top < 0.6:
        return "nâu"
    return min(COLOUR_NAMES, key=lambda c: abs(c[1] - hue))[0]


def palette(pixels: np.ndarray, k: int = 5, rounds: int = 8) -> list:
    """The main colours of a picture and the share of it each covers: k-means over its pixels, seeded evenly through brightness."""
    data = pixels.reshape(-1, 3).astype(np.float32)
    if len(data) == 0:
        return []
    order = np.argsort(data.sum(1))
    centres = data[order[np.linspace(0, len(data) - 1, k).astype(int)]].copy()
    for _ in range(rounds):
        nearest = ((data[:, None, :] - centres[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            members = data[nearest == j]
            if len(members):
                centres[j] = members.mean(0)
    nearest = ((data[:, None, :] - centres[None]) ** 2).sum(-1).argmin(1)
    shares = np.bincount(nearest, minlength=k) / len(data)
    out = []
    for j in np.argsort(-shares):
        if shares[j] < 0.03:
            continue
        rgb = [int(round(v)) for v in centres[j]]
        out.append(["#%02x%02x%02x" % tuple(rgb), round(float(shares[j]), 3), colour_name(rgb)])
    return out


def kelvin(rgb_mean) -> float | None:
    """A correlated colour temperature from the mean colour of the near-neutral pixels (McCamy's approximation). An estimate:
    it tells warm from cold light, not the exact temperature."""
    lin = [(c / 255) / 12.92 if c / 255 <= 0.04045 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in rgb_mean]
    x_ = 0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]
    y_ = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z_ = 0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]
    total = x_ + y_ + z_
    if total <= 1e-6:
        return None
    x, y = x_ / total, y_ / total
    if abs(0.1858 - y) < 1e-6:
        return None
    n = (x - 0.3320) / (0.1858 - y)
    cct = 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33
    return round(float(cct), -1) if 1500 <= cct <= 15000 else None


def measure_frame(rgb: np.ndarray, salient: list | None = None) -> FrameMeasure:
    """Light, colour, composition and noise of one frame given as an RGB array (any size; 448 wide is what is drawn)."""
    img = rgb.astype(np.float32) / 255.0
    luma = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
    h, w = luma.shape
    p5, p95 = np.percentile(luma, [5, 95])
    top, low = img.max(-1), img.min(-1)
    saturation = np.where(top > 1e-6, (top - low) / np.maximum(top, 1e-6), 0.0)
    neutral = (saturation < 0.35) & (luma > 0.15) & (luma < 0.92)
    pick = img[neutral] if neutral.sum() > 0.02 * luma.size else img.reshape(-1, 3)
    mean = pick.mean(0)
    warmth = float(mean[0] / max(mean[2], 1e-3))
    # Noise: the spread of what a small blur takes away, where the picture has no edges to take away.
    blurred = (luma[:-2, :-2] + luma[:-2, 1:-1] + luma[:-2, 2:] + luma[1:-1, :-2] + luma[1:-1, 1:-1] + luma[1:-1, 2:] + luma[2:, :-2] + luma[2:, 1:-1] + luma[2:, 2:]) / 9
    residual = luma[1:-1, 1:-1] - blurred
    gx, gy = np.abs(np.diff(luma, axis=1))[1:-1, :-1], np.abs(np.diff(luma, axis=0))[:-1, 1:-1]
    grad = gx[:, : residual.shape[1]] + gy[: residual.shape[0], :]
    flat = grad < np.percentile(grad, 40)
    noise = float(residual[flat].std() * 255) if flat.sum() > 100 else 0.0
    # Symmetry and empty space on a 16 by 9 grid of detail.
    cells = _cells(grad, 9, 16)
    grid = _cells(luma, 9, 16)
    mirror = np.corrcoef(grid.ravel(), np.fliplr(grid).ravel())[0, 1] if grid.std() > 1e-6 else 1.0
    empty_cells = cells < 0.25 * max(float(cells.mean()), 1e-6)
    sharp_ratio = subject_luma = surround_luma = None
    if salient:
        x, y, bw, bh = salient[0]
        x0, y0, x1, y1 = int(x * w), int(y * h), int((x + bw) * w), int((y + bh) * h)
        inside = np.zeros_like(luma, bool)
        inside[max(y0, 0):max(y1, 1), max(x0, 0):max(x1, 1)] = True
        if 0.02 < inside.mean() < 0.85:
            g_in, g_out = grad[inside[1:-1, 1:-1][: grad.shape[0], : grad.shape[1]]], grad[~inside[1:-1, 1:-1][: grad.shape[0], : grad.shape[1]]]
            if len(g_in) and len(g_out):
                sharp_ratio = round(float((g_in ** 2).mean() / max((g_out ** 2).mean(), 1e-9)), 3)
            subject_luma, surround_luma = round(float(luma[inside].mean()), 3), round(float(luma[~inside].mean()), 3)
    small = rgb[:: max(1, h // 60), :: max(1, w // 106)]
    return FrameMeasure(brightness=round(float(luma.mean()), 3), contrast=round(float(p95 - p5), 3), saturation=round(float(saturation.mean()), 3),
                        warmth=round(warmth, 3), kelvin=kelvin(mean * 255), noise=round(noise, 2),
                        symmetry=round(float(mirror) if not math.isnan(mirror) else 0.0, 3), empty=round(float(empty_cells.mean()), 3),
                        empty_left=round(float(empty_cells[:, :8].mean()), 3), empty_right=round(float(empty_cells[:, 8:].mean()), 3),
                        sharp_ratio=sharp_ratio, subject_luma=subject_luma, surround_luma=surround_luma, palette=palette(small))


def _cells(values: np.ndarray, rows: int, cols: int) -> np.ndarray:
    h, w = values.shape
    values = values[: h - h % rows, : w - w % cols]
    return values.reshape(rows, values.shape[0] // rows, cols, values.shape[1] // cols).mean((1, 3))


# ---------------------------------------------------------------------------------------------------------- people and size
def _area(box) -> float:
    return float(box[2] * box[3])


def people_in(picture: dict) -> dict:
    """People in one looked-at picture: how many, the biggest face and body, poses."""
    faces = [f for f in picture.get("faces") or [] if f.get("confidence", 1) >= 0.5]
    humans = [h for h in picture.get("humans") or [] if h.get("confidence", 1) >= 0.4]
    hands = [h for h in picture.get("hands") or [] if h.get("confidence", 1) >= 0.5]
    # Footage filmed from the operator's own eyes shows hands and no face or body: one or two hands are one person.
    count = max(len(faces), len(humans), (len(hands) + 1) // 2 if hands else 0)
    face_h = max((f["box"][3] for f in faces), default=0.0)
    body_h = max((h["box"][3] for h in humans), default=0.0)
    return {"count": count, "faces": len(faces), "hands": len(hands), "face_height": round(face_h, 3), "body_height": round(body_h, 3),
            "postures": [p for p in (posture(j) for j in picture.get("poses") or []) if p]}


def posture(joints: dict) -> str | None:
    """Standing, sitting, lying or bending, from where the hips, knees, shoulders and ankles are (y grows downwards)."""
    def at(*names):
        pts = [joints[n] for n in names if n in joints]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None
    neck, hip, knee, ankle = at("neck"), at("left_hip", "right_hip", "root"), at("left_knee", "right_knee"), at("left_ankle", "right_ankle")
    if neck is None or hip is None:
        return None
    torso_dx, torso_dy = abs(neck[0] - hip[0]), hip[1] - neck[1]
    if torso_dx > abs(torso_dy) * 1.2:
        return "nằm"
    if torso_dy > 0 and torso_dx > torso_dy * 0.6:
        return "cúi"
    if knee is not None:
        thigh = knee[1] - hip[1]
        if thigh < 0.35 * max(torso_dy, 1e-3):
            return "ngồi"
        if ankle is not None and ankle[1] - knee[1] > 0.3 * max(torso_dy, 1e-3):
            return "đứng"
    return "đứng" if ankle is not None else None


SIZE_RANK = {s: i for i, s in enumerate(vocab.SHOT_SIZES)}


def size_from_people(face_h: float, body_h: float) -> tuple[str, str] | None:
    """How tight the frame is on a person, from how much of its height their face or body fills. Returns (size, confidence)."""
    if face_h >= 0.42:
        return "đặc tả", "high" if face_h >= 0.5 else "medium"
    if face_h >= 0.18:
        return "cận", "high" if face_h >= 0.22 else "medium"
    if body_h >= 0.75 or face_h >= 0.09:
        return "trung", "medium"
    if body_h >= 0.25:
        return "toàn", "medium"
    if body_h > 0:
        return "cực toàn", "medium"
    return None


TEXTY = frozenset({"phone", "computer", "computer_monitor", "laptop", "screenshot", "document", "printed_page", "handwriting", "sign", "street_sign",
                   "billboards", "banner", "book", "magazine", "newspaper", "television", "chalkboard", "whiteboard", "receipt", "menu"})
WIDE_SCENE = frozenset({"sky", "blue_sky", "cloudy", "cityscape", "mountain", "hill", "ocean", "beach", "landscape", "forest", "rice_field", "lake",
                        "river", "desert", "canyon", "night_sky", "sunset_sunrise", "skyscraper", "harbour", "island", "waterfall", "field"})
CLOSE_THINGS = frozenset({"food", "dish", "drink", "beverage", "cup", "mug", "coffee", "plate", "bowl", "flower", "dessert", "cake", "fruit", "hand",
                          "jewelry", "watch", "phone", "document", "printed_page", "handwriting", "computer_keyboard", "texture", "insect"})


def size_from_thing(salient: list) -> tuple[str, str] | None:
    """How tight the frame is on a thing held up to it: by how much of the frame the main salient region fills."""
    if not salient:
        return None
    area = _area(salient[0])
    if area >= 0.45:
        return "đặc tả", "medium"
    if area >= 0.08:
        return "cận", "medium"
    return "trung", "low"


def size_from_scene(classes: list, salient: list) -> tuple[str, str] | None:
    """Without people the size of a frame is read from what it shows: open sky or landscape is wide, one small thing filling the
    frame is close. Never better than medium confidence; a model's answer is the second source."""
    sure = {c for c, p in classes if p >= 0.3}
    if sure & WIDE_SCENE and (not salient or _area(salient[0]) > 0.35):
        return "toàn", "medium"
    if sure & CLOSE_THINGS and salient and len(salient) == 1 and 0.12 <= _area(salient[0]) <= 0.75 and not sure & WIDE_SCENE:
        return "cận", "low"
    return None


def median_size(sizes: list[str]) -> str:
    ranks = sorted(SIZE_RANK[s] for s in sizes)
    return vocab.SHOT_SIZES[ranks[len(ranks) // 2]]


# ----------------------------------------------------------------------------------------------------------------- sound
def sound_events(windows: list[dict], *, hop: float, duration: float | None = None) -> list[dict]:
    """Stretches of one kind of sound. A kind counts in a window when it is among its likeliest and above its bar; a stretch
    needs two windows in a row, so that one window heard wrongly (a smoke alarm in birdsong) makes nothing."""
    hits: dict[str, list[tuple[float, float, float]]] = {}
    for w in windows:
        seen = {}
        for kind, confidence in w.get("top", []):
            name = vocab.SOUND_KINDS.get(kind)
            if name and confidence >= vocab.SOUND_BAR.get(name, vocab.SOUND_BAR_DEFAULT):
                seen[name] = max(seen.get(name, 0.0), confidence)
        for name, confidence in seen.items():
            hits.setdefault(name, []).append((float(w["t"]), float(w["t"]) + float(w.get("d", hop * 2)), confidence))
    events = []
    for name, found in hits.items():
        run = [found[0]]
        for item in found[1:] + [None]:
            if item is not None and item[0] - run[-1][0] <= hop * 1.01 + 1e-6:
                run.append(item)
                continue
            if len(run) >= 2:
                end = run[-1][1] if duration is None else min(run[-1][1], duration)
                mean = sum(r[2] for r in run) / len(run)
                events.append({"kind": name, "start": round(run[0][0], 2), "end": round(end, 2), "confidence": "high" if mean >= 0.8 else "medium",
                               "score": round(mean, 3), "source": "recognized"})
            if item is not None:
                run = [item]
    return sorted(events, key=lambda e: (e["start"], e["kind"]))


def levels(samples: np.ndarray, rate: int) -> dict:
    """Loudness a tenth of a second at a time, in dB of full scale, with the share of samples clipped and the share of the
    sound below 150 Hz (wind on a microphone is almost all low)."""
    step = rate // LEVEL_RATE
    n = len(samples) // step
    if n == 0:
        return {"rms_db": [], "peak_db": [], "clipped": [], "low_share": []}
    blocks = samples[: n * step].reshape(n, step).astype(np.float64)
    rms = np.sqrt((blocks ** 2).mean(1))
    peak = np.abs(blocks).max(1)
    clipped = (np.abs(blocks) >= 0.999).mean(1)
    spectrum = np.abs(np.fft.rfft(blocks * np.hanning(step), axis=1)) ** 2
    freqs = np.fft.rfftfreq(step, 1 / rate)
    low = spectrum[:, (freqs > 20) & (freqs < 150)].sum(1) / np.maximum(spectrum[:, freqs > 20].sum(1), 1e-12)
    db = lambda v: np.round(20 * np.log10(np.maximum(v, 1e-6)), 1)
    return {"rms_db": db(rms).tolist(), "peak_db": db(peak).tolist(), "clipped": np.round(clipped, 4).tolist(), "low_share": np.round(low, 3).tolist()}


def r128_between(momentary: list[float], start: float, end: float) -> float | None:
    """The loudness of a stretch in LUFS, from the momentary values of EBU R 128 (ten a second), averaged as energy."""
    a, b = int(start * LEVEL_RATE), max(int(start * LEVEL_RATE) + 1, int(end * LEVEL_RATE))
    values = [v for v in momentary[a:b] if v is not None and v > -70]
    if not values:
        return None
    return round(10 * math.log10(sum(10 ** (v / 10) for v in values) / len(values)), 1)


# ------------------------------------------------------------------------------------------------------------------ text
def _inside(a, b) -> bool:
    """Whether box `a` lies mostly within box `b`."""
    w, h = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])), max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return a[2] * a[3] > 0 and w * h / (a[2] * a[3]) > 0.5


def _iou(a, b) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    w, h = max(0.0, min(ax1, bx1) - max(a[0], b[0])), max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = w * h
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def text_spans(pictures: list[dict], *, step: float, duration: float, camera_moving=lambda t: False, words: list[dict] | None = None) -> list[dict]:
    """Text read on screen, joined across frames into stretches: what it says, where, from when to when, and what kind of
    text it is. A line read in consecutive frames at about the same place with about the same letters is one stretch."""
    open_spans: list[dict] = []
    done: list[dict] = []
    for k, picture in enumerate(pictures):
        t = k * step
        seen = [x for x in picture.get("text") or [] if x.get("confidence", 0) >= 0.5 and len(x.get("text", "").strip()) >= 2]
        still_open = []
        for span in open_spans:
            match = next((x for x in seen if _iou(x["box"], span["boxes"][-1]) > 0.2 and _same_line(x["text"], span["texts"][-1])), None)
            if match is not None:
                span["texts"].append(match["text"]); span["boxes"].append(match["box"]); span["times"].append(t); span["conf"].append(match["confidence"])
                seen.remove(match)
                still_open.append(span)
            elif t - span["times"][-1] <= step * 1.5:            # one frame missed is allowed
                still_open.append(span)
            else:
                done.append(span)
        for x in seen:
            still_open.append({"texts": [x["text"]], "boxes": [x["box"]], "times": [t], "conf": [x["confidence"]]})
        open_spans = still_open
    done += open_spans
    spans = []
    for span in done:
        if len(span["times"]) == 1 and min(span["conf"]) < 0.9:
            continue                     # read once and not surely: a fragment, most often of text going past or being typed
        # The longest reading that most others agree with: text being typed grows, and its last full form is what was meant.
        text = max(span["texts"], key=lambda t: (sum(_same_line(t, o) for o in span["texts"]), len(t)))
        start, end = max(0.0, span["times"][0] - step / 2), min(duration, span["times"][-1] + step / 2)
        boxes = np.array(span["boxes"])
        box = [round(float(v), 4) for v in boxes.mean(0)]
        moved = float(np.abs(boxes[:, :2] - boxes[0, :2]).max()) if len(boxes) > 1 else 0.0
        kind = text_kind(box, start, end, duration, moved=moved, camera_moved=any(camera_moving(t) for t in span["times"]), text=text, words=words)
        spans.append({"text": text, "start": round(start, 2), "end": round(end, 2), "box": box, "kind": kind,
                      "confidence": "high" if min(span["conf"]) >= 0.8 and len(span["times"]) >= 2 else "medium",
                      "source": "recognized", "frames": len(span["times"]), "size": round(box[3], 4)})
    return sorted(spans, key=lambda s: (s["start"], s["box"][1]))


def _same_line(a: str, b: str) -> bool:
    """Two readings of one line of text: alike, or one the start of the other (a line being typed)."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return False
    short, long = sorted((a, b), key=len)
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.7 or (len(short) >= 4 and long.startswith(short[: max(4, len(short) - 2)]))


def text_kind(box, start: float, end: float, duration: float, *, moved: float, camera_moved: bool, text: str, words: list[dict] | None) -> str:
    """What kind of text a stretch is, from where it sits and how it behaves (design group 10). Text that stays still while the
    camera moves was put on in editing; text that moves with the picture is part of the scene."""
    x, y, w, h = box
    centre_x = x + w / 2
    long_lasting = duration > 0 and (end - start) >= 0.8 * duration
    small_corner = w < 0.3 and h < 0.08 and (centre_x < 0.25 or centre_x > 0.75) and (y < 0.2 or y + h > 0.8)
    if long_lasting and small_corner:
        return "watermark"
    if moved > 0.04 or (camera_moved and moved > 0.015):
        return "chữ trong cảnh"
    if y > 0.62 and abs(centre_x - 0.5) < 0.18 and (end - start) < 12:
        if words and _matches_speech(text, start, end, words):
            return "phụ đề"
        return "phụ đề" if w > 0.25 else "chú thích"
    if y > 0.55 and centre_x < 0.45:
        return "dòng tên"
    if h >= 0.07 and abs(centre_x - 0.5) < 0.2:
        return "tiêu đề"
    return "chữ chèn" if not camera_moved else "chữ trong cảnh"


def _matches_speech(text: str, start: float, end: float, words: list[dict]) -> bool:
    heard = " ".join(w["text"] for w in words if w["end"] >= start - 0.5 and w["start"] <= end + 0.5).lower()
    return bool(heard) and difflib.SequenceMatcher(None, text.lower(), heard).ratio() >= 0.5


def static_marks(stack: np.ndarray) -> list[list[float]]:
    """Places that stay the same in every frame while the rest of the picture changes: a watermark or logo, with or without
    letters. `stack` is frames × height × width of brightness. Returns boxes."""
    if len(stack) < 6:
        return []
    spread = stack.std(0)
    overall = float(np.median(spread))
    if overall < 0.03:                         # the whole picture is still: nothing stands out as fixed
        return []
    fixed = spread < overall * 0.12
    h, w = fixed.shape
    edges = np.abs(np.diff(stack.mean(0), axis=1))[:, :] > 0.08
    fixed[:, :-1] &= edges | np.roll(edges, 1, axis=1)
    boxes = []
    for (r0, r1, c0, c1) in ((0, h // 4, 0, w // 4), (0, h // 4, 3 * w // 4, w), (3 * h // 4, h, 0, w // 4), (3 * h // 4, h, 3 * w // 4, w)):
        part = fixed[r0:r1, c0:c1]
        if part.mean() > 0.02:
            rows, cols = np.nonzero(part)
            boxes.append([round((c0 + cols.min()) / w, 3), round((r0 + rows.min()) / h, 3), round((cols.max() - cols.min() + 1) / w, 3), round((rows.max() - rows.min() + 1) / h, 3)])
    return boxes


# ------------------------------------------------------------------------------------------------------------- one beat
def _confidence_of(value: float, low: float, high: float) -> str:
    return "high" if value <= low or value >= high else "medium"


def profile_beat(start: float, end: float, pictures: list[dict], measures: list[FrameMeasure], *, words: list[dict], events: list[dict],
                 momentary: list[float], audio: dict, camera: str | None, spans: list[dict], log_profile: bool) -> dict:
    """The measured and recognised fields of one beat. `pictures` and `measures` are those of the frames inside it."""
    fields: dict = {}
    if pictures:
        found = [people_in(p) for p in pictures]
        counts = sorted(f["count"] for f in found)
        n = counts[len(counts) // 2]
        name = "không" if n == 0 else "một" if n == 1 else "hai" if n == 2 else "nhóm" if n <= 5 else "đám đông"
        agree = sum(1 for c in counts if c == n) / len(counts)
        fields["people"] = label(name, "recognized", "high" if agree >= 0.8 else "medium", count=n, most=counts[-1],
                                 faces=max(f["faces"] for f in found))
        sizes, how = [], None
        # A body with no face filling the frame, or hands with no face, is most often the one holding the camera; the shot is about
        # what is in their hands. Measured on the operator's footage (0073), neither that body nor the salient region tells close
        # from very close; big hands seen in most frames do mean close. Otherwise this beat is left unmeasured, not guessed.
        holders = [not f["faces"] and (f["hands"] or f["body_height"] >= 0.75) for f in found]
        if sum(holders) > len(found) / 2:
            hands = [max(h["box"][3] for h in p.get("hands") or []) for p in pictures if p.get("hands")]
            if len(hands) >= len(pictures) / 2 and float(np.median(hands)) >= 0.5:
                sizes, how = [("cận", "medium")] * len(pictures), "tay cầm vật"
        else:
            for p, f in zip(pictures, found):
                got = size_from_people(f["face_height"], f["body_height"])
                if got:
                    sizes.append(got); how = "người"
        if not sizes and sum(holders) <= len(found) / 2:
            for p in pictures:
                got = size_from_scene(p.get("classes") or [], p.get("salient") or [])
                if got:
                    sizes.append(got); how = "cảnh"
        if sizes and len(sizes) >= max(1, len(pictures) // 2):
            value = median_size([s for s, _ in sizes])
            conf = "high" if all(c == "high" for _, c in sizes) else ("low" if any(c == "low" for _, c in sizes) else "medium")
            fields["shot_size"] = label(value, "measured", conf, by=how, face_height=max(f["face_height"] for f in found) or None)
        held = sum(1 for p in pictures if any(_iou(h["box"], (p.get("salient") or [[0, 0, 0, 0]])[0]) > 0.05 or _inside(h["box"], (p.get("salient") or [[0, 0, 0, 0]])[0])
                                               for h in p.get("hands") or []))
        if held >= max(2, len(pictures) // 2):
            thing = next((vocab.VISION[c] for c, conf in sorted(((c, conf) for p in pictures for c, conf in p.get("classes") or []), key=lambda x: -x[1])
                          if c in vocab.VISION and c not in ("outdoor", "interior_room", "people", "adult", "sky", "blue_sky")), "vật")
            fields["holding"] = label(["người", "cầm", thing], "measured", "medium", frames=held, note="tay chồng lên vật nổi bật")
        postures = [x for f in found for x in f["postures"]]
        if postures:
            fields["posture"] = label(max(set(postures), key=postures.count), "recognized", "medium")
        classes: dict[str, float] = {}
        for p in pictures:
            for c, conf in p.get("classes") or []:
                classes[c] = classes.get(c, 0.0) + conf / len(pictures)
        ranked = sorted(classes.items(), key=lambda kv: -kv[1])
        vi, en = vocab.vision_tags(ranked)
        fields["scene_tags"] = label(vi[:12], "recognized", "medium", tags_en=en[:8] or None)
        place = "ngoài trời" if classes.get("outdoor", 0) >= 0.4 else ("trong nhà" if max(classes.get("interior_room", 0), classes.get("interior_shop", 0), classes.get("kitchen", 0)) >= 0.3 else None)
        if place:
            fields["place"] = label(place, "recognized", "high" if max(classes.get("outdoor", 0), classes.get("interior_room", 0)) >= 0.7 else "medium")
        animals = sorted({vocab.VISION.get(a["label"].lower(), a["label"].lower()) for p in pictures for a in p.get("animals") or [] if a.get("confidence", 0) >= 0.5})
        if animals:
            fields["animals"] = label(animals, "recognized", "medium")
        horizons = [p["horizon"] for p in pictures if p.get("horizon") is not None]
        if horizons:
            # The horizon is found in some frames and not others, and where the picture has no clear line its angle wanders.
            # It is only trusted when most frames find it and agree about it.
            tilt, spread = float(np.median(horizons)), float(np.std(horizons))
            agreed = len(horizons) >= max(2, len(pictures) // 2) and spread <= 2.0
            fields["horizon"] = label("thẳng" if abs(tilt) <= 3.0 else "nghiêng", "recognized",
                                      ("high" if abs(tilt) <= 1.5 or abs(tilt) >= 6 else "medium") if agreed else "low", degrees=round(tilt, 1), spread=round(spread, 1))
        scores = [p["aesthetic"] for p in pictures if p.get("aesthetic") is not None]
        if scores:
            fields["aesthetic"] = label(round(float(np.mean(scores)), 3), "recognized", "medium", utility=any(p.get("utility") for p in pictures))
        salient = [p["salient"][0] for p in pictures if p.get("salient")]
        if salient:
            box = np.mean(np.array(salient), 0)
            cx, cy = float(box[0] + box[2] / 2), float(box[1] + box[3] / 2)
            thirds = min(math.hypot(cx - a, cy - b) for a in (1 / 3, 2 / 3) for b in (1 / 3, 2 / 3))
            if _area(box) > 0.5:
                placement = "dàn trải"              # the eye is drawn over most of the frame: a view, not a subject placed in it
            else:
                placement = "chính giữa" if abs(cx - 0.5) < 0.08 and abs(cy - 0.5) < 0.1 else ("một phần ba" if thirds < 0.1 else "lệch")
            fields["subject_place"] = label(placement, "measured", "medium", x=round(cx, 3), y=round(cy, 3), area=round(_area(box), 3))
        # Is the person speaking the one in the frame? Their lips move with the words.
        heard = [w for w in words if w["end"] > start and w["start"] < end]
        if heard:
            mouths = [f.get("mouth") for p in pictures for f in (p.get("faces") or [])[:1] if f.get("mouth") is not None]
            if not any(f["faces"] for f in found):
                fields["speaker"] = label("ngoài khung", "measured", "medium", note="có lời nói, không thấy mặt người")
            elif len(mouths) >= 2:
                moving = max(mouths) - min(mouths) >= 0.08 or max(mouths) >= 0.18
                fields["speaker"] = label("trong khung" if moving else "ngoài khung", "measured", "medium", mouth_range=round(max(mouths) - min(mouths), 3))
    if measures:
        m = lambda name: float(np.median([getattr(x, name) for x in measures]))
        brightness, contrast, saturation, warmth, noise = m("brightness"), m("contrast"), m("saturation"), m("warmth"), m("noise")
        key = "tông sáng" if brightness > 0.62 and contrast < 0.7 else ("tông tối" if brightness < 0.3 else "cân bằng")
        fields["light"] = label(key, "measured", _confidence_of(brightness, 0.25, 0.68) if key != "cân bằng" else "medium",
                                brightness=round(brightness, 3), contrast=round(contrast, 3))
        backlit = [x for x in measures if x.subject_luma is not None and x.surround_luma is not None]
        if backlit:
            gap = float(np.median([x.surround_luma - x.subject_luma for x in backlit]))
            fields["backlit"] = label(gap > 0.18, "measured", _confidence_of(abs(gap - 0.18), 0.0, 0.1), gap=round(gap, 3))
        kelvins = [x.kelvin for x in measures if x.kelvin]
        temperature = "ấm" if warmth > 1.12 else ("lạnh" if warmth < 0.9 else "trung tính")
        fields["colour"] = label(temperature, "measured", _confidence_of(abs(warmth - 1.0), 0.03, 0.2), warmth=round(warmth, 3),
                                 kelvin=round(float(np.median(kelvins)), -1) if kelvins else None, saturation=round(saturation, 3),
                                 palette=measures[len(measures) // 2].palette, log=log_profile or None,
                                 look=colour_look(saturation, contrast, warmth, measures[len(measures) // 2].palette, log_profile))
        fields["noise"] = label("tốt" if noise < 2.0 else "chấp nhận được" if noise < 4.0 else "kém", "measured", _confidence_of(noise, 1.2, 5.0), measure=round(noise, 2))
        symmetry, empty = m("symmetry"), m("empty")
        side = "trái" if m("empty_left") - m("empty_right") > 0.15 else ("phải" if m("empty_right") - m("empty_left") > 0.15 else None)
        fields["composition"] = label("đối xứng" if symmetry > 0.85 else ("nhiều khoảng trống" if empty > 0.45 else "thường"), "measured", "medium",
                                      symmetry=round(symmetry, 3), empty=round(empty, 3), space_side=side)
        ratios = [x.sharp_ratio for x in measures if x.sharp_ratio is not None]
        if ratios:
            r = float(np.median(ratios))
            fields["depth"] = label("nông" if r > 4.0 else "sâu", "measured", "medium" if abs(math.log(max(r, 1e-3) / 4.0)) > 0.5 else "low", ratio=round(r, 2))
    inside = [s for s in spans if s["end"] > start and s["start"] < end]
    if inside:
        fields["text"] = label([s["text"] for s in inside][:8], "recognized", "high" if all(s["confidence"] == "high" for s in inside) else "medium",
                               kinds=sorted({s["kind"] for s in inside}))
    overlap = [e for e in events if e["end"] > start and e["start"] < end]
    if overlap:
        share: dict[str, float] = {}
        for e in overlap:
            share[e["kind"]] = share.get(e["kind"], 0.0) + (min(e["end"], end) - max(e["start"], start)) / max(end - start, 1e-3)
        kinds = sorted(share.items(), key=lambda kv: -kv[1])
        fields["sound"] = label([k for k, v in kinds if v >= 0.15][:6], "recognized", "medium", shares={k: round(min(v, 1.0), 2) for k, v in kinds})
        fields["music"] = label(any(k in vocab.MUSIC_KINDS and v >= 0.3 for k, v in kinds), "recognized", "medium")
    loud = r128_between(momentary, start, end)
    if loud is not None or audio.get("rms_db"):
        a, b = int(start * LEVEL_RATE), max(int(start * LEVEL_RATE) + 1, int(end * LEVEL_RATE))
        clipped = audio.get("clipped", [])[a:b]
        low = audio.get("low_share", [])[a:b]
        rms = audio.get("rms_db", [])[a:b]
        fields["loudness"] = label(loud, "measured", "high", peak_db=max(audio.get("peak_db", [])[a:b], default=None),
                                   silent=round(sum(1 for v in rms if v < -50) / len(rms), 2) if rms else None)
        if clipped:
            share_clipped = sum(1 for v in clipped if v > 0.001) / len(clipped)
            fields["clipping"] = label(share_clipped > 0.02, "measured", "high" if share_clipped == 0 or share_clipped > 0.1 else "medium", share=round(share_clipped, 3))
        if low and rms:
            windy = sum(1 for v, r in zip(low, rms) if v > 0.6 and r > -40) / len(low)
            fields["wind"] = label(windy > 0.3, "measured", "medium", share=round(windy, 2))
    if camera:
        fields["camera"] = label(camera, "measured", "high")
    return fields


def colour_look(saturation: float, contrast: float, warmth: float, colours: list, log_profile: bool) -> str:
    """A name for the colour of a stretch, by rule; one of the names a model would otherwise be asked for."""
    if log_profile:
        return "log chưa chỉnh màu"
    if saturation < 0.08:
        return "đơn sắc"
    names = {c[2] for c in colours if c[1] >= 0.12}
    if {"cam", "xanh ngọc"} <= names or {"cam", "xanh dương"} <= names and contrast > 0.6:
        return "điện ảnh xanh cam"
    if saturation > 0.45:
        return "rực rỡ"
    if contrast < 0.45 and saturation < 0.25:
        return "nhạt"
    if warmth > 1.2 and saturation < 0.3:
        return "cổ điển"
    return "tự nhiên"


# ----------------------------------------------------------------------------------------------------------- the whole file
PLATFORMS = {
    "TikTok": {"shape": "dọc", "longest": 60, "safe_bottom": 0.8},
    "Shorts": {"shape": "dọc", "longest": 60, "safe_bottom": 0.82},
    "Reels": {"shape": "dọc", "longest": 90, "safe_bottom": 0.8},
    "YouTube": {"shape": "ngang", "longest": None, "safe_bottom": 0.92},
}
CALLS_TO_ACTION = re.compile(r"đăng ký|theo dõi|bấm (vào )?link|link (ở|dưới)|mua ngay|đặt hàng|inbox|nhắn tin|bình luận|chia sẻ|subscribe|follow|like", re.IGNORECASE)


def asset_profile(*, probe: dict, shots: list[dict], beats: list[dict], words: list[dict], spans: list[dict], events: list[dict],
                  integrated: dict | None, signals_diff: np.ndarray | None, fps: float | None, language: str | None) -> dict:
    """The profile of a whole file: groups 01, 02 (by rule), 11, 12 (measured parts), 13 and 14 of the design."""
    duration = float(probe.get("duration") or (beats[-1]["end"] if beats else 0.0))
    lengths = sorted(s["end"] - s["start"] for s in shots) if shots else []
    pct = lambda q: round(float(np.percentile(lengths, q)), 2) if lengths else None
    transitions: dict[str, int] = {}
    for s in shots[1:]:
        transitions[s.get("transition_in") or "cut"] = transitions.get(s.get("transition_in") or "cut", 0) + 1
    pacing = {"shots": len(shots), "cuts_per_minute": round(max(len(shots) - 1, 0) / max(duration / 60, 1e-3), 2),
              "shot_median": pct(50), "shot_p10": pct(10), "shot_p90": pct(90), "transitions": transitions,
              "slow_motion": bool((probe.get("frame_rate") or 0) >= 100)}
    cut_times = [s["start"] for s in shots[1:]]
    if cut_times and words:
        gaps = [(a["end"], b["start"]) for a, b in zip(words, words[1:]) if b["start"] - a["end"] >= 0.15]
        inside_word = sum(1 for t in cut_times if any(w["start"] < t < w["end"] for w in words))
        at_gap = sum(1 for t in cut_times if any(a - 0.1 <= t <= b + 0.1 for a, b in gaps))
        pacing["cuts_at_pauses"] = round(at_gap / len(cut_times), 2)
        pacing["cuts_inside_words"] = inside_word
        pacing["split_edits"] = sum(1 for t in cut_times if any(w["start"] < t - 0.2 and w["end"] > t + 0.2 for w in words))
    # The first three seconds.
    first_word = next((w["start"] for w in words), None)
    early = [b for b in beats if b["start"] < 3.0]
    faces_early = any((b.get("profile", {}).get("people", {}).get("count") or 0) > 0 for b in early)
    text_early = any(s["start"] < 3.0 for s in spans)
    change = None
    if signals_diff is not None and fps:
        part = signals_diff[: int(3 * fps)]
        change = round(float(part.mean()), 3) if len(part) else None
    hook = {"first_word_at": round(first_word, 2) if first_word is not None else None, "face_in_first_3s": faces_early, "text_in_first_3s": text_early,
            "picture_change": change, "sound_early": sorted({e["kind"] for e in events if e["start"] < 3.0})}
    score = sum([first_word is not None and first_word < 1.5, faces_early, text_early, (change or 0) > 0.08])
    hook["strength"] = ["yếu", "vừa", "vừa", "mạnh", "mạnh"][score]
    said = " ".join(w["text"] for w in words) + " " + " ".join(s["text"] for s in spans)
    calls = sorted({m.group(0).lower() for m in CALLS_TO_ACTION.finditer(said)})
    # Style card.
    def spread(name):
        values = [b.get("profile", {}).get(name, {}).get("value") for b in beats]
        values = [v for v in values if isinstance(v, str)]
        return {v: round(values.count(v) / len(values), 2) for v in sorted(set(values), key=values.count, reverse=True)} if values else {}
    colours: dict[str, float] = {}
    for b in beats:
        for hexv, share, name in (b.get("profile", {}).get("colour", {}).get("palette") or []):
            colours[name] = colours.get(name, 0.0) + share / max(len(beats), 1)
    sat = [b["profile"]["colour"]["saturation"] for b in beats if b.get("profile", {}).get("colour")]
    con = [b["profile"]["light"]["contrast"] for b in beats if b.get("profile", {}).get("light")]
    speech_seconds = sum(w["end"] - w["start"] for w in words)
    music_seconds = sum(e["end"] - e["start"] for e in events if e["kind"] in vocab.MUSIC_KINDS)
    style = {"shot_sizes": spread("shot_size"), "camera": spread("camera"), "colour_temperature": spread("colour"), "look": _looks(beats),
             "palette": {k: round(v, 2) for k, v in sorted(colours.items(), key=lambda kv: -kv[1])[:6]},
             "saturation": round(float(np.median(sat)), 3) if sat else None, "contrast": round(float(np.median(con)), 3) if con else None,
             "speech_share": round(min(speech_seconds / max(duration, 1e-3), 1.0), 2), "music_share": round(min(music_seconds / max(duration, 1e-3), 1.0), 2),
             "loudness_lufs": (integrated or {}).get("integrated"), "cuts_per_minute": pacing["cuts_per_minute"],
             "captions": _caption_style(spans)}
    # Platforms, by rule.
    orientation = probe.get("orientation") or ("dọc" if (probe.get("height") or 0) > (probe.get("width") or 0) else "ngang")
    longest = _longest_clean(beats)
    fit = {}
    for name, rule in PLATFORMS.items():
        reasons = []
        if orientation != rule["shape"] and orientation != "vuông":
            reasons.append(f"khung {orientation}, nền tảng ưa khung {rule['shape']}: cần cắt khung")
        low_text = [s for s in spans if s["kind"] in ("chữ chèn", "tiêu đề", "phụ đề", "dòng tên") and s["box"][1] + s["box"][3] > rule["safe_bottom"]]
        if low_text:
            reasons.append(f"{len(low_text)} dòng chữ nằm trong vùng giao diện của nền tảng che")
        if rule["longest"] and longest < 5:
            reasons.append("không có đoạn sạch liền mạch nào dài từ 5 giây")
        fit[name] = {"fits": "tốt" if not reasons else ("được, cần sửa" if len(reasons) == 1 else "kém"), "reasons": reasons or ["không có trở ngại đo được"],
                     "longest_clean_seconds": round(longest, 1)}
    flawed = sum(1 for b in beats if any(b.get("profile", {}).get(k, {}).get("value") in ("kém", True) for k in ("noise", "clipping", "wind")) or
                 any(b.get("labels", {}).get(k, {}).get("value") == "poor" for k in ("sharpness", "shake", "exposure")))
    watermark = any(s["kind"] == "watermark" for s in spans)
    return {"version": VERSION, "duration": round(duration, 2), "orientation": orientation, "language": language,
            "log_profile": bool(probe.get("log_profile")), "pacing": pacing, "hook": hook, "calls_to_action": calls,
            "style": style, "platforms": fit, "quality": {"beats_with_flaws": flawed, "beats": len(beats), "watermark": watermark},
            "loudness": integrated or {}, "people": {"beats_with_people": sum(1 for b in beats if (b.get("profile", {}).get("people", {}).get("count") or 0) > 0),
                                                    "most": max((b.get("profile", {}).get("people", {}).get("most") or 0 for b in beats), default=0)},
            "text": {"spans": len(spans), "kinds": sorted({s["kind"] for s in spans})},
            "sound": {k: round(sum(e["end"] - e["start"] for e in events if e["kind"] == k), 1) for k in sorted({e["kind"] for e in events})}}


def _looks(beats) -> dict:
    values = [b.get("profile", {}).get("colour", {}).get("look") for b in beats]
    values = [v for v in values if v]
    return {v: round(values.count(v) / len(values), 2) for v in sorted(set(values), key=values.count, reverse=True)} if values else {}


def _caption_style(spans: list[dict]) -> dict | None:
    captions = [s for s in spans if s["kind"] in ("phụ đề", "chú thích")]
    if not captions:
        return None
    return {"count": len(captions), "height": round(float(np.median([s["size"] for s in captions])), 4),
            "position_y": round(float(np.median([s["box"][1] for s in captions])), 3)}


def _longest_clean(beats: list[dict]) -> float:
    best = run = 0.0
    last_end = None
    for b in beats:
        bad = any(b.get("labels", {}).get(k, {}).get("value") == "poor" for k in ("sharpness", "shake", "exposure"))
        if bad or (last_end is not None and b["start"] - last_end > 0.05):
            run = 0.0
        if not bad:
            run += b["end"] - b["start"]
            best = max(best, run)
        last_end = b["end"]
    return best


def detect_log(probe: dict, measures: list[FrameMeasure]) -> bool:
    """Footage recorded flat for grading (D-Log, D-Log M, HLG left ungraded): low contrast and low colour throughout, from a
    camera that records ten bits. Ordinary footage of a grey day is low contrast but rarely ten-bit and colourless together."""
    if not measures:
        return False
    contrast = float(np.median([m.contrast for m in measures]))
    saturation = float(np.median([m.saturation for m in measures]))
    ten_bit = (probe.get("bit_depth") or 8) >= 10
    return (ten_bit and contrast < 0.5 and saturation < 0.2) or (contrast < 0.35 and saturation < 0.12)


# --------------------------------------------------------------------------------------------------- checks against a model
def cross_checks(fields: dict, detail: dict, labels: dict, *, has_audio: bool) -> list[dict]:
    """Where a model's description of a beat disagrees with what was measured or recognised (design section 8.5). Each is a
    flag for the review queue; nothing is changed by it."""
    flags = []
    said = " ".join(str(v) for v in (detail.get("mo_ta"), detail.get("boi_canh"), " ".join(map(str, detail.get("chu_the") or [])))).lower()
    size = fields.get("shot_size")
    model_size = vocab.canonical(detail.get("co_canh") or "")
    if size and model_size in SIZE_RANK and abs(SIZE_RANK[size["value"]] - SIZE_RANK[model_size]) > 1:
        flags.append({"rule": "cỡ cảnh", "message": f"mô hình nói {model_size}, đo được {size['value']}"})
    people = fields.get("people")
    model_people = detail.get("so_nguoi")
    if people and model_people:
        model_people = vocab.canonical(str(model_people))
        if (people["count"] == 0) != (model_people == "không") and people["confidence"] == "high":
            flags.append({"rule": "số người", "message": f"mô hình nói {model_people}, nhận diện được {people['count']} người"})
    place = fields.get("place")
    model_place = vocab.canonical(detail.get("noi_chon") or "")
    if place and model_place in vocab.PLACES and model_place != place["value"] and place["confidence"] == "high":
        flags.append({"rule": "nơi chốn", "message": f"mô hình nói {model_place}, nhận diện được {place['value']}"})
    camera = (labels.get("camera") or {}).get("value")
    if camera and camera != "static" and re.search(r"máy (quay )?(đứng yên|cố định)|khung hình tĩnh", said):
        flags.append({"rule": "chuyển động máy", "message": f"mô tả nói máy đứng yên, số đo nói {camera}"})
    if camera == "static" and re.search(r"(máy|camera) (di chuyển|lia|quay sang)", said):
        flags.append({"rule": "chuyển động máy", "message": "mô tả nói máy chuyển động, số đo nói máy tĩnh"})
    if not has_audio and re.search(r"(nói|kể|thuyết minh|tiếng)", str(detail.get("mo_ta", "")).lower()):
        flags.append({"rule": "lời nói", "message": "mô tả nhắc tới tiếng hoặc lời nói, file không có tiếng"})
    text = fields.get("text")
    model_text = str(detail.get("chu_tren_hinh") or "").strip()
    if model_text and not text:
        flags.append({"rule": "chữ trên hình", "message": f"mô hình đọc được \"{model_text[:40]}\", máy đọc chữ không thấy chữ nào"})
    music = fields.get("music")
    if music is not None and not music["value"] and "nhạc" in said:
        flags.append({"rule": "âm thanh", "message": "mô tả nhắc tới nhạc, máy nghe không thấy nhạc"})
    foreign = vocab.foreign_words(" ".join(str(v) for v in (detail.get("mo_ta"), detail.get("boi_canh"), *(detail.get("chu_the") or []))))
    if foreign:
        flags.append({"rule": "ngôn ngữ", "message": "câu trả lời có từ ngoài tiếng Việt: " + ", ".join(foreign[:5])})
    turning = (fields.get("turning") or {}).get("value")
    if camera == "static" and turning is not None and turning > 15:
        flags.append({"rule": "chuyển động máy", "message": f"hình cho thấy máy đứng yên, cảm biến ghi máy xoay {turning} độ/giây"})
    angle = fields.get("angle")
    model_angle = vocab.canonical(detail.get("goc_may") or "")
    if angle and model_angle in vocab.ANGLES and model_angle in ("từ trên xuống", "từ dưới lên", "ngang tầm") and model_angle != angle["value"]:
        flags.append({"rule": "góc máy", "message": f"mô hình nói {model_angle}, cảm biến máy đo {angle['value']} ({angle.get('pitch')}°)"})
    if (labels.get("sharpness") or {}).get("value") == "poor" or (labels.get("shake") or {}).get("value") == "poor":
        flags.append({"rule": "chất lượng thấp", "message": "nhịp mất nét hoặc rung nặng: mô tả có thể không đáng tin"})
    return flags


# ----------------------------------------------------------------------------------------------- events (design group 07)
EDGE = 0.5                        # seconds: an event this close to the edge of its shot was cut off there


def _acts(detail: dict) -> set[str]:
    out = set()
    for a in detail.get("hanh_dong") or []:
        verb = vocab.canonical(a.get("lam_gi", "") if isinstance(a, dict) else str(a))
        if verb:
            out.add(verb)
    return out


def events_of(beats: list[dict], shots: list[dict], motion=None, series: tuple | None = None) -> list[dict]:
    """Join beats in a row, in the same shot, that show the same action into one event with a start, a peak and an end
    (design 10-13, section 7). `beats`: {start, end, shot, detail} in order. `motion(start, end)`: how much the subject moves
    in a stretch, measured; the beat that moves most is the peak. An event that touches the start or end of its shot was cut
    off there. A beat with no action is no event."""
    events, current = [], None
    for beat in beats:
        acts = _acts(beat.get("detail") or {})
        if current and acts and beat.get("shot") == current["shot"] and acts & current["acts"]:
            current["beats"].append(beat)
            current["acts"] &= acts if acts & current["acts"] else current["acts"]
            continue
        if current:
            events.append(current)
        current = {"shot": beat.get("shot"), "acts": set(acts), "beats": [beat]} if acts else None
    if current:
        events.append(current)
    out = []
    for e in events:
        first, last = e["beats"][0], e["beats"][-1]
        shot = shots[e["shot"]] if e["shot"] is not None and e["shot"] < len(shots) else {"start": first["start"], "end": last["end"]}
        moving = [(motion(b["start"], b["end"]) if motion else 0.0, b) for b in e["beats"]]
        peak = max(moving, key=lambda m: m[0])[1] if motion and len(moving) > 1 else e["beats"][len(e["beats"]) // 2]
        who = next((a.get("ai") for b in e["beats"] for a in (b.get("detail") or {}).get("hanh_dong") or [] if isinstance(a, dict) and a.get("ai")), "")
        what = sorted(e["acts"])
        exact = refine_bounds(first["start"], last["end"], *series) if series is not None else None
        out.append({"start": first["start"], "end": last["end"], "shot": e["shot"], "who": who, "actions": what, "beats": len(e["beats"]),
                    "moving_from": exact[0] if exact else None, "moving_to": exact[1] if exact else None,
                    "phases": {"bắt đầu": [first["start"], first["end"]], "cao trào": [peak["start"], peak["end"]], "kết thúc": [last["start"], last["end"]]},
                    "cut_start": first["start"] - shot["start"] <= EDGE,
                    "cut_end": shot["end"] - last["end"] <= EDGE, "source": "measured+model"})
    return out


# ------------------------------------------------------------------------- pictures alike, scenes across files (groups 03, 15)
def beat_print(prints: np.ndarray, step: float, start: float, end: float) -> np.ndarray | None:
    """One feature print for a beat: the mean of its frames' prints, made unit length."""
    if prints is None or not len(prints):
        return None
    k0, k1 = int(math.ceil(start / step - 1e-6)), int(math.floor((end - 1e-6) / step))
    rows = prints[max(k0, 0):min(k1 + 1, len(prints))].astype(np.float32)
    rows = rows[np.abs(rows).sum(1) > 0]
    if not len(rows):
        return None
    v = rows.mean(0)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


SCENE_GAP = 600.0                 # seconds between two recordings beyond which they are two scenes, whatever they show
SCENE_SPLIT = 1.0                 # a boundary score at or above this opens a new scene


def scene_boundary(a: dict, b: dict) -> tuple[float, list[str]]:
    """How much two consecutive beats of a shoot (in the order they were filmed) look like the end of one scene and the start
    of another, and why. Each beat: {at (seconds since the shoot began), end, print, place, tags, asset_id}."""
    score, why = 0.0, []
    gap = b["at"] - a["end_at"]
    if gap > SCENE_GAP:
        return 9.0, [f"cách nhau {round(gap / 60)} phút"]
    if a.get("place") and b.get("place") and a["place"] != b["place"]:
        score += 0.8; why.append("đổi nơi chốn")
    if a.get("print") is not None and b.get("print") is not None:
        alike = float(a["print"] @ b["print"])
        if alike < 0.55:
            score += 0.6; why.append("hình khác hẳn")
        elif alike < 0.7:
            score += 0.3
    ta, tb = set(a.get("tags") or []), set(b.get("tags") or [])
    if ta and tb and len(ta & tb) / len(ta | tb) < 0.25:
        score += 0.4; why.append("đổi chủ thể")
    if a["asset_id"] != b["asset_id"] and gap > 120:
        score += 0.3; why.append("file khác, cách vài phút")
    return score, why


def scenes_of(beats: list[dict]) -> list[dict]:
    """Group the beats of a shoot, in filming order, into scenes. Returns scenes with their beats and why each began."""
    out: list[dict] = []
    for beat in beats:
        if out:
            score, why = scene_boundary(out[-1]["beats"][-1], beat)
            if score < SCENE_SPLIT:
                out[-1]["beats"].append(beat)
                continue
        else:
            why = ["đầu buổi quay"]
        out.append({"beats": [beat], "why": why})
    for scene in out:
        tags: dict[str, int] = {}
        for b in scene["beats"]:
            for t in (b.get("tags") or [])[:6]:
                tags[t] = tags.get(t, 0) + 1
        top = [t for t, _ in sorted(tags.items(), key=lambda kv: -kv[1]) if t not in ("ngoài trời", "trong nhà", "bầu trời")][:4]
        places = {b.get("place") for b in scene["beats"] if b.get("place")}
        scene["name"] = (", ".join(sorted(places)) + ": " if places else "") + (", ".join(top) if top else "cảnh")
        scene["assets"] = sorted({b["asset_id"] for b in scene["beats"]}, key=lambda a: next(b["at"] for b in scene["beats"] if b["asset_id"] == a))
    return out


SAME_FACE = 0.80                  # likeness of two face prints above which they are taken for one person; a guess until labels measure it


def group_faces(prints: np.ndarray, *, same: float = SAME_FACE) -> list[list[int]]:
    """Faces grouped into people: each face joins the group whose centre it is most like, if like enough, else starts one."""
    groups: list[list[int]] = []
    centres: list[np.ndarray] = []
    for i, v in enumerate(prints):
        if centres:
            likeness = np.array([float(c @ v) for c in centres])
            best = int(likeness.argmax())
            if likeness[best] >= same:
                groups[best].append(i)
                c = prints[groups[best]].mean(0)
                centres[best] = c / (np.linalg.norm(c) + 1e-9)
                continue
        groups.append([i])
        centres.append(v)
    return groups


# ------------------------------------------------------------------------------- following things through a shot (group 06)
def tracks_of(pictures: list[dict], *, step: float, shots: list[dict], kinds=("humans", "faces", "hands", "animals")) -> list[dict]:
    """People, faces, hands and animals followed from frame to frame inside each shot: a box in one frame continues the track
    whose last box it overlaps most (at least a fifth), one frame may be missed. A track never crosses a cut."""
    out = []
    for kind in kinds:
        open_tracks: list[dict] = []
        for k, picture in enumerate(pictures):
            t = k * step
            shot = next((i for i, s in enumerate(shots) if s["start"] <= t < s["end"]), None)
            boxes = [x["box"] for x in picture.get(kind) or [] if x.get("confidence", 1) >= 0.4 and x.get("box")]
            still = []
            for tr in open_tracks:
                if tr["shot"] != shot or t - tr["times"][-1] > step * 2.01:
                    out.append(tr)
                    continue
                best = max(boxes, key=lambda b: _iou(b, tr["boxes"][-1]), default=None)
                if best is not None and _iou(best, tr["boxes"][-1]) >= 0.2:
                    tr["boxes"].append(best); tr["times"].append(t); boxes.remove(best)
                still.append(tr)
            open_tracks = still + [{"kind": kind, "shot": shot, "boxes": [b], "times": [t]} for b in boxes]
        out += open_tracks
    made = []
    for tr in out:
        if len(tr["times"]) < 2:
            continue
        first, last = tr["boxes"][0], tr["boxes"][-1]
        dx = (last[0] + last[2] / 2) - (first[0] + first[2] / 2)
        made.append({"kind": tr["kind"], "shot": tr["shot"], "start": round(tr["times"][0], 2), "end": round(tr["times"][-1] + step, 2), "frames": len(tr["times"]),
                     "first_box": first, "last_box": last, "moves": "trái sang phải" if dx > 0.15 else "phải sang trái" if dx < -0.15 else "tại chỗ",
                     "grows": round(last[2] * last[3] / max(first[2] * first[3], 1e-6), 2), "source": "recognized"})
    return sorted(made, key=lambda x: (x["start"], x["kind"]))


def refine_bounds(start: float, end: float, motion: np.ndarray, fps: float, *, quiet: float = 0.25) -> tuple[float, float]:
    """The instant an action starts and stops, to a tenth of a second: inside [start, end], where the subject's movement first
    rises above, and last stays above, a share `quiet` of its peak there. Unchanged when nothing moves."""
    a, b = int(start * fps), max(int(start * fps) + 1, int(end * fps))
    part = motion[a:b]
    if not len(part) or float(part.max()) <= 1e-6:
        return start, end
    above = np.nonzero(part >= quiet * float(part.max()))[0]
    return round((a + above[0]) / fps, 1), round(min(end, (a + above[-1] + 1) / fps), 1)


def has_content_credentials(path, *, reach: int = 8 * 1024 * 1024) -> bool:
    """Whether a file carries C2PA content credentials (design group 16): their store is labelled "c2pa" in a box near the
    start or the end of the file. Only their presence is read here; checking their signature needs the C2PA tools."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(min(reach, size))
            if b"c2pa" in head:
                return True
            if size > reach:
                f.seek(max(0, size - reach))
                return b"c2pa" in f.read(reach)
    except OSError:
        return False
    return False


# ----------------------------------------------------------------- what the channel's own figures say (design group 12)
MIN_VIDEOS = 5


def what_works(videos: list[dict]) -> dict:
    """Which measured traits of the footage used in published videos go with videos watched longer. `videos`: {retention
    (share of the video watched on average), traits: {name: value}}. Below five videos nothing is claimed; a trait is only
    compared when at least two videos have it and two do not. These are associations on the operator's own channel, not causes."""
    if len(videos) < MIN_VIDEOS:
        return {"videos": len(videos), "enough": False, "findings": []}
    findings = []
    names = {(k, str(v)) for x in videos for k, v in x["traits"].items()}
    for name, value in sorted(names):
        have = [x["retention"] for x in videos if str(x["traits"].get(name)) == value]
        rest = [x["retention"] for x in videos if str(x["traits"].get(name)) != value]
        if len(have) >= 2 and len(rest) >= 2:
            gap = sum(have) / len(have) - sum(rest) / len(rest)
            findings.append({"trait": name, "value": value, "with": len(have), "without": len(rest), "retention_with": round(sum(have) / len(have), 3),
                             "retention_without": round(sum(rest) / len(rest), 3), "difference": round(gap, 3)})
    findings.sort(key=lambda f: -abs(f["difference"]))
    return {"videos": len(videos), "enough": True, "findings": findings[:12]}


def template_from_style(whole: dict, name: str) -> dict:
    """A format template made from the style of a recording (design group 13): its shape, where and how big its captions sit,
    how present its music is, and, as notes the editing follows, its pace, its usual size of frame and its colour."""
    style = whole.get("style") or {}
    captions = style.get("captions") or {}
    y = captions.get("position_y")
    position = "bottom" if y is None or y >= 0.6 else ("top" if y < 0.33 else "middle")
    scale = round(max(0.7, min(1.6, (captions.get("height") or 0.05) / 0.05)), 2)
    shape = {"dọc": "portrait", "vuông": "square"}.get(whole.get("orientation"), "landscape")
    sizes = style.get("shot_sizes") or {}
    return {"name": name.strip(), "format": shape, "voice": "", "music_gain": 0.5 if (style.get("music_share") or 0) > 0.5 else 0.35, "auto_accept": False,
            "caption_scale": scale, "caption_position": position, "typeface": "sans", "caption_colour": None, "logo_path": "", "pronounce": {},
            "style": {"cuts_per_minute": style.get("cuts_per_minute"), "shot_size": max(sizes, key=sizes.get) if sizes else None,
                      "look": max(style.get("look") or {"tự nhiên": 1}, key=(style.get("look") or {"tự nhiên": 1}).get), "loudness_lufs": style.get("loudness_lufs")}}
