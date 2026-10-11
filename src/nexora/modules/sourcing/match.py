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
MATCH = PipelineDefinition("sourcing.match", "1", [StageDef("match", gate=True)])
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
        return {"matched": matched, "gaps": gaps}

    def swap(self, shot_id: str, alternate: int) -> None:
        """Replace the selection of a shot with one of its alternates; the old selection becomes an alternate."""
        sel = self._projects.selection(shot_id)
        chosen = sel.alternates[alternate]
        old = [{"moment_id": sel.moment_id, "asset_id": sel.asset_id, "t_in": sel.t_in, "t_out": sel.t_out, "score": sel.score, "reason": sel.reason}] if sel.moment_id else []
        rest = [a for i, a in enumerate(sel.alternates) if i != alternate] + old
        self._projects.set_selection(shot_id, status="accepted" if sel.status == "accepted" else "proposed", alternates=rest, decided_by="operator", **_fields(chosen))

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
