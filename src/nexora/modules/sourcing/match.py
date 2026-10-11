"""Sourcing: find the picture for each line of a script in the operator's footage (design v4.0, section 18.2).

Every shot ends with a selection or a reported gap; nothing is filled silently. The operator reviews before anything is cut.
"""
from nexora.core.index import MomentIndex
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.projects import ProjectStore

MATCH = PipelineDefinition("sourcing.match", "1", [StageDef("match", gate=True)])
WORDS_PER_SECOND = 2.6
MIN_SECONDS = 2.5


def needed_seconds(text: str) -> float:
    return round(max(MIN_SECONDS, len(text.split()) / WORDS_PER_SECOND), 2)


def fit(t_start: float, t_end: float, need: float) -> tuple[float, float]:
    """In and out points for `need` seconds: the middle of a longer moment, or from its start if it is shorter."""
    if t_end - t_start >= need:
        t_in = t_start + (t_end - t_start - need) / 2
        return round(t_in, 2), round(t_in + need, 2)
    return round(t_start, 2), round(t_start + need, 2)


class Sourcing:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, index: MomentIndex, *, threshold: float = 0.5, alternates: int = 3):
        self._orch, self._projects, self._index = orch, projects, index
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

    def _match(self, ctx):
        used: set[str] = set()
        matched = gaps = 0
        for shot in self._projects.script(ctx.subject_ref)["shots"]:
            need = needed_seconds(shot.text)
            hits = self._index.search(shot.text, limit=self._alternates + 1, min_score=self._threshold, exclude=frozenset(used))
            if not hits:
                self._projects.set_selection(shot.shot_id, status="gap", reason="Không có footage nào đủ khớp với câu này.")
                gaps += 1
                continue
            best, rest = self._candidate(hits[0], need), [self._candidate(h, need) for h in hits[1:]]
            used.add(best["moment_id"])
            self._projects.set_selection(shot.shot_id, status="proposed", alternates=rest, **best)
            matched += 1
        return {"matched": matched, "gaps": gaps}

    def swap(self, shot_id: str, alternate: int) -> None:
        """Replace the selection of a shot with one of its alternates; the old selection becomes an alternate."""
        sel = self._projects.selection(shot_id)
        chosen = sel.alternates[alternate]
        old = [{"moment_id": sel.moment_id, "asset_id": sel.asset_id, "t_in": sel.t_in, "t_out": sel.t_out, "score": sel.score, "reason": sel.reason}] if sel.moment_id else []
        rest = [a for i, a in enumerate(sel.alternates) if i != alternate] + old
        self._projects.set_selection(shot_id, status="accepted" if sel.status == "accepted" else "proposed", alternates=rest, decided_by="operator", **chosen)

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
