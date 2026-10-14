"""Sourcing: find the picture for each line of a script in the operator's footage (design v4.0, section 18.2).

Every shot ends with a selection or a reported gap; nothing is filled silently. The operator reviews before anything is cut.
"""
from nexora.core.adapter import AdapterError, AdapterRegistry, Request
from nexora.core.index import MomentIndex
from nexora.core.intelligence import VideoIntelligence
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


# What a line asks to see, in words an operator writes (design 2026-10-14, group 15): the field it names and the value wanted.
ASKS = [
    (r"đặc tả|extreme close", "shot_size", "đặc tả"), (r"cận cảnh|cận mặt|\bcận\b|close[- ]?up", "shot_size", "cận"),
    (r"trung cảnh|\bmedium shot", "shot_size", "trung"), (r"toàn cảnh|cảnh rộng|\btoàn\b|wide shot|flycam|từ trên cao", "shot_size", "toàn"),
    (r"không (có )?(một )?(ai|người)|vắng (vẻ|người|tanh)", "people", "không"), (r"\bmột (người|cô|anh|chị|bạn|ông|bà)\b", "people", "một"),
    (r"\bhai (người|bạn)|cặp đôi", "people", "hai"), (r"đám đông|đông (người|nghịt)|tấp nập", "people", "đám đông"), (r"nhóm (người|bạn)", "people", "nhóm"),
    (r"trong nhà|trong phòng|nội thất|trong bếp", "place", "trong nhà"), (r"ngoài trời|ngoài đường|ngoài phố|ngoài biển", "place", "ngoài trời"),
    (r"nói (trước|vào|với) (máy|camera|ống kính)|nhìn vào (máy|camera)|talking head", "speaker", "trong khung"),
    (r"từ trên (cao )?nhìn xuống|nhìn xuống|góc cao|top[- ]?down", "angle", "từ trên xuống"), (r"nhìn lên|ngước lên|góc thấp|low angle", "angle", "từ dưới lên"),
]


def asked(line: str) -> dict[str, str]:
    """The fields a line names, with the value it wants: "cận cảnh tay pha cà phê" asks for a close shot."""
    import re
    out: dict[str, str] = {}
    for pattern, field, value in ASKS:
        if field not in out and re.search(pattern, line, re.IGNORECASE):
            out[field] = value
    return out


def spread(hits: list, keep: int) -> list:
    """Keep the best hit of each stretch: hits from the same footage whose times touch, or nearly, say the same thing, so the
    alternates offered are different places, not the next beat of the same view."""
    out = []
    for hit in hits:
        m = hit.moment
        if any(o.moment.asset_id == m.asset_id and m.t_start <= o.moment.t_end + 1.0 and o.moment.t_start <= m.t_end + 1.0 for o in out):
            continue
        out.append(hit)
        if len(out) >= keep:
            break
    return out


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


CUT_MARGIN = 0.15        # seconds kept clear of a cut on either side


def clear_of_cuts(t_in: float, t_out: float, cuts: list[float], *, floor: float = 0.0, ceiling: float | None = None) -> tuple[float, float]:
    """Move a range so that it does not run across a cut in the footage. The range keeps its length and goes to the side of
    the cut that already holds more of it, as long as that side has room before the next cut (or the end of the footage);
    when neither side has room, it is left where it was, since a shot must be as long as its line."""
    inside = [c for c in cuts if t_in + CUT_MARGIN < c < t_out - CUT_MARGIN]
    if not inside:
        return t_in, t_out
    need, cut = t_out - t_in, min(inside, key=lambda c: abs(c - (t_in + t_out) / 2))
    before = max([c for c in cuts if c < cut] + [floor])
    after = min([c for c in cuts if c > cut] + ([ceiling] if ceiling is not None else [float("inf")]))
    left, right = (cut - CUT_MARGIN - need, cut - CUT_MARGIN), (cut + CUT_MARGIN, cut + CUT_MARGIN + need)
    fits_left, fits_right = left[0] >= before, right[1] <= after
    if fits_left and (not fits_right or cut - t_in >= t_out - cut):
        return round(left[0], 2), round(left[1], 2)
    if fits_right:
        return round(right[0], 2), round(right[1], 2)
    return t_in, t_out


