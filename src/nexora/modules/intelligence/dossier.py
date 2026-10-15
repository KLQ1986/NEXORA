"""The dossier of a recording (design 2026-10-15, section 9 B): everything Video Intelligence has learnt about it, gathered in
one place to be read, kept and handed on, and a word on every beat: can its picture be used, can its sound.

Nothing is analysed here. The dossier reads the canonical model through `VideoIntelligence`, so it is as current as the
analysis, and says which parts of the analysis are out of date. The grades come from what was measured, never from what a
model said: a model that calls a shaky picture steady does not make it usable.
"""
import re

from nexora.core.intelligence import VideoIntelligence

# Picture faults by field, as (what is wrong, how bad): "poor" makes a beat unusable, "fair" usable with care.
PICTURE = {"shake": "rung", "sharpness": "mờ", "exposure": "sai sáng", "quality": "chất lượng hình kém"}
GRADES = ("dùng được", "dùng tạm", "lỗi")
FIELD_NAMES = {"shot_size": "cỡ cảnh", "angle": "góc máy", "camera": "máy", "people": "số người", "place": "nơi", "light": "ánh sáng",
               "colour": "màu", "speaker": "người nói"}
CAMERA = {"static": "đứng yên", "pan": "lia ngang", "tilt": "lia dọc", "push_in": "đẩy vào", "pull_out": "kéo ra", "handheld": "cầm tay rung"}
# The search text of a beat ends with lists the dossier gives on their own lines.
_LISTS = re.compile(r"\s*(Điểm mới|Thấy|Hành động|Nơi|Hình):.*$", re.S)


def _value(values: dict, field: str):
    v = values.get(field)
    return v.value if v is not None else None


def _known(values: dict, field: str):
    """A value that was measured, recognised or set by the operator; what only a model said is not built on."""
    v = values.get(field)
    return v.value if v is not None and v.source != "model" else None


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


def uses_of(values: dict, *, first: bool, last: bool, speech: bool) -> list[str]:
    """What a beat could serve as in a cut, by rule from what was measured."""
    size, camera, still = _known(values, "shot_size"), _known(values, "camera"), _known(values, "still")
    uses = []
    if size in ("toàn", "cực toàn") and (camera in ("static", "pan") or still):
        uses.append("cảnh thiết lập (mở đầu một đoạn)")
    if camera == "push_in":
        uses.append("dẫn vào chủ thể")
    if camera == "pull_out" or (last and size in ("toàn", "cực toàn")):
        uses.append("cảnh kết")
    if size in ("cận", "đặc tả"):
        uses.append("cảnh chèn chi tiết")
    if speech and _known(values, "speaker") == "trong khung":
        uses.append("đoạn nói trước máy")
    elif speech:
        uses.append("lời dẫn ngoài khung")
    if not uses:
        uses.append("cảnh chèn" if not first else "cảnh mở đầu")
    return uses


