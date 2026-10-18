"""The project's storyboard: from an idea (or the script) to scenes and shots whose specs are contracts, changed by typed
operations shown as a diff, read for continuity at every cut and on a camera plan, and written to the project's script so
that matching, generation and the render take it from there (design 2026-10-17).

Nothing here searches footage or measures a picture: the Director (agents) does, and hands its measures to `seams`.
"""
from __future__ import annotations

import copy
import json
import math
import re

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, PrivacyClass, Request
from nexora.core.projects import ProjectStore
from nexora.core.storyboard import Shot, Storyboard

TEXT_ONLY = PrivacyClass.CLOUD_ALLOWED

SIZES = ("toàn cảnh", "trung", "cận trung", "cận", "đặc tả")
ANGLES = ("ngang mắt", "cao", "thấp", "cao (drone)", "hơi thấp", "qua vai")
MOVES = ("đứng yên", "theo sau", "lia ngang", "đẩy tới", "lùi ra", "bay chậm tới", "cầm tay")
LENSES = ("16mm", "24mm", "35mm", "40mm", "50mm", "85mm", "100mm")
SOURCES = ("footage", "generate", "stock", "any")
DIRECTIONS = ("phải", "trái", "")
TIMES = ("bình minh", "sáng", "trưa", "chiều", "hoàng hôn", "đêm", "")
# A plan of each scene seen from above, in a 560×220 box: the action runs along the axis at y = 110.
AXIS, PLAN_W, PLAN_H = 110, 560, 220

# What can be asked of a shot and how it is measured (`by`: auto, or a person). The Director measures the automatic ones.
CHECKS = {
    "match": ("Hình khớp mục tiêu", "auto", ">=", 0.45),           # the search's score of the picture against the intent
    "duration": ("Thời lượng trong khoảng", "auto", "range", None),
    "shot_size": ("Đúng cỡ cảnh", "auto", "=", None),              # Video Intelligence, only while the field is released
    "people": ("Đúng số người", "auto", "=", None),
    "no_shake": ("Không rung", "auto", "<", 0.3),                   # Visual Quality's defects at the stretch
    "no_blur": ("Không mờ", "auto", "<", 0.3),
    "colour_continuity": ("Màu nối với shot trước", "auto", "<=", 4.0),
    # SigLIP 2 on the largest face of the picture against the character's reference in the Bible. Measured on public-domain
    # official portraits (2026-10-17): the same person 0.922–0.955, different people at most 0.873; a picture without a face
    # is unmeasured, never passed. Two same-person pairs only: to be checked again once a Bible has real references.
    "character": ("Giống nhân vật trong Bible", "auto", ">=", 0.90),
    "human": ("Người duyệt", "human", "", None),
}

LABEL = {"intent": "mục tiêu", "line": "lời dẫn", "duration.target": "thời lượng", "duration.min": "tối thiểu", "duration.max": "tối đa",
         "framing.size": "cỡ cảnh", "framing.angle": "góc máy", "framing.move": "chuyển động", "framing.lens": "ống kính", "direction": "hướng",
         "source.policy": "nguồn", "source.query": "tìm footage", "generation.provider": "nhà cung cấp ảnh khung", "generation.provider_video": "nhà cung cấp video",
         "generation.model": "model",
         "generation.prompt.subject": "chủ thể (prompt)", "generation.prompt.action": "hành động (prompt)", "generation.prompt.setting": "bối cảnh (prompt)",
         "generation.prompt.light": "ánh sáng (prompt)", "generation.prompt.camera": "máy quay (prompt)", "generation.seed": "seed",
         "continuity.entities": "thực thể", "continuity.time_of_day": "thời điểm", "continuity.match_previous": "nối với shot trước"}
FIELDS = frozenset(LABEL)


# ---------------------------------------------------------------------------------------------------------------- specs
def _num(v, default: float, lo: float, hi: float) -> float:
    try:
        return round(max(lo, min(hi, float(v))), 2)
    except (TypeError, ValueError):
        return default


def _pick(v, allowed: tuple, default):
    """The vocabulary's word for `v`: itself, else the longest word of the vocabulary it contains ("góc thấp" is "thấp", as a
    model writes it), else the default."""
    v = str(v or "").strip().lower()
    exact = next((a for a in allowed if a.lower() == v), None)
    if exact is not None:
        return exact
    within = sorted((a for a in allowed if a and a.lower() in v), key=len, reverse=True)
    return within[0] if within else default


def default_criteria(policy: str) -> list[dict]:
    """What a shot is held to unless the operator says otherwise: it shows its intent, it fits its time, footage is steady."""
    out = [{"check": "match"}, {"check": "duration"}]
    if policy in ("footage", "any"):
        out.append({"check": "no_shake"})
    return out


def criterion(raw: dict) -> dict | None:
    check = raw.get("check")
    if check not in CHECKS:
        return None
    name, by, op, value = CHECKS[check]
    out = {"check": check, "by": by, "op": op, "text": str(raw.get("text") or name)[:200], "required": bool(raw.get("required", by == "auto"))}
    if value is not None or raw.get("value") not in (None, ""):
        out["value"] = raw.get("value") if raw.get("value") not in (None, "") else value
    return out


