"""How well the footage serves a script (design 2026-10-15, section 9 C): for every line, what was found and how well its frames
show what the line says; for every recording, which lines it serves; and in all, how much of the script has a picture.

Read after a match: nothing is searched or judged again here. A line is "tốt" when the operator accepted its picture or the
model judged the frames to show it well; "tạm" when something was found that shows it less well, or whose picture is faulty;
"thiếu" when nothing was found. What is wrong with a picture comes from what was measured (`core.usability`).
"""
import re

from nexora.core.intelligence import VideoIntelligence
from nexora.core.projects import ProjectStore
from nexora.core.usability import picture_grade
from nexora.modules.sourcing.match import AUTO_ACCEPT, needed_seconds

LINE_GRADES = ("tốt", "tạm", "thiếu")


def _clock(t: float | None) -> str:
    t = float(t or 0.0)
    return f"{int(t // 60)}:{t % 60:04.1f}"


# A selection's reason is the judge's word, then what matched, then the stretch's search text; the report keeps the first two.
_JUDGED = re.compile(r"^(.*?\(\d+/10\)\.)\s*(Khớp [^.]*\.)?")


def why_chosen(reason: str) -> str:
    m = _JUDGED.match(reason or "")
    if m:
        return " ".join(x for x in m.groups() if x)
    lead = re.match(r"^(Khớp [^.]*\.)", reason or "")
    return lead.group(1) if lead else (reason or "")[:160]


def line_grade(status: str, judge: int | None, picture: str | None) -> str:
    if status == "gap" or status is None:
        return "thiếu"
    if picture == "lỗi":
        return "tạm"
    if status == "accepted" or (judge is not None and judge >= AUTO_ACCEPT):
        return "tốt"
    return "tạm"


def build(projects: ProjectStore, vi: VideoIntelligence | None, script_id: str, *, names: dict[str, str]) -> dict:
    """The report on one script's match. `names`: the file name of every recording in the library, by asset id."""
    script = projects.script(script_id)
    lines, clips = [], {}
    for n, shot in enumerate(script["shots"], 1):
        sel = projects.selection(shot.shot_id)
        need = max(needed_seconds(shot.text), shot.target_seconds or 0.0)
        status = sel.status if sel else None
        found = None
        picture, why = None, []
        if sel and sel.asset_id and status != "gap":
            span = (sel.t_in or 0.0, sel.t_out or 0.0)
            if vi is not None:
                picture, why = picture_grade(vi.values(sel.asset_id, span))
            found = {"asset_id": sel.asset_id, "name": names.get(sel.asset_id, sel.asset_id), "t_in": sel.t_in, "t_out": sel.t_out,
                     "seconds": round(span[1] - span[0], 2), "score": sel.score, "reason": why_chosen(sel.reason or ""), "picture": picture, "picture_why": why}
            clips.setdefault(sel.asset_id, {"chosen": [], "alternate": [], "seconds": 0.0})
            clips[sel.asset_id]["chosen"].append(n)
            clips[sel.asset_id]["seconds"] += found["seconds"]
        for alt in (sel.alternates if sel else []):
            clips.setdefault(alt["asset_id"], {"chosen": [], "alternate": [], "seconds": 0.0})
            if n not in clips[alt["asset_id"]]["alternate"]:
                clips[alt["asset_id"]]["alternate"].append(n)
        judge = (sel.extras or {}).get("judge") if sel else None
        grade = line_grade(status, judge, picture)
        lines.append({"line": n, "shot_id": shot.shot_id, "text": shot.text, "brief": shot.brief, "seconds_needed": round(need, 1),
                      "status": status or "chưa ghép", "decided_by": sel.decided_by if sel else None, "judge": judge, "grade": grade, "found": found,
                      "short": bool(found and found["seconds"] + 0.05 < need),
                      "alternates": [{"asset_id": a["asset_id"], "name": names.get(a["asset_id"], a["asset_id"]), "judge": a.get("judge"),
                                      "t_in": a.get("t_in"), "t_out": a.get("t_out")} for a in (sel.alternates if sel else [])]})
    counts = {g: sum(1 for x in lines if x["grade"] == g) for g in LINE_GRADES}
    need = sum(x["seconds_needed"] for x in lines)
    covered = sum(min(x["seconds_needed"], x["found"]["seconds"]) for x in lines if x["found"])
    by_clip = [{"asset_id": a, "name": names.get(a, a), "lines": c["chosen"], "alternate_for": c["alternate"], "seconds": round(c["seconds"], 2)}
               for a, c in sorted(clips.items(), key=lambda kv: (-len(kv[1]["chosen"]), -len(kv[1]["alternate"])))]
    unused = sorted(names[a] for a in names if a not in clips)
    judged = [x["judge"] for x in lines if x["judge"] is not None]
    return {"script_id": script_id, "project_id": script["project_id"], "lines": lines, "clips": by_clip, "unused": unused,
            "totals": {"lines": len(lines), **counts, "seconds_needed": round(need, 1), "seconds_covered": round(covered, 1),
                       "coverage": round(covered / need, 3) if need else 0.0, "judge_mean": round(sum(judged) / len(judged), 1) if judged else None,
                       "approved": bool(script.get("match_approved"))}}


def markdown(r: dict, *, title: str = "") -> str:
    t = r["totals"]
    out = [f"# Báo cáo ghép nguyên liệu{': ' + title if title else ''}", "",
           f"- {t['lines']} câu: {t['tốt']} tốt, {t['tạm']} tạm, {t['thiếu']} thiếu",
           f"- Hình cần: {t['seconds_needed']:.1f} giây · đã có: {t['seconds_covered']:.1f} giây ({t['coverage']:.0%})"]
    if t["judge_mean"] is not None:
        out.append(f"- Điểm khớp trung bình: {t['judge_mean']}/10")
    out += ["", "## Theo câu", ""]
    for x in r["lines"]:
        out.append(f"### Câu {x['line']} · {x['grade']}" + (f" · {x['judge']}/10" if x["judge"] is not None else ""))
        out.append(f"“{x['text']}”" + (f"  \nCần thấy: {x['brief']}" if x["brief"] else ""))
        f = x["found"]
        if f:
            out.append(f"- Hình: `{f['name']}` {_clock(f['t_in'])}–{_clock(f['t_out'])} ({f['seconds']:.1f} giây"
                       + (f", thiếu so với {x['seconds_needed']:.1f} giây cần" if x["short"] else "") + ")")
            if f["picture"] and f["picture"] != "dùng được":
                out.append(f"- Hình {f['picture']}: {', '.join(f['picture_why'])}")
            if f["reason"]:
                out.append(f"- Lý do: {f['reason']}")
        else:
            out.append("- Chưa có hình trong kho cho câu này.")
        if x["alternates"]:
            out.append("- Phương án khác: " + ", ".join(f"`{a['name']}` {_clock(a['t_in'])}" + (f" ({a['judge']}/10)" if a["judge"] is not None else "")
                                                        for a in x["alternates"]))
        out.append("")
    out += ["## Theo clip", ""]
    for c in r["clips"]:
        out.append(f"- `{c['name']}`: chọn cho câu {', '.join(map(str, c['lines'])) or '–'}"
                   + (f"; dự phòng cho câu {', '.join(map(str, c['alternate_for']))}" if c["alternate_for"] else "") + f"; dùng {c['seconds']:.1f} giây")
    if r["unused"]:
        out += ["", "Không được dùng: " + ", ".join(f"`{n}`" for n in r["unused"])]
    return "\n".join(out).rstrip() + "\n"