class Sourcing:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, index: MomentIndex, *, threshold: float = 0.5, alternates: int = 3,
                 adapters: AdapterRegistry | None = None, judge: bool = False, judge_pass: int = 5, rejected=None, may_accept=None, cuts=None,
                 intel: VideoIntelligence | None = None):
        self._orch, self._projects, self._index = orch, projects, index
        self._adapters, self._judge, self._judge_pass = adapters, judge and adapters is not None, judge_pass
        self._threshold, self._alternates = threshold, alternates
        self._rejected = rejected or (lambda: frozenset())       # assets the operator has set aside: never proposed
        self._cuts = cuts or (lambda asset_id: ([], None))      # asset id -> (where its shots change, how long it is)
        self._may_accept = may_accept or (lambda project: bool(project.get("auto_accept")))      # whether a confident match needs no review; the autonomy level decides
        self._intel = intel                                     # what is known about the footage, from the canonical model (design 2026-10-15)

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
        t_in, t_out = self._whole_shot(hit.moment.asset_id, *fit(hit.moment.t_start, hit.moment.t_end, need))
        return {"moment_id": hit.moment.moment_id, "asset_id": hit.moment.asset_id, "t_in": t_in, "t_out": t_out,
                "score": hit.score, "reason": hit.moment.text}

    def _whole_shot(self, asset_id: str, t_in: float, t_out: float) -> tuple[float, float]:
        """A moment may be shorter than its line needs, and the clip then runs on into the moments after it. It may do so only
        inside the same shot and inside the footage: past the end of the footage it is moved back, across a cut it is moved aside."""
        cuts, length = self._cuts(asset_id)
        if length and t_out > length and t_out - t_in <= length:
            t_in, t_out = round(length - (t_out - t_in), 2), round(float(length), 2)
        return clear_of_cuts(t_in, t_out, cuts, ceiling=length) if cuts else (t_in, t_out)

    def _said(self, line: str, moment) -> str | None:
        """What the operator said before about this stretch of footage for these words: about this very moment, or, when the
        footage has been divided anew since, about a stretch that mostly overlaps it."""
        told = self._projects.feedback(line)
        if moment.moment_id in told:
            return told[moment.moment_id]
        for row in self._projects.feedback_spans(line):
            shared = min(row["t_out"], moment.t_end) - max(row["t_in"], moment.t_start)
            if row["asset_id"] == moment.asset_id and shared > 0 and shared >= 0.5 * min(row["t_out"] - row["t_in"], moment.t_end - moment.t_start):
                return row["verdict"]
        return None

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
            wanted = f"{shot.text} {shot.brief}" if shot.brief else shot.text            # what is said, plus what the operator asked to see
            # What the operator said before about clips for these very words: a clip they turned down is not offered again,
            # and one they chose goes first.
            judged = len(self._projects.feedback(shot.text))
            hits = self._index.search(wanted, limit=3 * (self._alternates + 1) + judged, min_score=self._threshold, exclude=frozenset(used), exclude_assets=self._rejected())
            # What the line asks to see, held against the measured labels that have proved accurate; then one hit per stretch.
            asks = asked(wanted)
            fits = {h.moment.moment_id: (self._intel.fit(h.moment.asset_id, (h.moment.t_start, h.moment.t_end), asks) if self._intel and asks else (0.0, []))
                    for h in hits}
            hits = sorted(hits, key=lambda h: h.score + fits[h.moment.moment_id][0], reverse=True)
            hits = spread(hits, self._alternates + 1 + judged)
            told = {h.moment.moment_id: self._said(shot.text, h.moment) for h in hits}
            hits = [h for h in hits if told[h.moment.moment_id] != "rejected"]
            hits = sorted(hits, key=lambda h: told.get(h.moment.moment_id) != "accepted")[:self._alternates + 1]
            verdicts: dict[str, tuple[int, str]] = {}
            if self._judge and hits:
                for hit in hits:
                    verdicts[hit.moment.moment_id] = self._look(shot.brief or shot.text, hit)
                    ctx.heartbeat()
                hits = sorted((h for h in hits if verdicts[h.moment.moment_id][0] >= self._judge_pass or told.get(h.moment.moment_id) == "accepted"),
                              key=lambda h: (told.get(h.moment.moment_id) == "accepted", verdicts[h.moment.moment_id][0], h.score), reverse=True)
            if not hits:
                self._projects.set_selection(shot.shot_id, status="gap", reason="Không có footage nào đủ khớp với câu này.")
                gaps += 1
                continue
            best, rest = self._candidate(hits[0], need), [self._candidate(h, need) for h in hits[1:]]
            for cand in [best, *rest]:
                why = fits.get(cand["moment_id"], (0.0, []))[1]
                if why:
                    cand["reason"] = f"Khớp {', '.join(why)}. {cand['reason']}"
            if self._judge:
                best["t_in"], best["t_out"] = self._whole_shot(best["asset_id"], *self._locate(shot.text, hits[0], need))
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
        if strong and self._may_accept(project):
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
        line = self._projects.shot(shot_id).text
        if sel.moment_id:                                   # the operator preferred another clip for these words: remember both halves of that
            self._projects.add_feedback(line, sel.moment_id, "rejected", asset_id=sel.asset_id, span=self._span(sel.moment_id, sel.t_in, sel.t_out))
        if chosen.get("moment_id"):
            self._projects.add_feedback(line, chosen["moment_id"], "accepted", asset_id=chosen.get("asset_id"), span=self._span(chosen["moment_id"], chosen.get("t_in"), chosen.get("t_out")))
        old = [{"moment_id": sel.moment_id, "asset_id": sel.asset_id, "t_in": sel.t_in, "t_out": sel.t_out, "score": sel.score, "reason": sel.reason}] if sel.moment_id else []
        rest = [a for i, a in enumerate(sel.alternates) if i != alternate] + old
        self._projects.set_selection(shot_id, status="accepted" if sel.status == "accepted" else "proposed", alternates=rest, decided_by="operator", **_fields(chosen))

    def _span(self, moment_id: str, t_in: float | None, t_out: float | None) -> tuple[float, float] | None:
        """The stretch of footage a verdict is about: the moment it names, or failing that the clip that was shown."""
        moment = self._index.by_id(moment_id)
        if moment is not None:
            return moment.t_start, moment.t_end
        return (t_in, t_out) if t_in is not None and t_out is not None else None

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
        hits = self._index.search(keyword, limit=1, min_score=self._threshold, exclude=frozenset(taken), exclude_assets=self._rejected())
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

    def gap_plan(self, script_id: str, *, stock: bool = False, generate: bool = False) -> list[dict]:
        """For every line still without a picture: the nearest thing the library holds, and the ways out that this
        installation can actually take. The last way out is always to shoot it, so each entry says what to shoot."""
        script = self._projects.script(script_id)
        plan = []
        for n, shot in enumerate(script["shots"], 1):
            sel = self._projects.selection(shot.shot_id)
            if sel is None or sel.status != "gap":
                continue
            wanted = f"{shot.text} {shot.brief}" if shot.brief else shot.text
            near = next(iter(self._index.search(wanted, limit=1, exclude_assets=self._rejected())), None)
            need = max(needed_seconds(shot.text), shot.target_seconds or 0.0)
            ways = []
            if near and near.score >= self._threshold * 0.6:
                ways.append({"way": "near", "text": f"Dùng cảnh gần giống nhất trong kho (khớp {near.score:.0%}) rồi tự xem lại."})
            if stock:
                ways.append({"way": "stock", "text": "Tìm một clip stock có giấy phép cho câu này."})
            if generate:
                ways.append({"way": "generate", "text": "Sinh hình bằng AI cho câu này."})
            ways.append({"way": "reword", "text": "Sửa câu để nói về một hình kho đã có."})
            ways.append({"way": "shoot", "text": f"Quay thêm: {shot.brief or shot.text} Cần ít nhất {need:.0f} giây dùng được."})
            plan.append({"line": n, "shot_id": shot.shot_id, "text": shot.text, "brief": shot.brief, "scene": shot.scene, "seconds": round(need, 1),
                         "near": {"moment_id": near.moment.moment_id, "asset_id": near.moment.asset_id, "text": near.moment.text, "score": near.score,
                                  "t_start": near.moment.t_start, "t_end": near.moment.t_end} if near else None, "ways": ways})
        return plan

    def shot_list(self, script_id: str, *, title: str = "") -> str:
        """What is left to shoot, as a list to take on location."""
        plan = self.gap_plan(script_id)
        lines = [f"# Danh sách cần quay thêm{': ' + title if title else ''}", ""]
        if not plan:
            return "\n".join(lines + ["Mọi câu trong kịch bản đều đã có hình."]) + "\n"
        scene = object()
        for g in plan:
            if g["scene"] != scene:
                scene = g["scene"]
                lines += [f"## {scene or 'Chưa xếp cảnh'}", ""]
            lines.append(f"- [ ] Câu {g['line']}: {g['brief'] or g['text']}")
            lines.append(f"      Lời dẫn: “{g['text']}”. Cần ít nhất {g['seconds']:.0f} giây dùng được, nên quay dư ra mỗi đầu 2 giây.")
        total = sum(g["seconds"] for g in plan)
        return "\n".join(lines + ["", f"Tổng cộng {len(plan)} cảnh, khoảng {total:.0f} giây hình cần có."]) + "\n"

    def _script_of(self, shot_id: str) -> str:
        return self._projects._conn.execute("SELECT script_id FROM shots WHERE shot_id = ?", (shot_id,)).fetchone()[0]

    def mark_gap(self, shot_id: str) -> None:
        sel = self._projects.selection(shot_id)
        if sel and sel.moment_id:                           # "no clip fits": the one shown, and the alternates beside it, were all turned down for these words
            line = self._projects.shot(shot_id).text
            for moment_id, asset_id, t_in, t_out in [(sel.moment_id, sel.asset_id, sel.t_in, sel.t_out)] + [(a.get("moment_id"), a.get("asset_id"), a.get("t_in"), a.get("t_out")) for a in sel.alternates]:
                if moment_id:
                    self._projects.add_feedback(line, moment_id, "rejected", asset_id=asset_id, span=self._span(moment_id, t_in, t_out))
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
            if sel.moment_id and sel.status in ("proposed", "accepted"):
                self._projects.add_feedback(self._projects.shot(sel.shot_id).text, sel.moment_id, "accepted", asset_id=sel.asset_id, span=self._span(sel.moment_id, sel.t_in, sel.t_out))
            if sel.status == "proposed":
                self._projects.set_selection(sel.shot_id, status="accepted", asset_id=sel.asset_id, moment_id=sel.moment_id, t_in=sel.t_in, t_out=sel.t_out,
                                             score=sel.score, reason=sel.reason, alternates=sel.alternates, decided_by=sel.decided_by)
        stage = self._orch.stages(run_id)[0]
        self._orch.decide_review(stage.stage_id, approve=True)
        self._projects.set_match_approved(script_id, True)