def normalise(raw: dict, *, camera: tuple[float, float] | None = None) -> dict:
    """A shot spec in its full shape from whatever was given (a model's answer, an edit), every value checked and bounded."""
    raw = raw or {}
    d = raw.get("duration") if isinstance(raw.get("duration"), dict) else {"target": raw.get("duration", raw.get("seconds", 5))}
    target = _num(d.get("target"), 5.0, 0.5, 120)
    f = raw.get("framing") or {}
    src = raw.get("source") if isinstance(raw.get("source"), dict) else {"policy": raw.get("source")}
    policy = _pick({"ai": "generate"}.get(str(src.get("policy") or "").lower(), src.get("policy")), SOURCES, "any")
    g = raw.get("generation") or {}
    p = g.get("prompt") or {}
    c = raw.get("continuity") or {}
    cam = raw.get("camera") or {}
    cx, cy = (camera or (280, 165))
    spec = {
        "intent": str(raw.get("intent") or "").strip()[:300],
        "line": str(raw.get("line") or "").strip()[:600],
        "duration": {"target": target, "min": _num(d.get("min"), max(0.5, round(target * 0.7, 1)), 0.5, 120), "max": _num(d.get("max"), round(target * 1.4, 1), 0.5, 240)},
        "framing": {"size": _pick(f.get("size"), SIZES, "trung"), "angle": _pick(f.get("angle"), ANGLES, "ngang mắt"),
                    "move": _pick(f.get("move"), MOVES, "đứng yên"), "lens": _pick(f.get("lens"), LENSES, "35mm")},
        "camera": {"x": _num(cam.get("x"), cx, 0, PLAN_W), "y": _num(cam.get("y"), cy, 0, PLAN_H),
                   **({"end": {"x": _num(cam["end"].get("x"), cx, 0, PLAN_W), "y": _num(cam["end"].get("y"), cy, 0, PLAN_H)}} if isinstance(cam.get("end"), dict) else {})},
        "direction": _pick(raw.get("direction"), DIRECTIONS, ""),
        "source": {"policy": policy, "query": str(src.get("query") or raw.get("query") or raw.get("intent") or "").strip()[:200]},
        "generation": {"provider": str(g.get("provider") or "").strip()[:60], "provider_video": str(g.get("provider_video") or "").strip()[:60],
                       "model": str(g.get("model") or "").strip()[:80],
                       "prompt": {k: str(p.get(k) or "").strip()[:200] for k in ("subject", "action", "setting", "light", "camera")},
                       "seed": int(g["seed"]) if str(g.get("seed", "")).lstrip("-").isdigit() else None},
        "continuity": {"entities": [str(e).strip()[:60] for e in (c.get("entities") or []) if str(e).strip()][:12],
                       "time_of_day": _pick(c.get("time_of_day"), TIMES, ""), "match_previous": bool(c.get("match_previous", True))},
        "criteria": [x for x in (criterion(r) for r in (raw.get("criteria") or default_criteria(policy)) if isinstance(r, dict)) if x],
    }
    if spec["duration"]["min"] > spec["duration"]["target"]:
        spec["duration"]["min"] = spec["duration"]["target"]
    if spec["duration"]["max"] < spec["duration"]["target"]:
        spec["duration"]["max"] = spec["duration"]["target"]
    return spec


def _get(spec: dict, path: str):
    cur = spec
    for k in path.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


