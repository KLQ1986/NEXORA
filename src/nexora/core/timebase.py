"""Exact media time: every boundary is a whole number of ticks.

One second is 254 016 000 000 ticks. That number divides evenly by every usual frame rate (23.976, 24, 25, 29.97, 30, 50,
59.94, 60, 120) and every usual audio sample rate (8 kHz to 192 kHz, the 44.1 kHz family included), so a boundary that
falls on a frame or a sample is stored without rounding and never drifts. Seconds as a decimal number remain what is shown
and what older records hold; they are derived from ticks, never the other way round once a boundary has been placed.

The unit is the one FilmCraft uses (crates/time), taken as an idea, not as code.
"""
from fractions import Fraction

TICKS_PER_SECOND = 254_016_000_000


def to_ticks(seconds: float) -> int:
    return round(seconds * TICKS_PER_SECOND)


def to_seconds(ticks: int, places: int = 3) -> float:
    return round(ticks / TICKS_PER_SECOND, places)


def frame_ticks(rate: float) -> int:
    """How long one frame lasts at `rate` frames a second. Rates written as 29.97 or 23.976 mean 30000/1001 and 24000/1001."""
    if rate <= 0:
        return 0
    nearest = round(rate)
    exact = Fraction(nearest * 1000, 1001) if abs(rate - nearest * 1000 / 1001) < 0.005 and abs(rate - nearest) > 0.005 else Fraction(rate).limit_denominator(1000)
    return round(TICKS_PER_SECOND / exact)


def frame_time(index: int, rate: float) -> int:
    """The tick at which frame `index` of a constant-rate stream begins."""
    nearest = round(rate)
    exact = Fraction(nearest * 1000, 1001) if abs(rate - nearest * 1000 / 1001) < 0.005 and abs(rate - nearest) > 0.005 else Fraction(rate).limit_denominator(1000)
    return round(Fraction(index * TICKS_PER_SECOND) / exact) if exact > 0 else 0


# ----------------------------------------------------------------------------------------------- SMPTE timecode (EDL, design 9 G)
def _nominal(rate: float) -> int:
    return int(round(rate))


def is_drop(rate: float) -> bool:
    """29.97 and 59.94 count in drop-frame timecode: frame numbers are skipped so that the clock keeps to real time."""
    return abs(rate * 1001 / 1000 - round(rate * 1001 / 1000)) < 0.01 and round(rate * 1001 / 1000) in (30, 60) and abs(rate - round(rate)) > 0.001


def timecode_frames(tc: str, rate: float) -> int:
    """The frame count of a timecode "HH:MM:SS:FF" (or ";FF", drop-frame)."""
    h, m, s, f = (int(x) for x in tc.replace(";", ":").replace(".", ":").split(":"))
    base = _nominal(rate)
    frames = ((h * 60 + m) * 60 + s) * base + f
    if is_drop(rate):
        drop = 2 * (base // 30)
        minutes = h * 60 + m
        frames -= drop * (minutes - minutes // 10)
    return frames


def frames_timecode(frames: int, rate: float) -> str:
    """A frame count as a timecode, drop-frame (";") at 29.97 and 59.94."""
    base = _nominal(rate)
    if is_drop(rate):
        drop = 2 * (base // 30)
        per_10 = base * 600 - drop * 9
        per_min = base * 60 - drop
        tens, rest = divmod(frames, per_10)
        frames += drop * 9 * tens + (drop * ((rest - drop) // per_min) if rest > drop else 0)
    f = frames % base
    s = frames // base
    return f"{s // 3600 % 24:02d}:{s // 60 % 60:02d}:{s % 60:02d}{';' if is_drop(rate) else ':'}{f:02d}"
