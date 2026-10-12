"""Deterministic checks: things about a cut, its captions and its package that can be measured and are either so or not
(design v4.0, section 20.1). No model is asked anything here.
"""
from pathlib import Path

MAX_CHARS_PER_SECOND = 20.0      # faster than this and a caption cannot be read before it goes
MAX_CAPTION_CHARS = 84           # two lines of 42
LONG_BLACK, LONG_SILENCE = 0.5, 3.0
TITLE_MAX = 100


def caption_findings(shots: list[dict]) -> list[dict]:
    """Captions that cannot be read in the time they are on screen, or that will not fit in two lines."""
    out = []
    for i, s in enumerate(shots, 1):
        text, seconds = (s.get("text") or "").strip(), float(s.get("duration") or 0)
        if not text or seconds <= 0:
            continue
        if len(text) > MAX_CAPTION_CHARS:
            out.append({"check": "Phụ đề", "shot": i, "severity": "vừa", "text": f"Phụ đề dài {len(text)} ký tự, quá hai dòng.", "fix": "Tách câu, hoặc đặt chữ trên màn hình ngắn hơn cho câu này."})
        elif len(text) / seconds > MAX_CHARS_PER_SECOND:
            out.append({"check": "Phụ đề", "shot": i, "severity": "vừa", "text": f"Phụ đề {len(text)} ký tự chỉ hiện {seconds:.1f} giây, đọc không kịp.", "fix": "Giữ hình lâu hơn hoặc rút gọn câu."})
    return out


def picture_and_sound(black: list[list[float]], silent: list[list[float]], duration: float, *, gap_ranges: list[list[float]] = ()) -> dict:
    """Checks on the finished file: no stretch of black that is not a known gap, and no long silence."""
    in_gap = lambda a, b: any(a >= ga - 0.2 and b <= gb + 0.2 for ga, gb in gap_ranges)
    stray = [[a, b] for a, b in black if b - a >= LONG_BLACK and not in_gap(a, b)]
    quiet = [[a, b] for a, b in silent if b - a >= LONG_SILENCE and b - a < duration - 0.5]
    return {"checks": {"Không có khung đen ngoài ý muốn": not stray, "Không có khoảng im lặng dài": not quiet}, "black": stray, "silence": quiet}


def package_checks(package: dict) -> dict:
    """Everything a manual upload needs is in the folder and usable."""
    folder = Path(package["folder"])
    present = lambda name: bool(name) and (folder / name).is_file() and (folder / name).stat().st_size > 0
    title = (package.get("title") or "").strip()
    return {
        "Có file video": present(package.get("video")),
        "Có phụ đề rời": present(package.get("captions")),
        "Có ảnh đại diện": present(package.get("thumbnail")),
        "Tiêu đề không trống và không quá dài": 0 < len(title) <= TITLE_MAX,
        "Có mô tả": bool((package.get("description") or "").strip()),
    }