def _set(spec: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = spec
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def _shown(v) -> str:
    if isinstance(v, list):
        return ", ".join(map(str, v)) or "—"
    if isinstance(v, bool):
        return "có" if v else "không"
    return "—" if v in (None, "") else str(v)


def camera_row(k: int, n: int) -> tuple[float, float]:
    """Where a new shot's camera starts on the plan: along the near side of the axis, spread over the width."""
    return (round(90 + (PLAN_W - 180) * (k / max(1, n - 1)) if n > 1 else 280, 1), 165.0)


# ------------------------------------------------------------------------------------------------------------ the planner
IDEA_PROMPT = """Bạn là đạo diễn. Từ ý tưởng dưới đây, dựng storyboard cho một video {seconds} giây, khung {format}.
Chia thành 2 đến 5 cảnh; mỗi cảnh 1 đến 5 shot; tổng thời lượng các shot xấp xỉ {seconds} giây, mỗi shot 3 đến 10 giây.
Ưu tiên nguồn "footage" khi kho có hình phù hợp (danh sách bên dưới), "ai" khi không có, "stock" cho cảnh chung.
Ý tưởng: {idea}
Kho footage hiện có (mô tả ngắn):
{inventory}
Trả về JSON đúng dạng:
{{"chung": {{"bang_mau": [{{"ten": "tên màu", "hex": "#rrggbb"}}], "van_tay": "<tả bối cảnh chung của cả phim, của riêng ý tưởng này>", "giong_dieu": ["<tính từ>"], "phong_cach": ["<một ghi chú về cách quay>"]}},
  "canh": [{{"tieu_de": "...", "muc_dich": "...", "shot": [{{"muc_tieu": "điều shot phải cho người xem thấy", "loi": "lời dẫn hoặc thoại", "giay": 5,
     "co_canh": "{sizes}", "goc": "{angles}", "chuyen_dong": "{moves}", "ong_kinh": "{lenses}", "nguon": "footage|ai|stock",
     "tim": "từ khoá tìm footage", "huong": "phải|trái|", "thuc_the": ["nhân vật, nơi chốn, đạo cụ có trong shot"], "thoi_diem": "{times}"}}]}}]}}
Chỉ trả JSON."""

OPS_PROMPT = """Bạn là đạo diễn, sửa storyboard theo lời người dùng. Chỉ được dùng các thao tác sau (JSON), không làm gì khác:
- {{"op": "set", "shot": "SC3", "field": "<trường>", "value": ...}}   trường là một trong: {fields}
- {{"op": "retime", "shot": "SC3", "seconds": 5}}
- {{"op": "insert", "after": "SC4", "spec": {{"intent": "...", "line": "...", "duration": 4, "framing": {{"size": "cận"}}, "source": "footage|generate|stock|any", "query": "..."}}}}
- {{"op": "delete", "shot": "SC5"}}     - {{"op": "move", "shot": "SC5", "after": "SC2"}}
- {{"op": "split", "shot": "SC3"}}      - {{"op": "merge", "shot": "SC3", "with": "SC4"}}
- {{"op": "add_criterion", "shot": "SC3", "criterion": {{"check": "{checks}", "value": ..., "text": "..."}}}}
- {{"op": "flip_camera", "shot": "SC3"}}
Phạm vi người dùng chọn: {scope}. Shot đang chọn: {current}. Không động tới shot ngoài phạm vi.
Storyboard hiện tại:
{board}
Lời người dùng: {text}
Trả về JSON: {{"tra_loi": "một câu nói điều sẽ làm", "ops": [ ... ]}}"""


class StoryboardPlanner:
    """Planning's side of the storyboard: building it, changing it, reading it, and writing it into the project's script."""

    def __init__(self, store: Storyboard, projects: ProjectStore, adapters: AdapterRegistry, inventory=lambda: []):
        self._store, self._projects, self._adapters, self._inventory = store, projects, adapters, inventory

    # ------------------------------------------------------------------------------------------------------- reading
    def codes(self, project_id: str) -> dict[str, str]:
        """Each shot's code in story order (SC1, SC2…, "story cut"): what the operator and the model call it."""
        return {s.shot_id: f"SC{k + 1}" for k, s in enumerate(self._store.shots(project_id))}

    def resolve(self, project_id: str, ref) -> Shot | None:
        ref = str(ref or "").strip()
        shots = self._store.shots(project_id)
        # SC3 is the code; S3, as the codes were first written (and as a person may still say it), means the same shot.
        m = re.fullmatch(r"(?i)s(?:c)?\s*(\d+)", ref)
        k = int(m.group(1)) - 1 if m else -1
        return shots[k] if 0 <= k < len(shots) else next((s for s in shots if s.shot_id == ref), None)

    def shared(self, project_id: str) -> dict:
        board = self._store.board(project_id) or {}
        return {"idea": board.get("idea", ""), "seconds": board.get("seconds", 60), "palette": board.get("palette", []), "fingerprint": board.get("fingerprint", ""),
                "moods": board.get("moods", []), "style_notes": board.get("style_notes", []), "autonomy": board.get("autonomy", 1)}

    def set_shared(self, project_id: str, **values) -> dict:
        board = {**(self._store.board(project_id) or {})}
        for k in ("idea", "fingerprint"):
            if k in values:
                board[k] = str(values[k] or "").strip()[:600]
        if "seconds" in values:
            board["seconds"] = int(_num(values["seconds"], 60, 5, 1800))
        if "autonomy" in values:
            board["autonomy"] = int(_num(values["autonomy"], 1, 1, 3))
        for k in ("moods", "style_notes"):
            if k in values:
                board[k] = [str(x).strip()[:120] for x in (values[k] or []) if str(x).strip()][:12]
        if "palette" in values:
            board["palette"] = [{"name": str(p.get("name") or "").strip()[:40], "hex": p["hex"]} for p in (values["palette"] or [])
                                if isinstance(p, dict) and re.fullmatch(r"#[0-9a-fA-F]{6}", str(p.get("hex", "")))][:8]
        self._store.set_board(project_id, board)
        return self.shared(project_id)

    # ------------------------------------------------------------------------------------------------------- building
    def from_script(self, project_id: str) -> int:
        """A storyboard from the project's script as it stands: a scene for each of its scenes (one when it has none), a shot for
        each line, framed plainly, footage first. The lines are kept word for word, and a clip already chosen for a line comes
        with it, waiting for the operator."""
        script = self._projects.current_script(project_id)
        if not script or not script["shots"]:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "the project has no script to start a storyboard from", retryable=False)
        self._store.clear(project_id)
        scenes: dict[str, str] = {}
        lines = script["shots"]
        for k, line in enumerate(lines):
            name = line.scene or "Cảnh 1"
            if name not in scenes:
                scenes[name] = self._store.add_scene(project_id, {"title": name, "purpose": "", "subject": {"x": 300, "y": AXIS, "label": ""}})
            spec = normalise({"intent": line.brief or line.text, "line": line.text, "duration": line.target_seconds or max(3.0, round(len(line.text.split()) / 2.6, 1)),
                              "source": "any", "query": line.brief or line.text}, camera=camera_row(k, len(lines)))
            sid = self._store.add_shot(project_id, scenes[name], spec, position=k, made_by="script", note="từ kịch bản")
            self._store.link_script(sid, line.shot_id)
            sel = self._projects.selection(line.shot_id)
            if sel and sel.asset_id and sel.status != "gap" and sel.t_in is not None and sel.t_out is not None:
                # The clip already chosen for the line (by a match, the producer, or the operator) is carried onto its shot, to be
                # looked at and approved there; the shot waits for the operator, nothing is accepted on their behalf.
                others = [{"asset_id": a["asset_id"], "moment_id": a.get("moment_id"), "t_in": a["t_in"], "t_out": a["t_out"], "score": a.get("score"),
                           "text": a.get("reason") or "", "passed": 0, "of": 0, "failed": []} for a in sel.alternates if a.get("asset_id") and a.get("t_in") is not None][:5]
                self._store.set_state(sid, "needs", assignment={"kind": "footage", "asset_id": sel.asset_id, "moment_id": sel.moment_id, "t_in": sel.t_in, "t_out": sel.t_out,
                                                                "score": sel.score, "text": sel.reason or "", "decided_by": sel.decided_by, "candidates": others}, checks=[])
        if not self._store.board(project_id):
            self.set_shared(project_id, idea=self._projects.project(project_id)["title"], seconds=int(sum(_get(s.spec, "duration.target") for s in self._store.shots(project_id))))
        return len(lines)

    def propose_from_idea(self, project_id: str, idea: str, *, seconds: int = 60) -> dict:
        """A whole storyboard proposed from an idea by the writer model: scenes, shots with their contracts, and the look shared by
        every shot. Nothing is changed until it is applied."""
        project = self._projects.project(project_id)
        inventory = "\n".join(self._inventory()[:60]) or "(kho đang trống)"
        prompt = IDEA_PROMPT.format(idea=idea.strip()[:800], seconds=int(seconds), format={"portrait": "dọc 9:16", "square": "vuông"}.get(project["format"], "ngang 16:9"),
                                    inventory=inventory, sizes="|".join(SIZES), angles="|".join(ANGLES), moves="|".join(MOVES), lenses="|".join(LENSES), times="|".join(t for t in TIMES if t))
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": prompt, "json": True, "max_tokens": 3000, "task": "storyboard_idea"})).outputs.get("json") or {}
        scenes = []
        n_shots = sum(len(c.get("shot") or []) for c in out.get("canh") or [] if isinstance(c, dict))
        k = 0
        for c in (out.get("canh") or [])[:8]:
            if not isinstance(c, dict):
                continue
            shots = []
            for s in (c.get("shot") or [])[:8]:
                if not isinstance(s, dict) or not str(s.get("muc_tieu") or "").strip():
                    continue
                shots.append(normalise({"intent": s.get("muc_tieu"), "line": s.get("loi"), "duration": s.get("giay"),
                                        "framing": {"size": s.get("co_canh"), "angle": s.get("goc"), "move": s.get("chuyen_dong"), "lens": s.get("ong_kinh")},
                                        "source": s.get("nguon"), "query": s.get("tim"), "direction": s.get("huong"),
                                        "continuity": {"entities": s.get("thuc_the") or [], "time_of_day": s.get("thoi_diem")}}, camera=camera_row(k, n_shots)))
                k += 1
            if shots:
                scenes.append({"title": str(c.get("tieu_de") or f"Cảnh {len(scenes) + 1}").strip()[:80], "purpose": str(c.get("muc_dich") or "").strip()[:200], "shots": shots})
        if not scenes:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the model gave no usable scenes for this idea", retryable=True)
        chung = out.get("chung") or {}
        # What the model copied from the template instead of writing (placeholders, the instructions' own words) is left out.
        real = lambda x: (x := str(x or "").strip()) and not x.startswith("<") and x not in ("...", "…", "tên màu", "bối cảnh trong một câu") and "tả bối cảnh chung" not in x
        chung = {"van_tay": chung.get("van_tay") if real(chung.get("van_tay")) else "", "giong_dieu": [x for x in chung.get("giong_dieu") or [] if real(x)],
                 "phong_cach": [x for x in chung.get("phong_cach") or [] if real(x)], "bang_mau": [b for b in chung.get("bang_mau") or [] if isinstance(b, dict) and real(b.get("ten"))]}
        shared = {"idea": idea.strip(), "seconds": int(seconds), "fingerprint": str(chung.get("van_tay") or "").strip(),
                  "moods": [str(x) for x in chung.get("giong_dieu") or []], "style_notes": [str(x) for x in chung.get("phong_cach") or []],
                  "palette": [{"name": str(p.get("ten") or ""), "hex": p.get("hex")} for p in chung.get("bang_mau") or [] if isinstance(p, dict)]}
        total = sum(s["duration"]["target"] for c in scenes for s in c["shots"])
        diff = [{"title": c["title"], "old": "", "new": f"{len(c['shots'])} shot · {sum(s['duration']['target'] for s in c['shots']):g}s · {c['purpose']}"} for c in scenes]
        return {"kind": "storyboard", "scenes": scenes, "shared": shared, "diff": diff, "scope": "Toàn bộ", "summary": f"{len(scenes)} cảnh, {k} shot, {total:g}s"}

    def apply_storyboard(self, project_id: str, proposal: dict) -> int:
        self._store.clear(project_id)
        self.set_shared(project_id, **proposal.get("shared", {}))
        n = 0
        for c in proposal["scenes"]:
            scene_id = self._store.add_scene(project_id, {"title": c["title"], "purpose": c.get("purpose", ""), "subject": {"x": 300, "y": AXIS, "label": ""}})
            for j, spec in enumerate(c["shots"]):
                self._store.add_shot(project_id, scene_id, normalise(spec), position=j, made_by="director", note="lập từ ý tưởng")
                n += 1
        return n

    # ----------------------------------------------------------------------------------------------------- operations
    def propose_ops(self, project_id: str, text: str, *, scope: str = "shot", current: str | None = None) -> dict:
        """The writer model reads the operator's words and answers with typed operations only; what is not valid is dropped."""
        shots = self._store.shots(project_id)
        codes = self.codes(project_id)
        scenes = {s.scene_id: s.title for s in self._store.scenes(project_id)}
        board = "\n".join(f"{codes[s.shot_id]} [{scenes.get(s.scene_id, '')}] {s.spec['duration']['target']:g}s · {s.spec['framing']['size']}, {s.spec['framing']['angle']}, "
                          f"{s.spec['framing']['lens']} · nguồn {s.spec['source']['policy']} · hướng {s.spec['direction'] or '—'} · mục tiêu: {s.spec['intent']} · lời: {s.spec['line']}"
                          for s in shots)
        cur = self._store.shot(current) if current else None
        prompt = OPS_PROMPT.format(fields=", ".join(sorted(FIELDS)), checks="|".join(CHECKS), scope={"shot": "chỉ shot đang chọn", "scene": "cảnh của shot đang chọn", "all": "toàn bộ"}.get(scope, scope),
                                   current=codes.get(cur.shot_id, "không có") if cur else "không có", board=board, text=text.strip()[:600])
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": prompt, "json": True, "max_tokens": 1500, "task": "storyboard_ops"})).outputs.get("json") or {}
        ops = [o for o in (out.get("ops") or []) if isinstance(o, dict)]
        allowed = self._in_scope(project_id, scope, cur)
        ops = [o for o in ops if self._targets(project_id, o) <= allowed]
        diff, problems = self.describe(project_id, ops)
        # A change that changes nothing (a value the vocabulary does not have, brought back to what it was) is not shown.
        kept = [(o, d) for o, d in zip(ops, diff) if d and d["old"] != d["new"]]
        return {"kind": "ops", "ops": [o for o, _ in kept], "diff": [d for _, d in kept], "problems": problems,
                "reply": str(out.get("tra_loi") or "").strip()[:300], "scope": {"shot": "Shot này", "scene": "Cảnh", "all": "Toàn bộ"}.get(scope, scope)}

    def _in_scope(self, project_id: str, scope: str, cur: Shot | None) -> set[str]:
        shots = self._store.shots(project_id)
        if scope == "all" or cur is None:
            return {s.shot_id for s in shots} | {"__new__"}
        if scope == "scene":
            return {s.shot_id for s in shots if s.scene_id == cur.scene_id} | {"__new__"}
        return {cur.shot_id}

    def _targets(self, project_id: str, op: dict) -> set[str]:
        out = set()
        for key in ("shot", "with", "after"):
            if op.get(key):
                s = self.resolve(project_id, op[key])
                out.add(s.shot_id if s else "__missing__")
        if op.get("op") == "insert":
            out.add("__new__")
        return out

    def describe(self, project_id: str, ops: list[dict]) -> tuple[list[dict | None], list[str]]:
        """What each operation would change, as the diff the operator reads; None for one that is not valid, with why."""
        codes = self.codes(project_id)
        out, problems = [], []
        for o in ops:
            try:
                out.append(self._diff(project_id, o, codes))
            except ValueError as e:
                out.append(None)
                problems.append(str(e))
        return out, problems

    def _diff(self, project_id: str, o: dict, codes: dict) -> dict:
        kind = o.get("op")
        shot = self.resolve(project_id, o.get("shot")) if o.get("shot") else None
        if kind in ("set", "retime", "delete", "move", "split", "merge", "add_criterion", "remove_criterion", "flip_camera") and shot is None:
            raise ValueError(f"không có shot {o.get('shot')}")
        code = codes.get(shot.shot_id) if shot else ""
        if kind == "set":
            if o.get("field") not in FIELDS:
                raise ValueError(f"trường {o.get('field')} không sửa được")
            trial = copy.deepcopy(shot.spec)
            _set(trial, o["field"], o.get("value"))
            new = _get(normalise(trial), o["field"])
            return {"title": f"{code} · {LABEL[o['field']]}", "old": _shown(_get(shot.spec, o["field"])), "new": _shown(new)}
        if kind == "retime":
            return {"title": f"{code} · thời lượng", "old": f"{shot.spec['duration']['target']:g}s", "new": f"{_num(o.get('seconds'), 5, 0.5, 120):g}s"}
        if kind == "insert":
            after = self.resolve(project_id, o.get("after")) if o.get("after") else None
            if o.get("after") and after is None:
                raise ValueError(f"không có shot {o.get('after')}")
            spec = normalise(o.get("spec") or {})
            if not spec["intent"]:
                raise ValueError("shot mới cần mục tiêu")
            return {"title": f"chèn sau {codes.get(after.shot_id) if after else 'đầu'}", "old": "",
                    "new": f"{spec['intent']} · {spec['source']['policy']}, {spec['framing']['size']}, {spec['duration']['target']:g}s"}
        if kind == "delete":
            return {"title": f"bỏ {code}", "old": shot.spec["intent"], "new": "—"}
        if kind == "move":
            after = self.resolve(project_id, o.get("after")) if o.get("after") else None
            before = self.resolve(project_id, o.get("before")) if o.get("before") else None
            if (o.get("after") and after is None) or (o.get("before") and before is None):
                raise ValueError(f"không có shot {o.get('after') or o.get('before')}")
            if o.get("scene") and not any(sc.scene_id == o["scene"] for sc in self._store.scenes(project_id)):
                raise ValueError(f"không có cảnh {o.get('scene')}")
            where = f"sau {codes.get(after.shot_id)}" if after else f"trước {codes.get(before.shot_id)}" if before else "cuối cảnh" if o.get("scene") else "đầu cảnh"
            return {"title": f"chuyển {code}", "old": "", "new": where}
        if kind == "split":
            t = shot.spec["duration"]["target"]
            return {"title": f"tách {code}", "old": f"{t:g}s", "new": f"{t / 2:g}s + {t / 2:g}s"}
        if kind == "merge":
            other = self.resolve(project_id, o.get("with"))
            if other is None:
                raise ValueError(f"không có shot {o.get('with')}")
            return {"title": f"gộp {code} với {codes.get(other.shot_id)}", "old": "", "new": f"{shot.spec['duration']['target'] + other.spec['duration']['target']:g}s"}
        if kind == "add_criterion":
            c = criterion(o.get("criterion") or {})
            if c is None:
                raise ValueError("tiêu chí không hợp lệ")
            return {"title": f"{code} · nghiệm thu", "old": "", "new": f"{c['text']}" + (f" ({c['op']} {c['value']})" if c.get("value") is not None else "") + (" · tự động" if c["by"] == "auto" else " · người duyệt")}
        if kind == "remove_criterion":
            k = int(o.get("index", -1))
            if not 0 <= k < len(shot.spec["criteria"]):
                raise ValueError("không có tiêu chí đó")
            return {"title": f"{code} · nghiệm thu", "old": shot.spec["criteria"][k]["text"], "new": "—"}
        if kind == "flip_camera":
            side = "trên" if shot.spec["camera"]["y"] < AXIS else "dưới"
            return {"title": f"{code} · máy quay", "old": f"phía {side} trục, hướng {shot.spec['direction'] or '—'}",
                    "new": f"phía {'dưới' if side == 'trên' else 'trên'} trục, hướng {flip_direction(shot.spec['direction']) or '—'}"}
        raise ValueError(f"không có thao tác {kind}")

    def apply(self, project_id: str, ops: list[dict], *, made_by: str, note: str | None = None) -> list[dict]:
        """Apply valid operations in order, each change a new version of the shots it touches; returns what was done."""
        done = []
        for o in ops:
            codes = self.codes(project_id)
            try:
                d = self._diff(project_id, o, codes)
            except ValueError:
                continue
            self._apply_one(project_id, o, made_by=made_by, note=note)
            done.append(d)
        return done

    def _apply_one(self, project_id: str, o: dict, *, made_by: str, note: str | None) -> None:
        kind = o["op"]
        shot = self.resolve(project_id, o.get("shot")) if o.get("shot") else None
        siblings = lambda scene_id: [s for s in self._store.shots(project_id) if s.scene_id == scene_id]
        if kind == "set":
            spec = copy.deepcopy(shot.spec)
            _set(spec, o["field"], o.get("value"))
            self._store.revise(shot.shot_id, normalise(spec), made_by=made_by, note=note or f"đổi {LABEL[o['field']]}")
        elif kind == "retime":
            spec = copy.deepcopy(shot.spec)
            t = _num(o.get("seconds"), 5, 0.5, 120)
            spec["duration"] = {"target": t, "min": min(spec["duration"]["min"], t), "max": max(spec["duration"]["max"], t)}
            self._store.revise(shot.shot_id, normalise(spec), made_by=made_by, note=note or "đổi thời lượng")
        elif kind == "insert":
            after = self.resolve(project_id, o.get("after")) if o.get("after") else None
            scene_id = after.scene_id if after else (self._store.scenes(project_id)[0].scene_id if self._store.scenes(project_id) else
                                                     self._store.add_scene(project_id, {"title": "Cảnh 1", "purpose": "", "subject": {"x": 300, "y": AXIS, "label": ""}}))
            rest = siblings(scene_id)
            pos = (after.position + next((s.position for s in rest if s.position > after.position), after.position + 2)) / 2 if after else (rest[0].position - 1 if rest else 0)
            self._store.add_shot(project_id, scene_id, normalise(o.get("spec") or {}), position=pos, made_by=made_by, note=note or "chèn shot")
        elif kind == "delete":
            self._store.remove_shot(shot.shot_id)
        elif kind == "move":
            # After a shot, before one (a card dropped on another), to the end of a scene, or to the start of its own.
            after = self.resolve(project_id, o.get("after")) if o.get("after") else None
            before = self.resolve(project_id, o.get("before")) if o.get("before") else None
            scene_id = after.scene_id if after else before.scene_id if before else o.get("scene") or shot.scene_id
            rest = [s for s in siblings(scene_id) if s.shot_id != shot.shot_id]
            if after:
                pos = (after.position + next((s.position for s in rest if s.position > after.position), after.position + 2)) / 2
            elif before:
                pos = (before.position + max((s.position for s in rest if s.position < before.position), default=before.position - 2)) / 2
            elif o.get("scene"):
                pos = (rest[-1].position + 1) if rest else 0
            else:
                pos = rest[0].position - 1 if rest else 0
            self._store.place(shot.shot_id, scene_id=scene_id, position=pos)
        elif kind == "split":
            spec = copy.deepcopy(shot.spec)
            half = round(spec["duration"]["target"] / 2, 2)
            spec["duration"] = {"target": half, "min": min(spec["duration"]["min"], half), "max": max(half, spec["duration"]["max"] / 2)}
            self._store.revise(shot.shot_id, normalise(spec), made_by=made_by, note=note or "tách đôi")
            rest = siblings(shot.scene_id)
            nxt = next((s.position for s in rest if s.position > shot.position), shot.position + 2)
            second = copy.deepcopy(spec)
            second["line"] = ""
            self._store.add_shot(project_id, shot.scene_id, normalise(second), position=(shot.position + nxt) / 2, made_by=made_by, note="nửa sau khi tách")
        elif kind == "merge":
            other = self.resolve(project_id, o.get("with"))
            spec = copy.deepcopy(shot.spec)
            t = spec["duration"]["target"] + other.spec["duration"]["target"]
            spec["duration"] = {"target": t, "min": spec["duration"]["min"], "max": max(t, spec["duration"]["max"] + other.spec["duration"]["max"])}
            spec["line"] = " ".join(x for x in (spec["line"], other.spec["line"]) if x)
            self._store.revise(shot.shot_id, normalise(spec), made_by=made_by, note=note or "gộp")
            self._store.remove_shot(other.shot_id)
        elif kind == "add_criterion":
            spec = copy.deepcopy(shot.spec)
            spec["criteria"] = spec["criteria"] + [criterion(o["criterion"])]
            self._store.revise(shot.shot_id, normalise(spec), made_by=made_by, note=note or "thêm tiêu chí")
        elif kind == "remove_criterion":
            spec = copy.deepcopy(shot.spec)
            spec["criteria"] = [c for k, c in enumerate(spec["criteria"]) if k != int(o["index"])]
            self._store.revise(shot.shot_id, normalise(spec), made_by=made_by, note=note or "bỏ tiêu chí")
        elif kind == "flip_camera":
            spec = copy.deepcopy(shot.spec)
            cam = spec["camera"]
            cam["y"] = round(2 * AXIS - cam["y"], 1)
            if "end" in cam:
                cam["end"]["y"] = round(2 * AXIS - cam["end"]["y"], 1)
            spec["direction"] = flip_direction(spec["direction"])
            self._store.revise(shot.shot_id, normalise(spec), made_by=made_by, note=note or "lật sang bên kia trục")

    def revert(self, shot_id: str, version: int, *, made_by: str) -> int:
        old = next((v for v in self._store.versions(shot_id) if v["version"] == int(version)), None)
        if old is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"no version {version} of that shot", retryable=False)
        return self._store.revise(shot_id, old["spec"], made_by=made_by, note=f"quay lại v{version}")

    # ------------------------------------------------------------------------------------------------------- the script
    def sync(self, project_id: str) -> str:
        """Write the storyboard into the project's script: a line for each shot (its words, else its intent), its brief, time and
        picture choices, and the picture the Director gave it, so that matching, generation and the render take it from here."""
        shots = self._store.shots(project_id)
        if not shots:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "the storyboard has no shots", retryable=False)
        lines = [s.spec["line"] or s.spec["intent"] for s in shots]
        script_id = self._projects.save_script(project_id, lines)
        made = self._projects.script(script_id)["shots"]
        for s, line in zip(shots, made):
            g, f = s.spec["generation"]["prompt"], s.spec["framing"]
            subject = ", ".join(x for x in (g.get("subject"), g.get("action") or s.spec["intent"], g.get("setting"), g.get("light")) if x)
            self._projects.annotate_shot(line.shot_id, brief=s.spec["intent"], target_seconds=s.spec["duration"]["target"],
                                         gen={"subject": subject, "shot_size": SIZE_EN.get(f["size"]), "camera": MOVE_EN.get(f["move"]),
                                              "provider_image": s.spec["generation"]["provider"] or None, "provider_video": s.spec["generation"]["provider_video"] or None})
            a = s.assignment
            if a and a.get("asset_id") and s.state in ("accepted", "needs", "stale"):
                self._projects.set_selection(line.shot_id, status="accepted" if s.state == "accepted" else "proposed", asset_id=a["asset_id"], moment_id=a.get("moment_id"),
                                             t_in=a.get("t_in"), t_out=a.get("t_out"), score=a.get("score"), reason="storyboard", decided_by="director")
            elif s.spec["source"]["policy"] == "generate":
                self._projects.set_selection(line.shot_id, status="gap", reason="storyboard: tạo bằng AI", decided_by="director")
            self._store.link_script(s.shot_id, line.shot_id)
        board = self.shared(project_id)
        style = "; ".join(x for x in [board["fingerprint"], *board["moods"], *board["style_notes"]] if x)
        if style:
            self._projects.update_project(project_id, style=style[:600])
        return script_id


