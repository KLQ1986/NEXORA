"""What the camera itself recorded about each frame (design 2026-10-14, section 4.5): DJI cameras keep a protobuf record per frame
in a data stream ("CAM meta"). Read without its schema, by the wire format, the fields used are:

  3.2.9  {1..4}   the camera's orientation as a quaternion (w, x, y, z)
  3.2.10 {2..4}   the direction of gravity in the camera's frame, unit length
  3.2.3  {1}      ISO;  3.2.6 {1} white balance in kelvin

Which axis is which was found by comparing recordings whose framing is known: footage looking down at a desk has gravity's
second component near -0.9, looking up into a coconut palm near +0.5, level footage near 0. So that component is the sine of
the camera's pitch; the third, against the fourth, gives its roll. These are the camera's own sensors, the most reliable
measure of camera angle and movement there is; footage from other cameras simply has none.
"""
import math
import struct


def _varint(b: bytes, i: int) -> tuple[int, int]:
    v = s = 0
    while True:
        x = b[i]
        i += 1
        v |= (x & 0x7F) << s
        s += 7
        if x < 0x80:
            return v, i


def _fields(b: bytes) -> list[tuple[int, int, object]]:
    i, out = 0, []
    try:
        while i < len(b):
            key, i = _varint(b, i)
            f, t = key >> 3, key & 7
            if t == 0:
                v, i = _varint(b, i)
            elif t == 1:
                v, i = b[i:i + 8], i + 8
            elif t == 5:
                v, i = struct.unpack("<f", b[i:i + 4])[0], i + 4
            elif t == 2:
                n, i = _varint(b, i)
                v, i = b[i:i + n], i + n
            else:
                break
            out.append((f, t, v))
    except (IndexError, struct.error):
        pass
    return out


def _get(b, *path):
    for f in path:
        if not isinstance(b, (bytes, bytearray)):
            return None
        hit = [v for g, _, v in _fields(b) if g == f]
        if not hit:
            return None
        b = hit[0]
    return b


def _floats(b) -> dict[int, float]:
    return {f: v for f, t, v in _fields(b) if t == 5} if isinstance(b, (bytes, bytearray)) else {}


def frames(packets: list[bytes]) -> list[dict]:
    """One record per frame: pitch and roll in degrees (up and clockwise positive), the orientation quaternion, ISO and white balance."""
    out = []
    for pkt in packets:
        frame = _get(pkt, 3, 2)
        if frame is None:
            continue
        q, g = _floats(_get(frame, 9)), _floats(_get(frame, 10))
        gy, gz, gw = g.get(2, 0.0), g.get(3, 0.0), g.get(4, 0.0)
        if not g:
            continue
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, gy))))
        roll = math.degrees(math.atan2(gz, -gw)) if abs(gw) > 1e-6 or abs(gz) > 1e-6 else 0.0
        wb = dict((f, v) for f, t, v in _fields(_get(frame, 6) or b"") if t == 0).get(1)
        out.append({"pitch": round(pitch, 2), "roll": round(roll, 2), "q": [q.get(k, 0.0) for k in (1, 2, 3, 4)], "iso": _floats(_get(frame, 3)).get(1), "wb": wb})
    return out


def turn_rate(a: list[float], b: list[float], seconds: float) -> float:
    """Degrees a second the camera turned between two orientations."""
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2 * math.acos(min(1.0, dot))) / seconds if seconds > 0 else 0.0


def beat_fields(records: list[dict], fps: float, start: float, end: float) -> dict:
    """The camera's angle, tilt and turning in one beat, measured by its own sensors."""
    a, b = int(start * fps), max(int(start * fps) + 1, int(end * fps))
    part = records[a:b]
    if not part:
        return {}
    pitch = sorted(r["pitch"] for r in part)[len(part) // 2]
    roll = sorted(r["roll"] for r in part)[len(part) // 2]
    step = max(1, int(fps / 5))
    rates = [turn_rate(part[i]["q"], part[i + step]["q"], step / fps) for i in range(0, len(part) - step, step)]
    rate = sorted(rates)[len(rates) // 2] if rates else 0.0
    angle = "từ trên xuống" if pitch <= -25 else ("từ dưới lên" if pitch >= 20 else "ngang tầm")
    sure = "high" if abs(pitch - (-25 if pitch < 0 else 20)) > 8 or angle == "ngang tầm" and abs(pitch) < 12 else "medium"
    return {"angle": {"value": angle, "source": "measured", "confidence": sure, "pitch": round(pitch, 1), "by": "cảm biến máy"},
            "tilt": {"value": "nghiêng" if abs(roll) > 4 else "thẳng", "source": "measured", "confidence": "high" if abs(abs(roll) - 4) > 2 else "medium", "degrees": round(roll, 1), "by": "cảm biến máy"},
            "turning": {"value": round(rate, 1), "source": "measured", "confidence": "high", "unit": "độ/giây", "by": "cảm biến máy"},
            "exposure_settings": {"value": {"iso": part[0].get("iso"), "white_balance": part[0].get("wb")}, "source": "measured", "confidence": "high"}}
