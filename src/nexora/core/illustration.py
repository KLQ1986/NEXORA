"""How a picture illustrates the words of a line (design 2026-10-18, associative illustration).

`direct`: the picture shows what is said. `associative`: the picture evokes the idea (a metaphor, a symbol, a mood, a rhythm).
`contrast`: the picture runs against the words to make a point. A line's illustration is {mode, evokes, feel}; `feel` is what
the picture should feel like, in a fixed vocabulary that the library's own measurements can answer, so the match on feel is
measured, not asked of a model.
"""
from __future__ import annotations

MODES = ("direct", "associative", "contrast")
STYLES = ("direct", "associative", "mixed")          # for a whole video (template, channel, project): mixed lets the writer choose per line
MODE_WORDS = {"truc_tiep": "direct", "trực tiếp": "direct", "lien_tuong": "associative", "liên tưởng": "associative", "tuong_phan": "contrast", "tương phản": "contrast"}

# What the picture should feel like: each key with the words it may take. Every value is answered by a measurement (see `measured`).
FEEL = {
    "chuyen_dong": ("tĩnh", "chậm", "nhanh"),        # the camera's own movement
    "anh_sang": ("sáng", "vừa", "tối"),
    "mau": ("ấm", "trung tính", "lạnh"),
    "khung": ("rộng", "trung", "cận"),
    "nguoi": ("không người", "một người", "vài người", "đông người"),
}
FEEL_NAMES = {"chuyen_dong": "chuyển động", "anh_sang": "ánh sáng", "mau": "màu", "khung": "khung hình", "nguoi": "người"}


def normalise(raw: dict | None) -> dict:
    """An illustration in its one shape, whoever wrote it (the model, the operator); {} when it says nothing."""
    if not isinstance(raw, dict):
        return {}
    mode = str(raw.get("mode") or raw.get("kieu") or "").strip().lower()
    mode = MODE_WORDS.get(mode, mode)
    if mode not in MODES:
        return {}
    feel_in = raw.get("feel") or raw.get("cam_giac") or {}
    feel = {k: str(v).strip().lower() for k, v in (feel_in.items() if isinstance(feel_in, dict) else []) if k in FEEL and str(v).strip().lower() in FEEL[k]}
    evokes = str(raw.get("evokes") or raw.get("goi") or "").strip()
    out = {"mode": mode}
    if evokes and mode != "direct":
        out["evokes"] = evokes[:120]
    if feel:
        out["feel"] = feel
    return out


def query(text: str, brief: str | None, illustration: dict | None) -> str:
    """What to search the footage with. A direct line: its words and what it asks to see. Any other: what is to be seen and what
    it evokes, never the words, since those say an idea the picture does not show."""
    ill = illustration or {}
    if ill.get("mode") in ("associative", "contrast"):
        return " ".join(x for x in (brief, ill.get("evokes")) if x) or text
    return f"{text} {brief}" if brief else text


def judged_line(text: str, brief: str | None, illustration: dict | None) -> str:
    """What the judge holds the frames against: the line itself for a direct one, what it should evoke for any other."""
    ill = illustration or {}
    if ill.get("mode") == "associative":
        return f"{brief or ''} (hình gợi ý \"{ill.get('evokes') or brief or text}\" cho câu \"{text}\"; không cần thấy đúng điều câu nói)".strip()
    if ill.get("mode") == "contrast":
        return f"{brief or ''} (hình đối lập với câu \"{text}\" để nhấn ý \"{ill.get('evokes') or ''}\")".strip()
    return brief or text


def measured(data: dict) -> dict:
    """The feel of a stretch of footage, read from what the library measured about it (a moment's `labels` and `profile`).
    A quality not measured is left out rather than guessed."""
    labels, profile = data.get("labels") or {}, data.get("profile") or {}
    out = {}
    camera = labels.get("camera") or {}
    if (labels.get("still") or {}).get("value") is True or camera.get("value") == "static":
        out["chuyen_dong"] = "tĩnh"
    elif camera.get("speed") is not None:
        out["chuyen_dong"] = "chậm" if float(camera["speed"]) < 0.08 else "nhanh"
    light = (profile.get("light") or {}).get("brightness")
    if light is not None:
        out["anh_sang"] = "sáng" if light >= 0.6 else "tối" if light < 0.35 else "vừa"
    kelvin = (profile.get("colour") or {}).get("kelvin")
    if kelvin:
        out["mau"] = "ấm" if kelvin < 5200 else "lạnh" if kelvin > 7000 else "trung tính"
    size = (profile.get("shot_size") or {}).get("value")
    if size:
        out["khung"] = "rộng" if size in ("toàn", "cực toàn") else "cận" if size in ("cận", "đặc tả") else "trung"
    people = profile.get("people") or {}
    if people.get("count") is not None:
        n = int(people["count"])
        out["nguoi"] = "không người" if n == 0 else "một người" if n == 1 else "vài người" if n < 4 else "đông người"
    return out


def feel_match(wanted: dict | None, data: dict) -> tuple[float, str | None]:
    """How much of the wanted feel a stretch has, 0 to 1, and the words that say so ("chậm, sáng: khớp 2/3"). Only qualities that
    were measured count; with nothing to compare, 0 and no words."""
    wanted = {k: v for k, v in (wanted or {}).items() if k in FEEL}
    if not wanted:
        return 0.0, None
    have = measured(data)
    asked = [k for k in wanted if k in have]
    if not asked:
        return 0.0, None
    hit = [k for k in asked if have[k] == wanted[k]]
    if not hit:
        return 0.0, f"không khớp ({', '.join(wanted[k] for k in asked)})"
    return len(hit) / len(wanted), f"{', '.join(wanted[k] for k in hit)}: khớp {len(hit)}/{len(wanted)}"


def style_prompt(style: str) -> str:
    """The writer's instruction for a video's way of illustrating, and the keys each line returns."""
    feel = "; ".join(f"{k}: {' | '.join(v)}" for k, v in FEEL.items())
    keys = ("Mỗi câu trả về một mục có các khoá: cau (lời dẫn), kieu (truc_tiep | lien_tuong | tuong_phan), "
            "hinh (điều thấy trên hình, viết như mô tả một cảnh quay; mỗi câu một hình KHÁC các câu khác), "
            "goi (với lien_tuong và tuong_phan: hình gợi ra điều gì, từ 2 đến 5 chữ, ví dụ \"dừng lại\", \"bắt đầu lại\"), "
            f"cam_giac (đối tượng chỉ gồm 1 đến 3 khoá quan trọng nhất cho câu, mỗi khoá một giá trị: {feel}).")
    if style == "direct":
        return ("Mỗi câu nói về một hình ảnh CÓ trong kho footage ở trên để có hình minh hoạ trực tiếp; kieu luôn là truc_tiep. " + keys)
    lead = ("Lời dẫn kể chuyện, nói ý, nói cảm nghĩ; KHÔNG tả lại điều đang thấy trên hình. Kho footage ở trên là nguyên liệu để minh hoạ. ")
    if style == "associative":
        return lead + "Mọi câu minh hoạ bằng liên tưởng: hình gợi ra ý của câu qua ẩn dụ, biểu tượng, cảm xúc hay nhịp; kieu là lien_tuong (hiếm khi tuong_phan). " + keys
    return (lead + "Chọn cách minh hoạ cho từng câu: điều cụ thể (nơi chốn, đồ vật, dữ kiện, các bước, người được nhắc tên) thì truc_tiep; "
            "ý, cảm xúc, câu chuyển ý thì lien_tuong; tuong_phan chỉ dùng hiếm, khi cần nhấn một điểm. " + keys)
