"""How a recording tells its story, and how it could be cut again (design 2026-10-15, section 9 G).

The story of a recording is read beat by beat from what was measured, not from what a model imagined: how much happens in
each beat (the subject's movement, the loudness, words, things newly seen, the camera moving) makes an energy curve; the
first beat opens, a wide still one sets the scene, the beat of most energy is the peak, the last one closes. The model's own
reading of the structure (in the summary) is held against it.

A recut is a proposal: the beats that can be used, each trimmed to where its action is or around its best frame, put in an
order that holds the eye (the strongest moment first, then the scene, the rest in the order filmed, the end last) and cut to
a length. It is written as an edit decision list (CMX 3600) that Premiere, Resolve and Avid open, against the original files
and their own timecode. Nothing is rendered: the operator or an editor takes it from there.
"""
from pathlib import Path
from typing import Callable

from nexora.core.intelligence import VideoIntelligence
from nexora.core.timebase import frames_timecode, is_drop, timecode_frames
from nexora.core.usability import picture_grade
from nexora.modules.intelligence.entities import thing_name

ROLES = ("mở đầu", "thiết lập", "phát triển", "cao trào", "kết")
WEIGHTS = {"motion": 0.35, "loudness": 0.2, "speech": 0.15, "new": 0.15, "camera": 0.15}
# How long a shot may hold in a cut of a given length, and in how long a hook the viewer decides to stay.
HOOK_SECONDS, MIN_SHOT = 3.0, 1.2


def _v(values: dict, field: str):
    return values[field].value if field in values else None


def _norm(xs: list[float]) -> list[float]:
    lo, hi = min(xs, default=0.0), max(xs, default=0.0)
    return [0.0 if hi - lo < 1e-9 else (x - lo) / (hi - lo) for x in xs]


def beats_of(vi: VideoIntelligence, asset_id: str, motion: Callable[[float, float], float] | None = None) -> list[dict]:
    """Every beat of a recording with what the story is read from."""
    out, seen = [], set()
    events = vi.segments(asset_id, "event")
    for k, b in enumerate(vi.segments(asset_id, "beat")):
        values = vi.values(asset_id, (b.t_start, b.t_end))
        names = {thing_name(str(t)) for t in (_v(values, "things") or [])}
        new = len(names - seen) if k else 0
        seen |= names
        event = next((e for e in events if e.t_start < b.t_end and b.t_start < e.t_end), None)
        moving = (event.data.get("moving_from"), event.data.get("moving_to")) if event else (None, None)
        loud = _v(values, "loudness")
        out.append({"index": k + 1, "t_start": b.t_start, "t_end": b.t_end, "seconds": round(b.t_end - b.t_start, 2),
                    "motion": float(motion(b.t_start, b.t_end)) if motion else (0.0 if _v(values, "still") else 0.3),
                    "loudness": float(loud) if isinstance(loud, (int, float)) else -70.0,
                    "speech": 1.0 if _v(values, "speech") else 0.0, "new": float(new),
                    "camera": 0.0 if _v(values, "camera") in (None, "static") else 1.0,
                    "shot_size": _v(values, "shot_size") if "shot_size" in values and values["shot_size"].source != "model" else None,
                    "aesthetic": float(_v(values, "aesthetic") or 0.0), "best_frame": _v(values, "best_frame"),
                    "picture": picture_grade(values), "moving": moving if moving[0] is not None else None,
                    "description": str(_v(values, "description") or "").split(" Thấy:")[0].split(" Chủ thể:")[0]})
    return out


