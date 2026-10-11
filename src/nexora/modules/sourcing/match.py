"""Sourcing: find the picture for each line of a script in the operator's footage (design v4.0, section 18.2).

Every shot ends with a selection or a reported gap; nothing is filled silently. The operator reviews before anything is cut.
"""
from nexora.core.adapter import AdapterError, AdapterRegistry, Request
from nexora.core.index import MomentIndex
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.projects import ProjectStore

JUDGE_PROMPT = (
    "Đây là {n} khung hình liên tiếp của một đoạn video. Câu lời dẫn cần minh hoạ: \"{line}\".\n"
    "Hình có cho thấy đúng điều câu này nói không? Chấm phu_hop từ 0 đến 10: 0 là không liên quan, 5 là cùng bối cảnh nhưng không đúng ý chính, "
    "10 là thấy rõ đúng điều được nói. Chỉ trả về JSON với khoá phu_hop (số) và ly_do (một câu ngắn nói hình cho thấy gì)."
)
LOCATE_PROMPT = (
    "Đây là {n} khung hình liên tiếp, đánh số từ 1 đến {n}, của một đoạn video. Câu lời dẫn: \"{line}\".\n"
    "Khung hình số mấy cho thấy rõ nhất điều câu này nói? Chỉ trả về JSON với khoá khung (số từ 1 đến {n})."
)
MATCH = PipelineDefinition("sourcing.match", "1", [StageDef("match", gate=True, requires=("model",))])
WORDS_PER_SECOND = 2.6
MIN_SECONDS = 2.5
AUTO_ACCEPT = 8          # judge points (0-10) every selection must reach for a match to be accepted without review


def _fields(candidate: dict) -> dict:
    return {k: candidate[k] for k in ("moment_id", "asset_id", "t_in", "t_out", "score", "reason")}


def needed_seconds(text: str) -> float:
    return round(max(MIN_SECONDS, len(text.split()) / WORDS_PER_SECOND), 2)


def fit(t_start: float, t_end: float, need: float) -> tuple[float, float]:
    """In and out points for `need` seconds: the middle of a longer moment, or from its start if it is shorter."""
    if t_end - t_start >= need:
        t_in = t_start + (t_end - t_start - need) / 2
        return round(t_in, 2), round(t_in + need, 2)
    return round(t_start, 2), round(t_start + need, 2)


