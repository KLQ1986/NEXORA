"""Lining up two recordings of the same event by their sound (design v4.0, multi-camera footage).

Each camera hears the same room, so the loudness of one, slid along the other, fits best at exactly the time the two started apart.
"""
import math


def _shape(env: list[float]) -> list[float]:
    """Keep what changes: the level around its mean. Steady noise then counts for nothing and events count for a lot."""
    mean = sum(env) / len(env)
    return [v - mean for v in env]


def _score(a: list[float], b: list[float], lag: int, least: int) -> float | None:
    """How alike a[i] and b[i + lag] are over the part where both exist (-1 to 1)."""
    start, end = max(0, -lag), min(len(a), len(b) - lag)
    if end - start < least:
        return None
    xs, ys = a[start:end], b[start + lag:end + lag]
    power = math.sqrt(sum(x * x for x in xs) * sum(y * y for y in ys))
    return sum(x * y for x, y in zip(xs, ys)) / power if power else None


def best_offset(a: list[float], b: list[float], rate: int, *, max_lag_seconds: float = 120.0, coarse_rate: int = 10) -> tuple[float, float]:
    """The offset in seconds such that a moment at t in the first recording is at t + offset in the second, and how sure that is (0 to 1).
    Found coarsely over the whole range, then refined around the best place."""
    step = max(1, rate // coarse_rate)
    small = lambda env: _shape([sum(env[i:i + step]) / step for i in range(0, len(env) - step + 1, step)])
    ca, cb = small(a), small(b)
    if len(ca) < coarse_rate * 2 or len(cb) < coarse_rate * 2:
        raise ValueError("too_short")
    reach = int(max_lag_seconds * rate / step)
    scores = {lag: s for lag in range(-reach, reach + 1) if (s := _score(ca, cb, lag, least=coarse_rate * 2)) is not None}
    if not scores:
        raise ValueError("too_short")
    coarse = max(scores, key=scores.get)
    fa, fb = _shape(a), _shape(b)
    fine = {lag: s for lag in range(coarse * step - step, coarse * step + step + 1) if (s := _score(fa, fb, lag, least=rate * 2)) is not None}
    lag = max(fine, key=fine.get) if fine else coarse * step
    return round(lag / rate, 2), round(max(0.0, scores[coarse]), 3)