def build(vi: VideoIntelligence, asset_id: str, *, name: str | None = None) -> dict | None:
    """The dossier of one recording, or None if the canonical model knows nothing of it."""
    known = vi.recording(asset_id)
    if known is None:
        return None
    tech, summary = known["technical"], known["summary"]
    told = summary.get("description") or {}
    sentences = vi.segments(asset_id, "sentence")
    spans = [s for s in vi.segments(asset_id, "span") if s.data.get("type") == "text"]
    beats_out = []
    beats = vi.segments(asset_id, "beat")
    for k, beat in enumerate(beats):
        span = (beat.t_start, beat.t_end)
        values = vi.values(asset_id, span)
        picture, picture_why = picture_grade(values)
        sound, sound_why = sound_grade(values)
        said = [s.data.get("text", "") for s in sentences if s.t_end > beat.t_start and s.t_start < beat.t_end]
        flags = [f for f in (_value(values, "flags") or []) if f.get("state", "open") == "open"]
        beats_out.append({
            "index": k + 1, "t_start": beat.t_start, "t_end": beat.t_end, "seconds": round(beat.t_end - beat.t_start, 2),
            "description": _LISTS.sub("", str(_value(values, "description") or "")).strip(),
            "things": _value(values, "things") or [],
            "actions": [a.get("lam_gi", "") if isinstance(a, dict) else str(a) for a in (_value(values, "actions") or [])],
            "measured": {f: _value(values, f) for f in ("shot_size", "angle", "camera", "people", "place", "light", "colour", "speaker")
                         if _value(values, f) is not None},
            "sources": {f: values[f].source for f in ("shot_size", "people", "place") if f in values},
            "picture": {"grade": picture, "why": picture_why},
            "sound": {"grade": sound, "why": sound_why},
            "uses": uses_of(values, first=k == 0, last=k == len(beats) - 1, speech=bool(said)),
            "speech": said,
            "text_on_screen": [s.data.get("text", "") for s in spans if s.t_end > beat.t_start and s.t_start < beat.t_end],
            "aesthetic": _value(values, "aesthetic"),
            "flags": [f.get("message", "") for f in flags],
        })
    usable = [b for b in beats_out if b["picture"]["grade"] == "dùng được"]
    best = max(usable or beats_out, key=lambda b: b["aesthetic"] or 0.0, default=None)
    people = [e for e in vi.entities("person") if any(a["asset_id"] == asset_id for a in e["appearances"])]
    places = [e for e in vi.entities("place") if any(a["asset_id"] == asset_id for a in e["appearances"])]
    return {
        "asset_id": asset_id, "name": name,
        "recording": {"duration": tech.get("duration"), "width": tech.get("display_width") or tech.get("width"),
                      "height": tech.get("display_height") or tech.get("height"), "frame_rate": tech.get("frame_rate"), "codec": tech.get("codec"),
                      "bit_depth": tech.get("bit_depth"), "hdr": tech.get("hdr"), "log": (summary.get("profile") or {}).get("log_profile"),
                      "orientation": tech.get("orientation"), "has_audio": tech.get("has_audio"), "created": tech.get("created"), "size": tech.get("size")},
        "title": told.get("tieu_de", ""), "summary": told.get("tom_tat", ""), "topics": told.get("chu_de", []), "genre": told.get("the_loai", ""),
        "story": told.get("cau_truc", []),
        "analysis": {"analysed": vi.analysed(asset_id), "out_of_date": vi.stale(asset_id), "updated_at": known.get("updated_at")},
        "people": [{"name": e["name"] or e["data"].get("name") or "chưa đặt tên", "key": e["key"],
                    "at": [(a["t_start"], a["t_end"]) for a in e["appearances"] if a["asset_id"] == asset_id]} for e in people],
        "places": [{"name": e["name"] or e["data"].get("name") or e["key"], "key": e["key"]} for e in places],
        "speech": [{"t_start": s.t_start, "t_end": s.t_end, "text": s.data.get("text", ""), "speaker": (s.data.get("speaker") or {}).get("value")}
                   for s in sentences],
        "text_on_screen": [{"t_start": s.t_start, "t_end": s.t_end, "text": s.data.get("text", ""), "kind": s.data.get("kind")} for s in spans],
        "events": [{"t_start": e.t_start, "t_end": e.t_end, "who": e.data.get("who") or "", "actions": e.data.get("actions") or [],
                    **{k: e.data[k] for k in ("before", "after") if e.data.get(k)}} for e in vi.segments(asset_id, "event")],
        "scenes": [e.data.get("name", "") for e in vi.segments(asset_id, "scene")],
        "shots": len(vi.segments(asset_id, "shot")),
        "beats": beats_out,
        "verdict": {"usable_seconds": round(sum(b["seconds"] for b in usable), 2),
                    "careful_seconds": round(sum(b["seconds"] for b in beats_out if b["picture"]["grade"] == "dùng tạm"), 2),
                    "unusable_seconds": round(sum(b["seconds"] for b in beats_out if b["picture"]["grade"] == "lỗi"), 2),
                    "best_beat": best["index"] if best else None},
    }