class Sourcing:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, index: MomentIndex, *, threshold: float = 0.5, alternates: int = 3,
                 adapters: AdapterRegistry | None = None, judge: bool = False, judge_pass: int = 5):
        self._orch, self._projects, self._index = orch, projects, index
        self._adapters, self._judge, self._judge_pass = adapters, judge and adapters is not None, judge_pass
        self._threshold, self._alternates = threshold, alternates

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(MATCH, {"match": self._match})

    def start_match(self, script_id: str, *, wait=None) -> str:
        self._projects.set_match_approved(script_id, False)
        self._orch.supersede(MATCH.pipeline_id, script_id)
        run_id = self._orch.submit_run(MATCH, subject_ref=script_id)
        if wait:
            wait()
        return run_id

    def _candidate(self, hit, need: float) -> dict:
        t_in, t_out = fit(hit.moment.t_start, hit.moment.t_end, need)
        return {"moment_id": hit.moment.moment_id, "asset_id": hit.moment.asset_id, "t_in": t_in, "t_out": t_out,
                "score": hit.score, "reason": hit.moment.text}

    def _look(self, line: str, hit) -> tuple[int, str]:
        """The model looks at real frames of a candidate and says how well they show the line (0-10).
        This catches descriptions that sound right but belong to the wrong picture."""
        frames = hit.moment.data.get("frames") or [hit.moment.data.get("frame")]
        frames = [f for f in frames if f][:4]
        if not frames:
            return self._judge_pass, ""
        try:
            out = self._adapters.submit("model", Request("describe", inputs={"images": frames}, params={
                "task": "judge", "line": line, "candidate_text": hit.moment.text, "max_tokens": 160,
                "prompt": JUDGE_PROMPT.format(n=len(frames), line=line)})).outputs["json"]
            return max(0, min(10, int(float(out.get("phu_hop", 0))))), str(out.get("ly_do", "")).strip()
        except (AdapterError, ValueError, TypeError):
            return self._judge_pass, ""            # the judge is unavailable: fall back to retrieval alone

    def _locate(self, line: str, hit, need: float) -> tuple[float, float]:
        """Inside a chosen moment, centre the clip on the frame that shows the line best."""
        frames = [f for f in (hit.moment.data.get("frames") or []) if f]
        span = hit.moment.t_end - hit.moment.t_start
        if len(frames) < 2 or span <= need:
            return fit(hit.moment.t_start, hit.moment.t_end, need)
        try:
            out = self._adapters.submit("model", Request("describe", inputs={"images": frames}, params={
                "task": "locate", "line": line, "max_tokens": 60, "prompt": LOCATE_PROMPT.format(n=len(frames), line=line)})).outputs["json"]
            k = max(1, min(len(frames), int(float(out.get("khung", 1)))))
        except (AdapterError, ValueError, TypeError):
            return fit(hit.moment.t_start, hit.moment.t_end, need)
        centre = hit.moment.t_start + (k - 0.5) * span / len(frames)
        t_in = max(hit.moment.t_start, min(centre - need / 2, hit.moment.t_end - need))
        return round(t_in, 2), round(t_in + need, 2)

    def _match(self, ctx):
        used: set[str] = set()
        matched = gaps = 0
        confident: list[int] = []
        for shot in self._projects.script(ctx.subject_ref)["shots"]:
            need = needed_seconds(shot.text)
            hits = self._index.search(shot.text, limit=self._alternates + 1, min_score=self._threshold, exclude=frozenset(used))
            verdicts: dict[str, tuple[int, str]] = {}
            if self._judge and hits:
                for hit in hits:
                    verdicts[hit.moment.moment_id] = self._look(shot.text, hit)
                    ctx.heartbeat()
                hits = sorted((h for h in hits if verdicts[h.moment.moment_id][0] >= self._judge_pass),
                              key=lambda h: (verdicts[h.moment.moment_id][0], h.score), reverse=True)
            if not hits:
                self._projects.set_selection(shot.shot_id, status="gap", reason="Không có footage nào đủ khớp với câu này.")
                gaps += 1
                continue
            best, rest = self._candidate(hits[0], need), [self._candidate(h, need) for h in hits[1:]]
            if self._judge:
                best["t_in"], best["t_out"] = self._locate(shot.text, hits[0], need)
                confident.append(verdicts[best["moment_id"]][0])
                for cand in [best, *rest]:
                    points, why = verdicts[cand["moment_id"]]
                    cand["judge"] = points
                    if why:
                        cand["reason"] = f"{why} ({points}/10). {cand['reason']}"
            used.add(best["moment_id"])
            self._projects.set_selection(shot.shot_id, status="proposed", alternates=rest, **_fields(best))
            matched += 1
        # Review by exception: with the project's gate set to confidence-based, a match with no gap and every
        # selection judged strong on real frames is accepted without waiting. Anything less waits for the operator.
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        strong = self._judge and gaps == 0 and matched > 0 and all(v >= AUTO_ACCEPT for v in confident)
        if project.get("auto_accept") and strong:
            for sel in self._projects.selections(ctx.subject_ref):
                self._projects.set_selection(sel.shot_id, status="accepted", asset_id=sel.asset_id, moment_id=sel.moment_id, t_in=sel.t_in, t_out=sel.t_out,
                                             score=sel.score, reason=sel.reason, alternates=sel.alternates, decided_by="policy")
            self._projects.set_match_approved(ctx.subject_ref, True)
            return {"matched": matched, "gaps": gaps, "auto_approve": True}
        if gaps:
            self._orch.notify("gaps", ctx.claim.run_id, reason=str(gaps))
        return {"matched": matched, "gaps": gaps}

    def swap(self, shot_id: str, alternate: int) -> None:
        """Replace the selection of a shot with one of its alternates; the old selection becomes an alternate."""
        sel = self._projects.selection(shot_id)
        chosen = sel.alternates[alternate]
        old = [{"moment_id": sel.moment_id, "asset_id": sel.asset_id, "t_in": sel.t_in, "t_out": sel.t_out, "score": sel.score, "reason": sel.reason}] if sel.moment_id else []
        rest = [a for i, a in enumerate(sel.alternates) if i != alternate] + old
        self._projects.set_selection(shot_id, status="accepted" if sel.status == "accepted" else "proposed", alternates=rest, decided_by="operator", **_fields(chosen))

    def use_asset(self, shot_id: str, asset_id: str, *, reason: str, seconds: float | None = None, pending: bool = False) -> None:
        """Fill a shot with a whole asset from another strategy (stock or generation); it still goes through review."""
        shot_text = next(s.text for sc in [self._projects.script(self._script_of(shot_id))] for s in sc["shots"] if s.shot_id == shot_id)
        need = seconds or needed_seconds(shot_text)
        old = self._projects.selection(shot_id)
        self._projects.set_selection(shot_id, status="proposed", asset_id=asset_id, t_in=0.0, t_out=need, reason=reason,
                                     alternates=old.alternates if old else [], decided_by="operator")
        if pending:
            self._projects.set_extras(shot_id, pending_asset=asset_id)

    def refine_from_asset(self, shot_id: str, asset_id: str) -> bool:
        """A clip brought in for one line (stock, for example) was proposed whole, before anyone had looked at it. Now that it has been
        described, find the part that shows the line. If no part does, the line is a gap again: a wrong picture is worse than none."""
        sel = self._projects.selection(shot_id)
        if sel is None or sel.asset_id != asset_id or sel.moment_id:
            return False                             # the operator has moved on from this clip, or it was already placed
        text = next(s.text for s in self._projects.script(self._script_of(shot_id))["shots"] if s.shot_id == shot_id)
        need = needed_seconds(text)
        hits = [h for h in self._index.search(text, limit=400) if h.moment.asset_id == asset_id][:4]
        if not hits:                                 # the description shares nothing with the line; still let the model look at the opening
            first = [m for m in self._index.moments(asset_id, level="segment")][:2]
            hits = [type("Hit", (), {"moment": m, "score": 0.0})() for m in first]
        best, why = None, ""
        for hit in hits:
            points, reason = self._look(text, hit) if self._judge else (self._judge_pass if hit.score >= self._threshold else 0, "")
            if points >= self._judge_pass and (best is None or points > best[0]):
                best, why = (points, hit), reason
        note = (sel.reason or "").split(" Đoạn được chọn:")[0]
        if best is None:
            self._projects.set_selection(shot_id, status="gap", alternates=sel.alternates, decided_by="system",
                                         reason=f"Clip stock tải về không có đoạn nào cho thấy điều câu này nói. {note}")
            self._projects.set_extras(shot_id, pending_asset=None)
            return True
        hit = best[1]
        t_in, t_out = self._locate(text, hit, need) if self._judge else fit(hit.moment.t_start, hit.moment.t_end, need)
        self._projects.set_selection(shot_id, status=sel.status, asset_id=asset_id, moment_id=hit.moment.moment_id, t_in=t_in, t_out=t_out, score=hit.score,
                                     reason=f"{note} Đoạn được chọn: {why or hit.moment.text}", alternates=sel.alternates, decided_by=sel.decided_by)
        self._projects.set_extras(shot_id, pending_asset=None)
        return True

    def pending_for(self, asset_id: str) -> list[str]:
        """Shots waiting for this asset to be described before their clip can be placed."""
        rows = self._projects._conn.execute("SELECT shot_id, extras FROM selections WHERE asset_id = ? AND extras LIKE '%pending_asset%'", (asset_id,))
        return [r["shot_id"] for r in rows if __import__("json").loads(r["extras"]).get("pending_asset") == asset_id]

    def use_angle(self, shot_id: str, asset_id: str, offset: float) -> None:
        """Show the same instant from another camera that was lined up with the current one."""
        sel = self._projects.selection(shot_id)
        t_in = round(max(0.0, sel.t_in + offset), 2)
        self._projects.set_selection(shot_id, status=sel.status, asset_id=asset_id, t_in=t_in, t_out=round(t_in + (sel.t_out - sel.t_in), 2), score=sel.score,
                                     reason=f"Cùng thời điểm, góc máy khác. {sel.reason or ''}".strip(), alternates=sel.alternates, decided_by="operator")

    def add_insert(self, shot_id: str, keyword: str) -> dict:
        """Cut to a second picture at the moment a word of the line is spoken. The picture is found by searching for that word;
        the moment is placed by where the word stands in the line, since speech runs at a nearly even pace."""
        keyword = keyword.strip()
        text = next(s.text for s in self._projects.script(self._script_of(shot_id))["shots"] if s.shot_id == shot_id)
        where = text.lower().find(keyword.lower())
        sel = self._projects.selection(shot_id)
        if not keyword or where < 0:
            raise ValueError("Từ này không có trong câu")
        if sel is None or sel.status == "gap":
            raise ValueError("Câu này chưa có hình chính")
        inserts = list(sel.extras.get("inserts", []))
        taken = {sel.moment_id, *(i["moment_id"] for i in inserts)} - {None}
        hits = self._index.search(keyword, limit=1, min_score=self._threshold, exclude=frozenset(taken))
        if not hits:
            raise LookupError(keyword)
        m = hits[0].moment
        insert = {"keyword": keyword, "at": round(where / len(text), 3), "asset_id": m.asset_id, "moment_id": m.moment_id, "t_in": m.t_start, "reason": m.text}
        self._projects.set_extras(shot_id, inserts=sorted([i for i in inserts if i["keyword"].lower() != keyword.lower()] + [insert], key=lambda i: i["at"]))
        return insert

    def remove_insert(self, shot_id: str, keyword: str) -> None:
        sel = self._projects.selection(shot_id)
        self._projects.set_extras(shot_id, inserts=[i for i in sel.extras.get("inserts", []) if i["keyword"] != keyword])

    def set_focus(self, shot_id: str, x: float | None) -> None:
        """Where the subject stands across the frame (0 left, 1 right), as the operator sees it; None hands the choice back to the system."""
        sel = self._projects.selection(shot_id)
        self._projects.set_extras(shot_id, focus=None if x is None else {"asset_id": sel.asset_id, "x": max(0.0, min(1.0, float(x)))})

    def _script_of(self, shot_id: str) -> str:
        return self._projects._conn.execute("SELECT script_id FROM shots WHERE shot_id = ?", (shot_id,)).fetchone()[0]

    def mark_gap(self, shot_id: str) -> None:
        sel = self._projects.selection(shot_id)
        keep = ([{"moment_id": sel.moment_id, "asset_id": sel.asset_id, "t_in": sel.t_in, "t_out": sel.t_out, "score": sel.score, "reason": sel.reason}] if sel and sel.moment_id else []) + (sel.alternates if sel else [])
        self._projects.set_selection(shot_id, status="gap", reason="Người vận hành đánh dấu là chưa có hình phù hợp.", alternates=keep, decided_by="operator")

    def trim(self, shot_id: str, t_in: float, t_out: float) -> None:
        sel = self._projects.selection(shot_id)
        self._projects.set_selection(shot_id, status=sel.status, asset_id=sel.asset_id, moment_id=sel.moment_id, t_in=round(t_in, 2), t_out=round(t_out, 2),
                                     score=sel.score, reason=sel.reason, alternates=sel.alternates, decided_by="operator")

    def approve(self, run_id: str) -> None:
        """The operator accepts the selections as they stand."""
        script_id = self._orch.run_info(run_id)["subject_ref"]
        for sel in self._projects.selections(script_id):
            if sel.status == "proposed":
                self._projects.set_selection(sel.shot_id, status="accepted", asset_id=sel.asset_id, moment_id=sel.moment_id, t_in=sel.t_in, t_out=sel.t_out,
                                             score=sel.score, reason=sel.reason, alternates=sel.alternates, decided_by=sel.decided_by)
        stage = self._orch.stages(run_id)[0]
        self._orch.decide_review(stage.stage_id, approve=True)
        self._projects.set_match_approved(script_id, True)
