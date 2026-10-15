"""Can a stretch of footage be used: its picture and its sound graded from what was measured (design 2026-10-15, section 9).

Read by the dossier of a recording and by the report on how a script's lines were matched. The grades come from measured
fields only: a model that calls a shaky picture steady does not make it usable.
"""

GRADES = ("dùng được", "dùng tạm", "lỗi")
# Picture faults by field, as (what is wrong, how bad): "poor" makes a beat unusable, "fair" usable with care.
PICTURE = {"shake": "rung", "sharpness": "mờ", "exposure": "sai sáng", "quality": "chất lượng hình kém"}


def _value(values: dict, field: str):
    v = values.get(field)
    return v.value if v is not None else None


def picture_grade(values: dict) -> tuple[str, list[str]]:
    """How usable a beat's picture is, and why, from the measured fields only."""
    why_bad, why_care = [], []
    for field, name in PICTURE.items():
        grade = _value(values, field)
        fault = ((values.get(field).evidence or {}).get("fault") if values.get(field) else None)
        said = {"burnt": "cháy sáng", "dark": "thiếu sáng"}.get(fault, name) if field == "exposure" else name
        if grade == "poor":
            why_bad.append(said)
        elif grade == "fair":
            why_care.append(f"hơi {said}" if field != "quality" else "chất lượng hình trung bình")
    if _value(values, "horizon") == "nghiêng":
        why_care.append("đường chân trời nghiêng")
    if _value(values, "backlit") is True:
        why_care.append("ngược sáng")
    if _value(values, "noise") == "kém":
        why_care.append("nhiễu hạt")
    if why_bad:
        return "lỗi", why_bad + why_care
    return ("dùng tạm", why_care) if why_care else ("dùng được", [])


def sound_grade(values: dict) -> tuple[str, list[str]]:
    """How usable a beat's own sound is: clipped sound cannot be mended; wind can be lived with under music."""
    if _value(values, "clipping") is True:
        return "lỗi", ["tiếng bị méo"]
    care = []
    if _value(values, "wind") is True:
        care.append("có tiếng gió")
    loud = _value(values, "loudness")
    if isinstance(loud, (int, float)) and loud < -45:
        care.append(f"tiếng rất nhỏ ({loud:.0f} LUFS)")
    return ("dùng tạm", care) if care else ("dùng được", [])
