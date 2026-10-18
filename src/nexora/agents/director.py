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

from nexora.core import illustration as ILL
from nexora.core.adapter import AdapterError
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.intelligence import VideoIntelligence
from nexora.core.projects import ProjectStore
from nexora.core.storyboard import Shot, Storyboard
from nexora.core.visual_quality import VisualQuality
from nexora.modules.planning.storyboard import CHECKS, StoryboardPlanner

CANDIDATES = 8
OFFERED = 6                                      # candidates kept with a shot, shown as its "other options"
SPEEDS = (0.5, 0.75, 1.0, 1.5, 2.0)
TREATS = ("speed", "stabilise", "live_sound", "sfx", "lipsync", "upscale_ml")


class Director:
    def __init__(self, store: Storyboard, planner: StoryboardPlanner, index: MomentIndex, vi: VideoIntelligence, vq: VisualQuality,
                 assets: AssetStore, projects: ProjectStore, *, colour_gap=None, likeness=None, find=None, remember=None):
        self._store, self._planner, self._index, self._vi, self._vq = store, planner, index, vi, vq
        self._assets, self._projects, self._gap, self._likeness = assets, projects, colour_gap, likeness
        # The clip selection's own search (find: words, seconds, line -> candidates) and its memory of the operator's verdicts
        # (remember: line, moment, verdict, ...): the storyboard picks pictures the way the clip step did, and teaches it back.
        self._find, self._remember = find, remember

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
        ill = s.spec.get("illustration") or {}
        # A shot that evokes is searched by what is to be seen and what it evokes, never by its narration.
        query = ILL.query(s.spec["line"], s.spec["source"]["query"] or s.spec["intent"], ill) if ill.get("mode") in ("associative", "contrast") else (s.spec["source"]["query"] or s.spec["intent"])
        tried = []
        for a in self._candidates(s, query):
            asset = self._assets.asset(a["asset_id"])
            if not asset or asset.get("kind") not in ("video", None) or asset.get("rejected"):
                continue
            tried.append((a, self._check(s, a, previous)))
        if not tried:
            note = "không tìm thấy footage cho shot này" + ("; có thể chuyển sang tạo bằng AI" if policy == "any" else "")
            return "needs", None, [{"check": "source", "text": note, "by": "auto", "st": "fail", "value": query[:60]}]
        rank = lambda t: (all(c["st"] == "pass" for c in t[1] if c["required"] and c["by"] == "auto"), sum(c["st"] == "pass" for c in t[1]), t[0]["score"])
        tried.sort(key=rank, reverse=True)
        best, checks = tried[0]
        if s.assignment and s.assignment.get("treat"):
            best["treat"] = s.assignment["treat"]             # how the operator treats the shot's clip outlives a new search
        best["candidates"] = [self._offer(a, cs) for a, cs in tried[:OFFERED]]
        ok = all(c["st"] == "pass" for c in checks if c["required"] and c["by"] == "auto")
        waits = any(c["st"] in ("wait", "unmeasured") for c in checks if c["required"])
        return ("accepted" if ok and not waits and autonomy >= 2 else "needs"), best, checks

    def _line(self, s: Shot) -> str:
        """The words the operator's verdicts on clips are kept under: the shot's narration, else its intent (as its script line)."""
        return s.spec["line"] or s.spec["intent"]

    def _candidates(self, s: Shot, query: str) -> list[dict]:
        """Footage for a shot: by the clip selection's search when it is wired (pictures and words, verdicts remembered, kept
        inside one shot of the footage), else by the index alone."""
        d = s.spec["duration"]
        if self._find is not None:
            try:
                found = self._find(query, d["target"], self._line(s), s.spec.get("illustration") or None)
            except Exception:
                found = []
            return [{"kind": "footage", "asset_id": c["asset_id"], "moment_id": c.get("moment_id"), "t_in": round(float(c["t_in"]), 2),
                     "t_out": round(float(c["t_out"]), 2), "score": round(float(c.get("score") or 0), 3), "text": str(c.get("reason") or "")[:300],
                     "chosen_before": bool(c.get("chosen_before"))} for c in found]
        try:
            hits = self._index.search(query, limit=CANDIDATES)
        except Exception:                                    # an index without vectors still answers by words; one that fails says nothing
            hits = []
        return [self._assignment(s, h) for h in hits]

    @staticmethod
    def _offer(a: dict, cs: list) -> dict:
        return {"asset_id": a["asset_id"], "moment_id": a.get("moment_id"), "t_in": a["t_in"], "t_out": a["t_out"], "score": a["score"], "text": a["text"],
                "chosen_before": a.get("chosen_before", False), "passed": sum(c["st"] == "pass" for c in cs), "of": len(cs),
                "failed": [c["text"] for c in cs if c["st"] == "fail"]}

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

    # -------------------------------------------------------------------------------------- the operator's picture
    def _previous(self, s: Shot) -> Shot | None:
        shots = self._store.shots(s.project_id)
        i = next(k for k, x in enumerate(shots) if x.shot_id == s.shot_id)
        return shots[i - 1] if i else None

    def _place(self, s: Shot, chosen: dict, others: list[dict], *, state: str | None = None) -> None:
        """Give a shot this picture, measured against its criteria, the other candidates kept beside it."""
        a = {k: chosen[k] for k in ("asset_id", "moment_id", "t_in", "t_out", "score", "text") if k in chosen}
        a.update(kind=chosen.get("kind", "footage"), decided_by="operator")
        if s.assignment and s.assignment.get("treat"):
            a["treat"] = s.assignment["treat"]
        checks = self._check(s, a, self._previous(s))
        a["candidates"] = [self._offer(c, self._check(s, c, None)) if "passed" not in c else c for c in others][:OFFERED]
        self._store.set_state(s.shot_id, state or ("accepted" if s.state == "accepted" else "needs"), assignment=a, checks=checks)

    def _pool(self, s: Shot) -> list[dict]:
        """The shot's picture first, then its other candidates."""
        a = s.assignment or {}
        now = [{k: a[k] for k in ("asset_id", "moment_id", "t_in", "t_out", "score", "text", "kind") if k in a}] if a.get("asset_id") else []
        rest = [c for c in a.get("candidates") or [] if not now or (c["asset_id"], c["t_in"]) != (now[0]["asset_id"], now[0]["t_in"])]
        return now + rest

    def use(self, shot_id: str, candidate: int) -> None:
        """The operator picks one of the shot's other candidates: it becomes its picture, the old one goes back among the others,
        and both verdicts are remembered for these words (as the clip step's swap)."""
        s = self._store.shot(shot_id)
        pool = self._pool(s)
        offered = [c for c in pool[1:]] if s.assignment and s.assignment.get("asset_id") else pool
        if not 0 <= candidate < len(offered):
            raise LookupError(candidate)
        chosen = offered[candidate]
        if self._remember:
            if s.assignment and s.assignment.get("moment_id"):
                self._remember(self._line(s), s.assignment["moment_id"], "rejected", asset_id=s.assignment["asset_id"], t_in=s.assignment["t_in"], t_out=s.assignment["t_out"])
            self._remember(self._line(s), chosen.get("moment_id"), "accepted", asset_id=chosen["asset_id"], t_in=chosen["t_in"], t_out=chosen["t_out"])
        self._place(s, chosen, [c for c in pool if c is not chosen])

    def add_clip(self, shot_id: str, candidate: int) -> str:
        """One of a shot's other candidates becomes a shot of its own, right after it in the same scene: its intent the clip's
        description, its length the clip's, from footage, the picture already given."""
        s = self._store.shot(shot_id)
        pool = self._pool(s)
        offered = pool[1:] if s.assignment and s.assignment.get("asset_id") else pool
        if not 0 <= candidate < len(offered):
            raise LookupError(candidate)
        c = offered[candidate]
        length = round(max(1.0, c["t_out"] - c["t_in"]), 2)
        words = (c.get("text") or "").split(". ")[-1].strip() or s.spec["intent"]
        spec = {"intent": words[:160], "duration": length, "source": "footage", "query": s.spec["source"]["query"],
                "framing": dict(s.spec["framing"]), "entities": list(s.spec["continuity"]["entities"])}
        before = {x.shot_id for x in self._store.shots(s.project_id)}
        self._planner.apply(s.project_id, [{"op": "insert", "after": shot_id, "spec": spec}], made_by="operator", note="thêm clip từ phương án khác")
        new = next(x for x in self._store.shots(s.project_id) if x.shot_id not in before)
        self._place(new, {**c, "kind": "footage"}, [], state="needs")
        return new.shot_id

    def none_fits(self, shot_id: str) -> None:
        """No candidate shows the shot: each of them is turned down for these words, and the shot waits without a picture."""
        s = self._store.shot(shot_id)
        if self._remember:
            for c in self._pool(s):
                self._remember(self._line(s), c.get("moment_id"), "rejected", asset_id=c["asset_id"], t_in=c["t_in"], t_out=c["t_out"])
        self._store.set_state(shot_id, "needs", assignment=None,
                              checks=[{"check": "source", "text": "Không clip nào hợp: tìm stock, đổi câu tìm, hoặc chuyển sang tạo bằng AI", "by": "human", "required": True, "st": "wait", "value": "—"}])

    def trim(self, shot_id: str, t_in: float, t_out: float) -> None:
        s = self._store.shot(shot_id)
        if not s.assignment or not s.assignment.get("asset_id"):
            raise LookupError(shot_id)
        if not 0 <= t_in < t_out:
            raise ValueError("đoạn cắt không hợp lệ")
        self._place(s, {**s.assignment, "t_in": round(t_in, 2), "t_out": round(t_out, 2)}, self._pool(s)[1:])

    def treat(self, shot_id: str, **options) -> dict:
        """How the shot's clip is treated in the cut (the clip step's options), kept with its picture and written to the cut on
        approval: speed, stabilise, live_sound, sfx, lipsync, upscale_ml."""
        s = self._store.shot(shot_id)
        if not s.assignment or not s.assignment.get("asset_id"):
            raise LookupError(shot_id)
        t = dict(s.assignment.get("treat") or {})
        for k, v in options.items():
            if k == "speed":
                t[k] = min(SPEEDS, key=lambda x: abs(x - float(v or 1.0)))
            elif k == "sfx":
                t[k] = v if v and self._assets.asset(str(v)) else None
            elif k in TREATS:
                t[k] = bool(v)
        self._store.set_state(shot_id, s.state, assignment={**s.assignment, "treat": t}, checks=s.checks)
        return t

    def use_asset(self, shot_id: str, asset_id: str, *, reason: str) -> None:
        """A whole clip brought in for this shot (stock): its picture, from its start, as long as the shot."""
        s = self._store.shot(shot_id)
        self._place(s, {"kind": "footage", "asset_id": asset_id, "moment_id": None, "t_in": 0.0, "t_out": float(s.spec["duration"]["target"]), "score": None, "text": reason},
                    self._pool(s))

    def approve(self, project_id: str) -> dict:
        """The operator's word on the whole storyboard: written to the script with each shot's picture, its other candidates and
        its treatment, every picture accepted, and the clips counted as approved, so the cut can be rendered."""
        script_id = self._planner.sync(project_id)
        by_line = {s.script_shot: s for s in self._store.shots(project_id)}
        pictured = missing = 0
        for line in self._projects.script(script_id)["shots"]:
            s = by_line.get(line.shot_id)
            a = s.assignment if s else None
            if not a or not a.get("asset_id"):
                missing += 1
                continue
            alts = [{"moment_id": c.get("moment_id"), "asset_id": c["asset_id"], "t_in": c["t_in"], "t_out": c["t_out"], "score": c.get("score"), "reason": c.get("text")}
                    for c in (a.get("candidates") or []) if (c["asset_id"], c["t_in"]) != (a["asset_id"], a["t_in"])]
            self._projects.set_selection(line.shot_id, status="accepted", asset_id=a["asset_id"], moment_id=a.get("moment_id"), t_in=a["t_in"], t_out=a["t_out"],
                                         score=a.get("score"), reason=a.get("text") or "storyboard", alternates=alts, decided_by="operator")
            if a.get("treat"):
                self._projects.set_extras(line.shot_id, **a["treat"])
            if self._remember and a.get("moment_id"):
                self._remember(line.text, a["moment_id"], "accepted", asset_id=a["asset_id"], t_in=a["t_in"], t_out=a["t_out"])
            if s.state != "accepted":
                self._store.set_state(s.shot_id, "accepted", assignment=a, checks=s.checks)
            pictured += 1
        self._projects.set_match_approved(script_id, True)
        return {"script_id": script_id, "pictured": pictured, "missing": missing}

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
        if apply and p["kind"] == "copilot":
            raise ValueError("a Copilot proposal is applied with the decisions the operator kept")
        if apply:
            if p["kind"] == "storyboard":
                n = self._planner.apply_storyboard(m["project_id"], p)
                done = [{"title": "storyboard", "old": "", "new": f"{n} shot"}]
            else:
                done = self._planner.apply(m["project_id"], p["ops"], made_by="director", note="theo hội thoại")
            self._store.say(m["project_id"], "director", f"Đã áp dụng {len(done)} thay đổi; shot nào đổi đặc tả sẽ được kiểm lại.")
        self._store.settle(message_id, "applied" if apply else "dropped")
        return done
