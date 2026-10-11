"""Hours of the day in which long background work may run."""
import time


def parse_window(spec: str | None) -> tuple[int, int] | None:
    """ "22-7" means from 22:00 until 07:00. Empty means any time. Raises ValueError on anything else."""
    if not spec:
        return None
    start, end = (int(part) for part in spec.split("-"))
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        raise ValueError("hours run from 0 to 23 and must differ")
    return start, end


def in_window(spec: str | None, *, hour: int | None = None) -> bool:
    window = parse_window(spec)
    if window is None:
        return True
    hour = time.localtime().tm_hour if hour is None else hour
    start, end = window
    return start <= hour < end if start < end else hour >= start or hour < end