SIZE_EN = {"toàn cảnh": "wide shot", "trung": "medium shot", "cận trung": "medium close-up", "cận": "close-up", "đặc tả": "extreme close-up"}
MOVE_EN = {"đứng yên": "static", "theo sau": "tracking shot", "lia ngang": "slow pan", "đẩy tới": "slow push in", "lùi ra": "slow pull out",
           "bay chậm tới": "slow push in", "cầm tay": "handheld"}


def flip_direction(d: str) -> str:
    return {"phải": "trái", "trái": "phải"}.get(d, d)


# ---------------------------------------------------------------------------------------------------------- continuity
def seams(shots: list[Shot], scene_of: dict[str, str], *, colour_gap=None) -> list[dict]:
    """Each cut, read for continuity: colour and light (measured on the two pictures when both have one; else from the time of
    day the specs ask for), direction (a new direction inside a scene crosses the 180° line), the characters' look (an entity
    worn in one shot and not the next while the character stays), and the risk of a jump cut (same size, angle and lens in a
    scene). `colour_gap(a, b)`: the Visual Quality gap of their pictures, or None."""
    out = []
    for a, b in zip(shots, shots[1:]):
        same_scene = scene_of.get(a.scene_id) == scene_of.get(b.scene_id)
        checks = []
        gap = colour_gap(a, b) if colour_gap and a.assignment and b.assignment else None
        shared = set(a.spec["continuity"]["entities"]) & set(b.spec["continuity"]["entities"])
        if gap is not None:
            # A large gap breaks the cut only between two shots of one place (an entity in common); between shots whose content
            # differs it is as likely the content as the light, so it asks for a look (measured on a script with no scenes marked:
            # a bathroom beside a beach read 6 and more).
            st = "pass" if not same_scene or gap <= 2.5 else "warn" if gap <= 4.5 or not shared else "fail"
            detail = ("sang cảnh mới: được phép đổi" if not same_scene else "đo trên hai hình (VQ, tông máy quay)" if shared or gap <= 4.5
                      else "đo trên hai hình; hai shot không có thực thể chung, có thể chỉ là khác nội dung")
            checks.append({"key": "colour", "st": st, "name": "Màu và ánh sáng", "detail": detail, "value": f"{gap:.1f}"})
        else:
            ta, tb = a.spec["continuity"]["time_of_day"], b.spec["continuity"]["time_of_day"]
            jump = same_scene and ta and tb and ta != tb
            checks.append({"key": "colour", "st": "warn" if jump else "pass", "name": "Màu và ánh sáng",
                           "detail": f"cùng cảnh mà đổi thời điểm: {ta} → {tb}" if jump else "chưa có hình để đo; theo thời điểm đặc tả", "value": f"{ta or '—'} → {tb or '—'}"})
        da, db = a.spec["direction"], b.spec["direction"]
        crossed = same_scene and da and db and da != db
        checks.append({"key": "direction", "st": "fail" if crossed else "pass", "name": "Hướng nhìn, hướng đi",
                       "detail": f"đi sang {da} rồi sang {db}: vượt trục 180°" if crossed else "giữ hướng", "value": f"{da or '—'} → {db or '—'}"})
        ea, eb = set(a.spec["continuity"]["entities"]), set(b.spec["continuity"]["entities"])
        lost = sorted(e for e in ea - eb if eb & ea) if same_scene else []
        checks.append({"key": "look", "st": "warn" if lost else "pass", "name": "Nhân vật, trang phục, đạo cụ",
                       "detail": f"có ở shot trước, mất ở shot sau: {', '.join(lost)}" if lost else "giữ nguyên" if ea & eb else "không có thực thể chung", "value": str(len(ea & eb))})
        fa, fb = a.spec["framing"], b.spec["framing"]
        jump = same_scene and fa["size"] == fb["size"] and fa["angle"] == fb["angle"] and fa["lens"] == fb["lens"]
        checks.append({"key": "jump", "st": "warn" if jump else "pass", "name": "Nguy cơ jump cut",
                       "detail": "cùng cỡ cảnh, góc và ống kính" if jump else "cỡ cảnh, góc hoặc ống kính khác", "value": f"{fa['size']} → {fb['size']}"})
        worst = "fail" if any(c["st"] == "fail" for c in checks) else "warn" if any(c["st"] == "warn" for c in checks) else "pass"
        fixes = []
        if any(c["key"] == "colour" and c["st"] != "pass" for c in checks):
            fixes.append({"text": "Khớp màu shot sau theo shot trước", "ops": [{"op": "set", "shot": b.shot_id, "field": "continuity.match_previous", "value": True}]})
        if crossed:
            fixes.append({"text": "Lật máy của shot sau sang bên kia trục", "ops": [{"op": "flip_camera", "shot": b.shot_id}]})
        for e in lost:
            fixes.append({"text": f"Giữ \"{e}\" ở shot sau", "ops": [{"op": "set", "shot": b.shot_id, "field": "continuity.entities", "value": sorted(eb | {e})}]})
        if jump:
            fixes.append({"text": "Đổi cỡ cảnh shot sau sang cận", "ops": [{"op": "set", "shot": b.shot_id, "field": "framing.size", "value": "cận" if fb["size"] != "cận" else "trung"}]})
        out.append({"a": a.shot_id, "b": b.shot_id, "same_scene": same_scene, "checks": checks, "worst": worst, "fixes": fixes})
    return out