def _clock(t: float | None) -> str:
    t = float(t or 0.0)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def markdown(d: dict) -> str:
    """The dossier as a page to read or hand on."""
    r = d["recording"]
    out = [f"# Hồ sơ: {d['title'] or d['name'] or d['asset_id']}", ""]
    if d["name"]:
        out.append(f"Tệp: `{d['name']}`  ")
    out.append(f"Dài {r['duration'] or 0:.1f} giây · {r['width']}×{r['height']} · {r['frame_rate'] or 0:.2f} khung/giây · {r['codec']}"
               f"{' · ' + str(r['bit_depth']) + '-bit' if r['bit_depth'] else ''}{' · log' if r['log'] else ''}{' · HDR' if r['hdr'] else ''}"
               f" · {r['orientation'] or ''} · {'có tiếng' if r['has_audio'] else 'không tiếng'}")
    if d["summary"]:
        out += ["", d["summary"]]
    if d["topics"]:
        out.append(f"\nChủ đề: {', '.join(d['topics'])}" + (f" · Thể loại: {d['genre']}" if d["genre"] else ""))
    v = d["verdict"]
    out += ["", "## Kết luận", "",
            f"- Dùng được: {v['usable_seconds']:.1f} giây · dùng tạm: {v['careful_seconds']:.1f} giây · lỗi: {v['unusable_seconds']:.1f} giây",
            f"- Nhịp đẹp nhất: {v['best_beat']}" if v["best_beat"] else "- Chưa có nhịp nào"]
    stale = d["analysis"]["out_of_date"]
    out.append(f"- Phần phân tích đã cũ: {', '.join(stale)}" if stale else "- Phân tích đang ở phiên bản mới nhất")
    out += ["", "## Từng nhịp", ""]
    for b in d["beats"]:
        out.append(f"### {b['index']}. {_clock(b['t_start'])}–{_clock(b['t_end'])} · hình: {b['picture']['grade']} · tiếng: {b['sound']['grade']}")
        out.append("")
        if b["description"]:
            out.append(b["description"])
            out.append("")
        said = [f"{FIELD_NAMES.get(k, k)} {CAMERA.get(v, v) if k == 'camera' else v}{' (mô hình nói)' if b['sources'].get(k) == 'model' else ''}"
                for k, v in b["measured"].items()]
        out.append("- Đặc điểm: " + ", ".join(said))
        if b["things"]:
            out.append("- Thấy: " + ", ".join(str(t) for t in b["things"]))
        if b["actions"]:
            out.append("- Hành động: " + ", ".join(b["actions"]))
        if b["picture"]["why"] or b["sound"]["why"]:
            out.append("- Lưu ý: " + ", ".join(b["picture"]["why"] + b["sound"]["why"]))
        out.append("- Dùng làm: " + ", ".join(b["uses"]))
        if b["speech"]:
            out.append("- Lời: " + " ".join(f"“{s}”" for s in b["speech"]))
        if b["text_on_screen"]:
            out.append("- Chữ trên hình: " + ", ".join(b["text_on_screen"]))
        if b["flags"]:
            out.append("- Cần xem lại: " + "; ".join(b["flags"]))
        out.append("")
    if d["people"] or d["places"]:
        out += ["## Người và nơi", ""]
        out += [f"- Người: {p['name']} ({', '.join(f'{_clock(a)}–{_clock(b)}' for a, b in p['at'])})" for p in d["people"]]
        out += [f"- Nơi: {p['name']}" for p in d["places"]]
        out.append("")
    if d["events"]:
        out += ["## Sự kiện", ""] + [f"- {_clock(e['t_start'])}–{_clock(e['t_end'])} {', '.join(e['actions'])}" for e in d["events"]] + [""]
    if d["speech"]:
        out += ["## Lời nói", ""] + [f"- {_clock(s['t_start'])} {s['text']}" for s in d["speech"]] + [""]
    if d["story"]:
        out += ["## Cấu trúc", ""] + [f"- {p.get('tu', '')} {p.get('phan', '')}: {p.get('vi', '')}" for p in d["story"]] + [""]
    return "\n".join(out).rstrip() + "\n"