def story(vi: VideoIntelligence, asset_id: str, *, motion: Callable[[float, float], float] | None = None) -> dict | None:
    """The story of one recording: its energy beat by beat, the role of each beat, its pace and its opening, and whether the
    model's own reading of its structure agrees."""
    known = vi.recording(asset_id)
    if known is None:
        return None
    beats = beats_of(vi, asset_id, motion)
    if not beats:
        return {"asset_id": asset_id, "beats": [], "notes": ["Clip chưa được chia nhịp."]}
    parts = {key: _norm([b[key] for b in beats]) for key in WEIGHTS}
    for i, b in enumerate(beats):
        b["energy"] = round(sum(w * parts[key][i] for key, w in WEIGHTS.items()), 3)
    peak = max(range(len(beats)), key=lambda i: beats[i]["energy"])
    for i, b in enumerate(beats):
        wide_still = b["shot_size"] in ("toàn", "cực toàn") and b["camera"] == 0.0
        if i == 0:
            b["role"] = "thiết lập" if wide_still else "mở đầu"
        elif i == len(beats) - 1 and len(beats) > 1:
            b["role"] = "kết"
        elif i == peak and len(beats) > 2:
            b["role"] = "cao trào"
        else:
            b["role"] = "thiết lập" if wide_still and i == 1 else "phát triển"
        why = sorted(WEIGHTS, key=lambda key: -parts[key][i] * WEIGHTS[key])[:2]
        b["why"] = [{"motion": "chủ thể chuyển động", "loudness": "tiếng to", "speech": "có lời", "new": "thấy vật mới", "camera": "máy di chuyển"}[k]
                    for k in why if parts[k][i] > 0.3]
    profile = (known["summary"] or {}).get("profile") or {}
    pacing = profile.get("pacing") or {}
    duration = float(known["technical"].get("duration") or beats[-1]["t_end"])
    told = (known["summary"] or {}).get("description") or {}
    model_peak = next((p for p in told.get("cau_truc") or [] if "cao trào" in str(p.get("phan", ""))), None)
    agrees = None
    if model_peak and model_peak.get("tu"):
        try:
            m, s = str(model_peak["tu"]).split(":")
            at = int(m) * 60 + float(s)
            agrees = beats[peak]["t_start"] - 1.0 <= at <= beats[peak]["t_end"] + 1.0
        except ValueError:
            agrees = None
    first3 = [b for b in beats if b["t_start"] < HOOK_SECONDS]
    hook_energy = max((b["energy"] for b in first3), default=0.0)
    notes = []
    if len(beats) > 2 and peak == 0:
        notes.append("Đoạn mạnh nhất nằm ngay đầu: mở tốt, nhưng phần sau yếu dần.")
    if len(beats) > 2 and hook_energy < 0.3:
        notes.append("Ba giây đầu ít chuyện xảy ra: nên đưa đoạn mạnh nhất lên đầu khi dựng.")
    median = pacing.get("shot_median")
    if median and median > 8:
        notes.append(f"Cú máy dài (trung bình {median:.0f} giây): dựng cho mạng xã hội nên cắt ngắn còn 2–4 giây mỗi cảnh.")
    if agrees is False:
        notes.append("Mô hình đặt cao trào ở chỗ khác với nơi đo được nhiều chuyển động và âm thanh nhất.")
    return {"asset_id": asset_id, "duration": round(duration, 2), "beats": beats, "peak": beats[peak]["index"],
            "arc": [b["energy"] for b in beats], "hook": {"energy": round(hook_energy, 3), "strength": (profile.get("hook") or {}).get("strength")},
            "pacing": {k: pacing.get(k) for k in ("shots", "cuts_per_minute", "shot_median")},
            "model": {"structure": told.get("cau_truc") or [], "agrees": agrees}, "notes": notes}


def _window(b: dict, longest: float) -> tuple[float, float]:
    """The part of a beat to keep: where its action is, or around its best frame, no longer than `longest`."""
    a, z = b["t_start"], b["t_end"]
    if b["moving"]:
        a, z = max(a, b["moving"][0]), min(z, b["moving"][1])
    if z - a <= longest:
        return round(a, 2), round(z, 2)
    centre = float(b["best_frame"]) if b["best_frame"] is not None and a <= float(b["best_frame"]) <= z else (a + z) / 2
    start = min(max(a, centre - longest / 2), z - longest)
    return round(start, 2), round(start + longest, 2)


