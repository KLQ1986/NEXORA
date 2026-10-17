"""The Director: carries each shot of a project's storyboard to its acceptance where it can, and brings the rest to the operator
(design 2026-10-17). It also holds the conversation: the operator's words become a proposal of typed operations.

For a shot that is not accepted, in story order: its picture is looked for by its source policy (the library's footage, by its
query and intent), every candidate is measured against the shot's automatic criteria, the best that passes all the required
ones is taken, and the shot is accepted on its own only when the autonomy level allows it and nothing waits for a person.
A criterion that cannot be measured (a field Video Intelligence has not earned, footage Visual Quality has not seen) is
reported as such and never passed by default. Generated shots wait for their keyframe, made by the project's generation once
the storyboard is written to the script, and are accepted by the operator (or at the highest level).
"""
from __future__ import annotations

import json

from nexora.core.adapter import AdapterError
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.intelligence import VideoIntelligence
from nexora.core.projects import ProjectStore
from nexora.core.storyboard import Shot, Storyboard
from nexora.core.visual_quality import VisualQuality
from nexora.modules.planning.storyboard import CHECKS, StoryboardPlanner

CANDIDATES = 8


class Director:
    def __init__(self, store: Storyboard, planner: StoryboardPlanner, index: MomentIndex, vi: VideoIntelligence, vq: VisualQuality,
                 assets: AssetStore, projects: ProjectStore, *, colour_gap=None, likeness=None):
        self._store, self._planner, self._index, self._vi, self._vq = store, planner, index, vi, vq
        self._assets, self._projects, self._gap, self._likeness = assets, projects, colour_gap, likeness

    # ---------------------------------------------------------------------------------------------------- the loop
    def run(self, project_id: str, *, only: str | None = None) -> dict:
        """One pass over the storyboard (or one shot): what was accepted, what needs the operator, and why."""
        autonomy = self._planner.shared(project_id)["autonomy"]
        shots = self._store.shots(project_id)
        done = {"accepted": [], "needs": [], "skipped": []}
        previous: Shot | None = None
        for s in shots:
            if (only and s.shot_id != only) or (not only and s.state == "accepted"):
                previous = self._store.shot(s.shot_id)
                done["skipped"].append(s.shot_id)
                continue
            self._store.set_state(s.shot_id, "running")
            state, assignment, checks = self._one(s, previous, autonomy)
            if assignment and previous and previous.assignment and self._gap:
                # Measured once here, kept with the picture: the seam before this shot reads it instead of rendering frames again.
                try:
                    assignment["gap_prev"] = round(float(self._gap(previous.assignment, assignment)), 2)
                except Exception:
                    pass
            self._store.set_state(s.shot_id, state, assignment=assignment, checks=checks)
            done["accepted" if state == "accepted" else "needs"].append(s.shot_id)
            previous = self._store.shot(s.shot_id)
        return done

    def _one(self, s: Shot, previous: Shot | None, autonomy: int) -> tuple[str, dict | None, list]:
        policy = s.spec["source"]["policy"]
        if policy == "generate":
            return self._generated(s, autonomy)
        if policy == "stock":
            return "needs", s.assignment, [{"check": "source", "text": "Footage stock: chọn trong kho stock (OpenMontage) ở phần dựng", "by": "human", "st": "wait", "value": "—"}]
        query = s.spec["source"]["query"] or s.spec["intent"]
        try:
            hits = self._index.search(query, limit=CANDIDATES)
        except Exception:                                    # an index without vectors still answers by words; one that fails says nothing
            hits = []
        tried = []
        for h in hits:
            asset = self._assets.asset(h.moment.asset_id)
            if not asset or asset.get("kind") not in ("video", None) or asset.get("rejected"):
                continue
            a = self._assignment(s, h)
            checks = self._check(s, a, previous)
            tried.append((a, checks))
        if not tried:
            note = "không tìm thấy footage cho shot này" + ("; có thể chuyển sang tạo bằng AI" if policy == "any" else "")
            return "needs", None, [{"check": "source", "text": note, "by": "auto", "st": "fail", "value": query[:60]}]
        rank = lambda t: (all(c["st"] == "pass" for c in t[1] if c["required"] and c["by"] == "auto"), sum(c["st"] == "pass" for c in t[1]), t[0]["score"])
        tried.sort(key=rank, reverse=True)
        best, checks = tried[0]
        best["candidates"] = [{"asset_id": a["asset_id"], "t_in": a["t_in"], "t_out": a["t_out"], "score": a["score"], "text": a["text"],
                               "passed": sum(c["st"] == "pass" for c in cs), "of": len(cs),
                               "failed": [c["text"] for c in cs if c["st"] == "fail"]} for a, cs in tried[:4]]
        ok = all(c["st"] == "pass" for c in checks if c["required"] and c["by"] == "auto")
        waits = any(c["st"] in ("wait", "unmeasured") for c in checks if c["required"])
        return ("accepted" if ok and not waits and autonomy >= 2 else "needs"), best, checks

    def _assignment(self, s: Shot, h) -> dict:
        m = h.moment
        d = s.spec["duration"]
        t_in = float(m.t_start)
        t_out = min(float(m.t_end), t_in + d["target"]) if m.t_end and m.t_end > t_in else t_in + d["target"]
        if t_out - t_in < d["min"]:                           # a moment shorter than the shot: carried on past it, as the cut would
            t_out = t_in + d["target"]
        return {"kind": "footage", "asset_id": m.asset_id, "moment_id": m.moment_id, "t_in": round(t_in, 2), "t_out": round(t_out, 2),
                "score": round(float(h.score), 3), "text": m.text[:200]}

    def _generated(self, s: Shot, autonomy: int) -> tuple[str, dict | None, list]:
        keys = self._projects.generations(s.script_shot, kind="keyframe") if s.script_shot else []
        if not keys:
            return "needs", None, [{"check": "keyframe", "text": "Chưa có ảnh khung: ghi storyboard vào kịch bản rồi tạo ảnh khung", "by": "human", "st": "wait", "value": "—"}]
        a = {"kind": "generated", "asset_id": keys[-1]["asset_id"], "t_in": 0.0, "t_out": s.spec["duration"]["target"], "score": None,
             "text": keys[-1].get("prompt", "")[:200]}
        checks = [{"check": "keyframe", "text": "Ảnh khung đúng ý (người duyệt)", "by": "human", "required": True, "st": "wait", "value": "—"}]
        return ("accepted" if autonomy >= 3 else "needs"), a, checks

    # ---------------------------------------------------------------------------------------------------- measuring
    def _check(self, s: Shot, a: dict, previous: Shot | None) -> list[dict]:
        out = []
        for c in s.spec["criteria"]:
            st, value = self._measure(c, s, a, previous)
            out.append({"check": c["check"], "text": c["text"], "by": c["by"], "required": c["required"], "st": st, "value": value})
        return out

    def _measure(self, c: dict, s: Shot, a: dict, previous: Shot | None) -> tuple[str, str]:
        check, want = c["check"], c.get("value")
        if c["by"] == "human":
            return "wait", "—"
        if check == "match":
            return ("pass" if a["score"] >= float(want or CHECKS["match"][3]) else "fail"), f"{a['score']:.2f}"
        if check == "duration":
            d, length = s.spec["duration"], a["t_out"] - a["t_in"]
            return ("pass" if d["min"] - 0.05 <= length <= d["max"] + 0.05 else "fail"), f"{length:.1f}s"
        if check in ("shot_size", "people"):
            try:
                v = self._vi.value(a["asset_id"], (a["t_in"], a["t_out"]), check, released_only=True)
            except Exception:
                v = None
            if v is None or not v.released:
                return "unmeasured", "chưa kiểm định"
            target = str(want if want not in (None, "") else (s.spec["framing"]["size"] if check == "shot_size" else "")).lower()
            return ("pass" if not target or str(v.value).lower() == target else "fail"), str(v.value)
        if check in ("no_shake", "no_blur"):
            if self._vq.profile(a["asset_id"]) is None:
                return "unmeasured", "VQ chưa đo"
            kind = "shake" if check == "no_shake" else "soft"
            worst = max([d["severity"] for d in self._vq.defects(a["asset_id"]) if d["kind"] == kind and d["t_start"] < a["t_out"] and d["t_end"] > a["t_in"]], default=0.0)
            return ("pass" if worst < float(want or CHECKS[check][3]) else "fail"), f"{worst:.2f}"
        if check == "colour_continuity":
            if previous is None or not previous.assignment or not self._gap:
                return "unmeasured", "chưa có shot trước"
            try:
                gap = self._gap(previous.assignment, a)
            except (AdapterError, Exception):
                return "unmeasured", "không đo được"
            return ("pass" if gap <= float(want or CHECKS[check][3]) else "fail"), f"{gap:.1f}"
        if check == "character":
            return self._character(s, a, float(want or CHECKS["character"][3]))
        return "unmeasured", "—"

    def _character(self, s: Shot, a: dict, want: float) -> tuple[str, str]:
        """Each character the shot names that the project's Bible shows (a reference picture): the face in the shot's picture
        most like it, held against `want`; the least alike of them decides."""
        bible = json.loads((self._projects.project(s.project_id) or {}).get("bible") or "[]")
        named = {e.lower() for e in s.spec["continuity"]["entities"]}
        refs = [e for e in bible if e.get("kind", "character") == "character" and e.get("asset_id") and e["name"].lower() in named]
        if not refs:
            return "unmeasured", "Bible chưa có ảnh nhân vật"
        if not self._likeness:
            return "unmeasured", "chưa có SigLIP"
        scores = []
        for e in refs:
            try:
                v = self._likeness(a, e["asset_id"])
            except Exception:
                v = None
            if v is None:
                return "unmeasured", "không thấy khuôn mặt"
            scores.append(v)
        worst = min(scores)
        return ("pass" if worst >= want else "fail"), f"{worst:.2f}"

    def decide(self, shot_id: str, *, accept: bool) -> None:
        """The operator's word on a shot: accepted (its human criteria with it), or sent back."""
        s = self._store.shot(shot_id)
        checks = [{**c, "st": "pass" if c["by"] == "human" and accept else c["st"]} for c in (s.checks or [])]
        self._store.set_state(shot_id, "accepted" if accept else "needs", checks=checks)

    # ------------------------------------------------------------------------------------------------- conversation
    def say(self, project_id: str, text: str, *, scope: str = "shot", current: str | None = None) -> dict:
        """The operator's words, answered with a proposal of operations (or with why there is none)."""
        self._store.say(project_id, "you", text)
        try:
            p = self._planner.propose_ops(project_id, text, scope=scope, current=current)
        except AdapterError as e:
            mid = self._store.say(project_id, "director", f"Không đọc được yêu cầu lúc này: {str(e)[:160]}")
            return self._store.message(mid)
        if not p["ops"]:
            why = "; ".join(p["problems"][:3])
            mid = self._store.say(project_id, "director", "Không có thay đổi hợp lệ nào cho yêu cầu này" + (f" ({why})." if why else "."))
            return self._store.message(mid)
        mid = self._store.say(project_id, "director", p["reply"] or "Đề xuất bên dưới; chưa có gì thay đổi cho tới khi bạn áp dụng.", proposal=p)
        return self._store.message(mid)

    def propose_idea(self, project_id: str, idea: str, *, seconds: int) -> dict:
        self._store.say(project_id, "you", f"Dựng storyboard từ ý tưởng: {idea}")
        try:
            p = self._planner.propose_from_idea(project_id, idea, seconds=seconds)
        except AdapterError as e:
            mid = self._store.say(project_id, "director", f"Chưa dựng được storyboard: {str(e)[:160]}")
            return self._store.message(mid)
        mid = self._store.say(project_id, "director", f"Storyboard đề xuất: {p['summary']}. Áp dụng thì thay storyboard hiện tại.", proposal=p)
        return self._store.message(mid)

    def settle(self, message_id: str, *, apply: bool) -> list[dict]:
        m = self._store.message(message_id)
        if m is None or m["status"] != "open":
            raise LookupError(message_id)
        p = m["proposal"]
        done = []
        if apply:
            if p["kind"] == "storyboard":
                n = self._planner.apply_storyboard(m["project_id"], p)
                done = [{"title": "storyboard", "old": "", "new": f"{n} shot"}]
            else:
                done = self._planner.apply(m["project_id"], p["ops"], made_by="director", note="theo hội thoại")
            self._store.say(m["project_id"], "director", f"Đã áp dụng {len(done)} thay đổi; shot nào đổi đặc tả sẽ được kiểm lại.")
        self._store.settle(message_id, "applied" if apply else "dropped")
        return done