def camera_plan(shots: list[Shot], scenes: list) -> list[dict]:
    """Each scene seen from above: its subject on the axis, each shot's camera, the cone of its lens, and which cameras stand on
    the other side of the axis from the scene's first (those flip the screen direction)."""
    out = []
    for sc in scenes:
        mine = [s for s in shots if s.scene_id == sc.scene_id]
        if not mine:
            continue
        first_top = mine[0].spec["camera"]["y"] < AXIS
        subj = sc.data.get("subject") or {"x": 300, "y": AXIS, "label": ""}
        cams = []
        for s in mine:
            cam = s.spec["camera"]
            lens = int(re.sub(r"\D", "", s.spec["framing"]["lens"]) or 35)
            fov = 84 if lens <= 24 else 64 if lens <= 35 else 46 if lens <= 50 else 29 if lens <= 85 else 22
            cams.append({"shot_id": s.shot_id, "x": cam["x"], "y": cam["y"], "end": cam.get("end"), "fov": fov, "crossed": (cam["y"] < AXIS) != first_top,
                         "aim": round(math.degrees(math.atan2(subj["y"] - cam["y"], subj["x"] - cam["x"])), 1)})
        out.append({"scene_id": sc.scene_id, "subject": subj, "cams": cams, "crossed": [c["shot_id"] for c in cams if c["crossed"]]})
    return out