def recut(vi: VideoIntelligence, asset_ids: list[str], *, seconds: float = 30.0, names: dict[str, str] | None = None,
          motion: Callable[[str, float, float], float] | None = None) -> dict:
    """A proposal for cutting one or more recordings (in the order given) to about `seconds`: what to keep, in what order,
    trimmed where, and what was left out and why."""
    names = names or {}
    longest = 3.0 if seconds <= 20 else 4.0 if seconds <= 45 else 6.0
    pool, dropped = [], []
    for asset_id in asset_ids:
        told = story(vi, asset_id, motion=(lambda a, b, x=asset_id: motion(x, a, b)) if motion else None)
        if not told or not told.get("beats"):
            continue
        for b in told["beats"]:
            grade, why = b["picture"]
            if grade == "lỗi":
                dropped.append({"asset_id": asset_id, "t_start": b["t_start"], "t_end": b["t_end"], "why": "hình lỗi: " + ", ".join(why)})
                continue
            t_in, t_out = _window(b, longest)
            if t_out - t_in < MIN_SHOT:
                dropped.append({"asset_id": asset_id, "t_start": b["t_start"], "t_end": b["t_end"], "why": "quá ngắn để giữ"})
                continue
            pool.append({**b, "asset_id": asset_id, "t_in": t_in, "t_out": t_out,
                         "score": round(0.5 * b["energy"] + 0.3 * max(0.0, b["aesthetic"] + 0.5) + (0.2 if grade == "dùng được" else 0.0), 3)})
    if not pool:
        return {"seconds": 0.0, "target": seconds, "plan": [], "dropped": dropped, "notes": ["Không có đoạn nào dùng được."]}
    order = {(p["asset_id"], p["index"]): n for n, p in enumerate(pool)}           # the order filmed
    hook = max(pool, key=lambda p: (p["energy"], p["score"]))
    setting = next((p for p in pool if p["role"] == "thiết lập" and p is not hook), None)
    ending = next((p for p in reversed(pool) if p["role"] == "kết" and p not in (hook, setting)), None)
    chosen = [p for p in (hook, setting, ending) if p is not None]
    total = lambda: sum(min(p["t_out"] - p["t_in"], HOOK_SECONDS if p is hook else longest) for p in chosen)
    for p in sorted((p for p in pool if p not in chosen), key=lambda p: -p["score"]):
        if total() >= seconds:
            dropped.append({"asset_id": p["asset_id"], "t_start": p["t_start"], "t_end": p["t_end"], "why": "không cần cho độ dài này"})
            continue
        chosen.append(p)
    middle = sorted((p for p in chosen if p not in (hook, setting, ending)), key=lambda p: order[(p["asset_id"], p["index"])])
    sequence = [hook] + ([setting] if setting else []) + middle + ([ending] if ending else [])
    plan, at = [], 0.0
    for n, p in enumerate(sequence, 1):
        t_in, t_out = p["t_in"], p["t_out"]
        if p is hook and t_out - t_in > HOOK_SECONDS:                               # the hook is short: the strongest seconds of it
            centre = float(p["best_frame"]) if p["best_frame"] is not None and t_in <= float(p["best_frame"]) <= t_out else (t_in + t_out) / 2
            t_in = round(min(max(t_in, centre - HOOK_SECONDS / 2), t_out - HOOK_SECONDS), 2)
            t_out = round(t_in + HOOK_SECONDS, 2)
        role = "mở (hook)" if p is hook else "thiết lập" if p is setting else "kết" if p is ending else p["role"]
        reason = {"mở (hook)": "đoạn nhiều năng lượng nhất, đưa lên đầu để giữ người xem", "thiết lập": "cảnh rộng, máy đứng yên: cho biết đang ở đâu",
                  "kết": "đoạn cuối, khép lại"}.get(role, "giữ theo thứ tự quay")
        plan.append({"order": n, "asset_id": p["asset_id"], "name": names.get(p["asset_id"], p["asset_id"]), "t_in": t_in, "t_out": t_out,
                     "seconds": round(t_out - t_in, 2), "at": round(at, 2), "role": role, "why": reason + (f" ({', '.join(p['why'])})" if p["why"] else ""),
                     "description": p["description"]})
        at += t_out - t_in
    notes = []
    if at < seconds * 0.8:
        notes.append(f"Chỉ có {at:.1f} giây hình dùng được, ngắn hơn {seconds:.0f} giây mong muốn: cần quay thêm hoặc chọn độ dài ngắn hơn.")
    return {"seconds": round(at, 2), "target": seconds, "longest_shot": longest, "plan": plan, "dropped": dropped, "notes": notes}


def edl(vi: VideoIntelligence, made: dict, *, title: str = "NEXORA") -> str:
    """The recut as an edit decision list (CMX 3600): picture and sound of every piece, against the original files' timecode.
    The rate of the first recording sets the record side."""
    plan = made["plan"]
    if not plan:
        return f"TITLE: {title}\nFCM: NON-DROP FRAME\n"
    tech = lambda a: (vi.recording(a) or {}).get("technical") or {}
    rate = float(tech(plan[0]["asset_id"]).get("frame_rate") or 25.0)
    out = [f"TITLE: {title}", f"FCM: {'DROP FRAME' if is_drop(rate) else 'NON-DROP FRAME'}", ""]
    record = timecode_frames("01:00:00:00", rate)
    for p in plan:
        t = tech(p["asset_id"])
        src_rate = float(t.get("frame_rate") or rate)
        start = timecode_frames(t["timecode"], src_rate) if t.get("timecode") else 0
        a, b = start + round(p["t_in"] * src_rate), start + round(p["t_out"] * src_rate)
        length = round((p["t_out"] - p["t_in"]) * rate)
        reel = "AX"
        out.append(f"{p['order']:03d}  {reel:<8} AA/V  C        {frames_timecode(a, src_rate)} {frames_timecode(b, src_rate)} "
                   f"{frames_timecode(record, rate)} {frames_timecode(record + length, rate)}")
        out.append(f"* FROM CLIP NAME: {Path(p['name']).name}")
        out.append(f"* COMMENT: {p['role']}: {p['why']}")
        out.append("")
        record += length
    return "\n".join(out)


def markdown(s: dict | None, r: dict | None, *, name: str = "") -> str:
    out = [f"# Kể chuyện và dựng lại{': ' + name if name else ''}", ""]
    if s and s.get("beats"):
        out += ["## Câu chuyện của clip", ""]
        for b in s["beats"]:
            out.append(f"- Nhịp {b['index']} ({b['t_start']:.1f}–{b['t_end']:.1f} s): {b['role']}, năng lượng {b['energy']:.2f}"
                       + (f" ({', '.join(b['why'])})" if b["why"] else ""))
        out.append(f"- Cao trào: nhịp {s['peak']}" + ("" if s["model"]["agrees"] is None else
                                                     (" · mô hình đồng ý" if s["model"]["agrees"] else " · mô hình đặt cao trào chỗ khác")))
        out += [f"- {n}" for n in s["notes"]] + [""]
    if r:
        out += [f"## Đề xuất dựng lại ({r['seconds']:.1f} / {r['target']:.0f} giây)", ""]
        for p in r["plan"]:
            out.append(f"{p['order']}. `{Path(p['name']).name}` {p['t_in']:.1f}–{p['t_out']:.1f} s ({p['seconds']:.1f} s) · {p['role']}: {p['why']}")
        if r["dropped"]:
            out += ["", "Bỏ ra:"] + [f"- `{Path(r_.get('asset_id', '')).name}` {d['t_start']:.1f}–{d['t_end']:.1f} s: {d['why']}" for d in r["dropped"] for r_ in [d]]
        out += [f"- {n}" for n in r["notes"]]
    return "\n".join(out).rstrip() + "\n"
