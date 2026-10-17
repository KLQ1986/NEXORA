"""The Semantic Editing Copilot, a mode of the storyboard (Nexora_Semantic_Editing_Copilot_Spec_v1.0, P0; design 2026-10-17).

The operator says what the cut should become ("down to 45 seconds, keep the key points, a stronger opening, no repetition")
over one or more recordings in which someone speaks. The Copilot answers with decisions, one per sentence of the transcript:
keep, remove, or move to the front, each with its reason in the operator's words, the evidence it rests on (the sentence, its
times, what the writer model read it as) and how sure it is. Nothing changes until the operator applies them; applied, the
kept sentences become the storyboard's shots, each holding its stretch of the recording with its own sound, and the Edit step
builds and renders them as any storyboard.

What is measured is kept apart from what a model inferred. Fillers, retakes and pauses come from the rough cut (word times);
repetition is measured as closeness of meaning (embeddings), not shared words; the roles of sentences (hook, point, example,
conclusion…) and how much each carries are the writer model's reading, shown as such. A sentence holding a number, a name, a
disclaimer or a call to action is never cut without review. Reaching a length never silently drops a key point: when the
points cannot all fit, the proposal says what it would take instead.
"""
from __future__ import annotations

import math
import re

from nexora.core.adapter import AdapterError, AdapterRegistry, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.storyboard import Storyboard
from nexora.modules.edit.roughcut import plan as rough_plan
from nexora.modules.planning.ideas import channel_text
from nexora.modules.planning.storyboard import StoryboardPlanner

ROLES = {"hook": "mở đầu cuốn hút", "point": "luận điểm", "example": "ví dụ, bằng chứng", "counter": "phản biện", "transition": "chuyển ý",
         "conclusion": "kết luận", "cta": "kêu gọi hành động", "aside": "ý phụ"}
PRESETS = ("shorten", "opening", "repetition", "vertical")
REPEAT = 0.9                       # how close in meaning a later sentence must be to one kept to count as said again
NEAR_REPEAT = 0.8                  # close enough to ask the operator
PAUSE = 1.0                        # seconds of silence between two words that end a stretch of speech
MAX_WORD, SPOKEN = 1.0, 0.6        # a word longer than this holds silence; what is kept of it
PROMPT = """Bạn là biên tập viên dựng video. Dưới đây là các câu của một đoạn ghi hình có người nói, đánh số, kèm thời lượng.
Yêu cầu của người dựng: "{goal}"
Với mỗi câu, cho biết: vai (một trong {roles}), quan_trong (0 đến 1: câu đóng góp bao nhiêu cho thông điệp chung), ly_do (một câu ngắn).
Rồi liệt kê các luận điểm chính của cả đoạn, mỗi luận điểm kèm số các câu nói về nó.
Các câu:
{lines}
Chỉ trả về JSON: {{"cau": [{{"so": 1, "vai": "...", "quan_trong": 0.8, "ly_do": "..."}}], "luan_diem": [{{"ten": "...", "cau": [1, 2]}}]}}"""
PROTECT = [(re.compile(r"\d"), "có số liệu"),
           (re.compile(r"(lưu ý|không phải lời khuyên|miễn trừ|tham khảo ý kiến|chịu trách nhiệm)", re.I), "có lời lưu ý"),
           (re.compile(r"(đăng ký|theo dõi|bấm|nhấn|link|liên kết|bình luận|chia sẻ)", re.I), "có lời kêu gọi")]
NAME = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-ZĐ][a-zà-ỹđ]+(?:\s[A-ZĐ][a-zà-ỹđ]+)+")


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def protected(text: str) -> list[str]:
    """What in a sentence must not be cut without the operator: numbers, names, disclaimers, calls to action."""
    out = [why for pattern, why in PROTECT if pattern.search(text)]
    if NAME.search(text):
        out.append("có tên riêng")
    return out


class Copilot:
    def __init__(self, store: Storyboard, planner: StoryboardPlanner, index: MomentIndex, assets: AssetStore, adapters: AdapterRegistry):
        self._store, self._planner, self._index, self._assets, self._adapters = store, planner, index, assets, adapters

    def sources(self) -> list[dict]:
        """The recordings someone speaks in, with how much is said, for the operator to choose from."""
        out = []
        for asset_id, n, seconds in self._index.assets_with("speech"):
            asset = self._assets.asset(asset_id)
            if not asset or asset.get("trashed_at"):
                continue
            original = self._assets.original(asset_id)
            proxies = [v for v in self._assets.versions(asset_id) if v.role == "proxy" and self._assets.path_of(v).is_file()]
            out.append({"asset_id": asset_id, "name": self._assets.path_of(original).name, "sentences": n, "spoken_seconds": seconds,
                        "duration": original.metadata.get("probe", {}).get("duration"),
                        "media_url": f"/media/{(proxies[-1] if proxies else original).version_id}"})
        return out

    # ------------------------------------------------------------------------------------------------ the reading
    def _sentences(self, asset_ids: list[str]) -> list[dict]:
        """Every sentence of the recordings, in order, with the rough cut's measured verdict (fillers, retakes) and its range."""
        out = []
        for asset_id in asset_ids:
            moments = self._index.moments(asset_id, level="speech")
            duration = self._assets.original(asset_id).metadata.get("probe", {}).get("duration")
            # A transcribed "sentence" can hold long silences between its words (a recording of someone working, talking now and
            # then): it is split at every pause longer than PAUSE, so each stretch of speech is weighed, and kept, on its own.
            spans = []
            for m in moments:
                words, stretched = self._words(m.data.get("words", []))
                runs, run = [], []
                for w in words:
                    if run and float(w["start"]) - float(run[-1]["end"]) > PAUSE:
                        runs.append(run)
                        run = []
                    run.append(w)
                if run:
                    runs.append(run)
                for r in runs or [[]]:
                    spans.append((m, {"t_start": float(r[0]["start"]) if r else m.t_start, "t_end": float(r[-1]["end"]) if r else m.t_end,
                                      "text": " ".join(str(w["text"]).strip() for w in r) if r else m.text, "words": r,
                                      "stretched": any(w.get("stretched") for w in r) or (not r and stretched)}))
            entries = rough_plan([span for _, span in spans], duration=duration)
            for (m, span), e in zip(spans, entries):
                speaker = (m.data.get("speaker") or {}).get("value") if isinstance(m.data.get("speaker"), dict) else m.data.get("speaker")
                out.append({"asset_id": asset_id, "moment_id": m.moment_id, "text": e["text"], "t_in": e["t_in"], "t_out": e["t_out"],
                            "seconds": round(e["t_out"] - e["t_in"], 2), "measured_drop": None if e["keep"] else e["reason"],
                            "doubtful": e["doubtful"], "stretched": span["stretched"], "speaker": speaker})
        return out

    @staticmethod
    def _words(raw: list[dict]) -> tuple[list[dict], bool]:
        """A recording's words with their times as far as they can be trusted. Whisper leaves no gap between words: it lets a
        word swallow the silence beside it ("biến" lasting 20 s). A word longer than MAX_WORD is taken to hold silence: at the
        head of a stretch the silence is before it, so its end is kept; after another word it is after it, so its start is kept.
        Such words are marked, so the sentence they are in waits for the operator."""
        words, stretched = [], False
        for w in raw:
            if w.get("start") is None or w.get("end") is None:
                continue
            a, b = float(w["start"]), float(w["end"])
            if b - a > MAX_WORD:
                stretched = True
                joined = bool(words) and a - float(words[-1]["end"]) < 0.1
                a, b = (a, a + SPOKEN) if joined else (b - SPOKEN, b)
                w = {**w, "start": round(a, 2), "end": round(b, 2), "stretched": True}
            words.append(w)
        return words, stretched

    def _read(self, sentences: list[dict], goal: str, channel: dict | None = None) -> tuple[dict[int, dict], list[dict], bool]:
        """The writer model's reading of the sentences (role, weight, why) and of the key points; ({}, [], False) without one."""
        lines = "\n".join(f"{k + 1}. ({s['seconds']:.1f}s) {s['text']}" for k, s in enumerate(sentences))
        try:
            out = self._adapters.submit("model", Request("chat", privacy_class=PrivacyClass.CLOUD_ALLOWED, params={
                "prompt": channel_text(channel) + PROMPT.format(goal=goal[:400], roles="|".join(ROLES), lines=lines[:12000]), "json": True, "max_tokens": 2500,
                "task": "copilot_read"})).outputs.get("json") or {}
        except AdapterError:
            return {}, [], False
        read = {}
        for c in out.get("cau") or []:
            try:
                k = int(c.get("so")) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= k < len(sentences):
                role = str(c.get("vai") or "").strip().lower()
                read[k] = {"role": role if role in ROLES else "aside", "weight": max(0.0, min(1.0, float(c.get("quan_trong") or 0.5))),
                           "why": str(c.get("ly_do") or "").strip()[:200]}
        points = []
        for p in out.get("luan_diem") or []:
            ids = [int(x) - 1 for x in p.get("cau") or [] if str(x).isdigit() and 0 < int(x) <= len(sentences)]
            if ids and str(p.get("ten") or "").strip():
                points.append({"name": str(p["ten"]).strip()[:120], "sentences": ids})
        return read, points, bool(read)

    def _vectors(self, texts: list[str]) -> list[list[float]] | None:
        try:
            return self._adapters.submit("model", Request("embed", inputs={"texts": texts})).outputs["vectors"]
        except (AdapterError, KeyError):
            return None

    # ------------------------------------------------------------------------------------------------ the proposal
    def propose(self, project_id: str, asset_ids: list[str], *, goal: str, target_seconds: float | None = None, presets: tuple = (), channel: dict | None = None) -> dict:
        if not asset_ids:
            raise ValueError("chọn ít nhất một bản ghi có lời nói")
        sentences = self._sentences(asset_ids)
        if not sentences:
            raise ValueError("các bản ghi này chưa có lời nói được chép lại")
        read, points, understood = self._read(sentences, goal, channel)
        decisions = [{"decision_id": f"d{k + 1:03d}", "sentence": k, "asset_id": s["asset_id"], "moment_id": s["moment_id"], "text": s["text"],
                      "t_in": s["t_in"], "t_out": s["t_out"], "seconds": s["seconds"], "action": "KEEP", "reasons": [], "confidence": 0.7,
                      "review": "proposed", "evidence": {"transcript": s["text"], "range": [s["t_in"], s["t_out"]], "speaker": s["speaker"],
                                                         "observed": [], "inferred": {}}} for k, s in enumerate(sentences)]
        for d, s in zip(decisions, sentences):
            r = read.get(d["sentence"])
            if r:
                d["role"], d["weight"] = r["role"], r["weight"]
                d["evidence"]["inferred"] = {"role": ROLES[r["role"]], "weight": round(r["weight"], 2), "why": r["why"]}
            else:
                d["role"], d["weight"] = "aside", 0.5
            d["protect"] = protected(s["text"])
            if s["doubtful"]:
                d["evidence"]["observed"].append("lời chép không chắc chắn")
            if s.get("stretched"):
                d["evidence"]["observed"].append("mốc từ không chắc (từ kéo dài qua khoảng lặng)")
            if s["measured_drop"]:                                   # measured: a filler, a take said again
                d.update(action="REMOVE", confidence=0.95)
                d["reasons"].append(s["measured_drop"])
                d["evidence"]["observed"].append(s["measured_drop"])
        # Repetition, measured as closeness of meaning to a sentence already kept.
        if "repetition" in presets or not presets:
            vectors = self._vectors([s["text"] for s in sentences])
            if vectors:
                kept: list[int] = []
                for d in decisions:
                    if d["action"] != "KEEP":
                        continue
                    k = d["sentence"]
                    best = max(((_cos(vectors[k], vectors[j]), j) for j in kept), default=(0.0, None))
                    if best[1] is not None and best[0] >= NEAR_REPEAT:
                        d["evidence"]["observed"].append(f"gần nghĩa với câu {best[1] + 1} ({best[0]:.2f})")
                        if best[0] >= REPEAT and not d["protect"]:
                            d.update(action="REMOVE", confidence=round(min(0.9, best[0]), 2))
                            d["reasons"].append(f"lặp ý câu {best[1] + 1}; câu đó được giữ")
                            continue
                        d["review"] = "needs_review"
                    kept.append(k)
        # What must stay: a hook, the conclusion, each key point at least once, what is protected.
        alive = [d for d in decisions if d["action"] == "KEEP"]
        hook = next((d for d in alive if d["role"] == "hook"), None) or (max(alive[: max(1, len(alive) // 4)], key=lambda d: d["weight"]) if alive else None)
        ending = next((d for d in reversed(alive) if d["role"] in ("conclusion", "cta")), None)
        needed = {id(d) for d in alive if d["protect"]} | ({id(hook)} if hook else set()) | ({id(ending)} if ending else set())
        coverage = []
        for p in points:
            holders = [decisions[k] for k in p["sentences"] if decisions[k]["action"] == "KEEP"]
            if holders:
                needed.add(id(max(holders, key=lambda d: d["weight"])))
            coverage.append({"point": p["name"], "sentences": [k + 1 for k in p["sentences"]]})
        for d in alive:
            if id(d) in needed:
                d["required"] = True
                why = "mở đầu" if d is hook else "kết luận" if d is ending else ("cần giữ: " + ", ".join(d["protect"])) if d["protect"] else "giữ luận điểm"
                d["reasons"].append(why)
        # The length asked for: the required first, then the rest by what they carry; what is left out says why.
        notes = []
        if target_seconds and ("shorten" in presets or not presets):
            must = sum(d["seconds"] for d in alive if d.get("required"))
            if must > target_seconds:
                notes.append(f"Giữ đủ {len(points) or 'các'} luận điểm, mở đầu và kết luận cần {must:.0f} giây, dài hơn {target_seconds:.0f} giây yêu cầu: "
                             f"Copilot giữ chúng và không tự bỏ ý; muốn ngắn hơn thì bỏ bớt một luận điểm.")
            budget = target_seconds - must
            for d in sorted((d for d in alive if not d.get("required")), key=lambda d: -d["weight"]):
                if d["seconds"] <= budget + 0.5:
                    budget -= d["seconds"]
                    d["reasons"].append("đủ chỗ trong độ dài này")
                else:
                    d.update(action="REMOVE", confidence=0.6)
                    d["reasons"].append("không cần cho độ dài này")
                    if d["weight"] >= 0.6 or d["protect"]:
                        d["review"] = "needs_review"
        # A stronger opening: the hook said first, when it is not already.
        if "opening" in presets and hook and hook is not alive[0]:
            hook["action"] = "MOVE"
            hook["reasons"].append("đưa lên đầu: câu cuốn hút nhất")
        for d in decisions:
            if d["action"] == "REMOVE" and d["protect"]:
                d["review"] = "needs_review"
            if not understood and d["action"] != "REMOVE":
                d["review"] = "needs_review"                            # without the model's reading nothing is cut on meaning
            if any(o.startswith(("lời chép không chắc chắn", "mốc từ không chắc")) for o in d["evidence"]["observed"]):
                d["review"] = "needs_review"
        kept = [d for d in decisions if d["action"] in ("KEEP", "MOVE")]
        for c in coverage:
            c["kept"] = any(decisions[k - 1]["action"] in ("KEEP", "MOVE") for k in c["sentences"])
        source = sum(s["seconds"] for s in sentences)
        if not understood:
            notes.append("Không đọc được nghĩa các câu lúc này: chỉ cắt tiếng đệm và câu nói lại; mọi câu khác chờ bạn xem.")
        return {"kind": "copilot", "goal": goal, "presets": list(presets), "target_seconds": target_seconds, "assets": asset_ids,
                "decisions": decisions, "coverage": coverage, "notes": notes,
                "summary": {"source_seconds": round(source, 1), "kept_seconds": round(sum(d["seconds"] for d in kept), 1),
                            "keep": sum(d["action"] == "KEEP" for d in decisions), "move": sum(d["action"] == "MOVE" for d in decisions),
                            "remove": sum(d["action"] == "REMOVE" for d in decisions), "review": sum(d["review"] == "needs_review" for d in decisions)},
                "diff": [{"title": f"{d['decision_id']} {d['action']}", "old": "", "new": d["text"][:120]} for d in decisions if d["action"] != "KEEP"][:30],
                "scope": "Toàn bộ"}

    # ------------------------------------------------------------------------------------------------ applying it
    def apply(self, project_id: str, proposal: dict, *, keep: list[str] | None = None) -> int:
        """The decisions as the operator left them made into the storyboard: one shot per sentence kept (a moved one first),
        holding its stretch of the recording with its own sound. `keep` names the decisions kept, overriding the proposal."""
        decisions = proposal["decisions"]
        chosen = [d for d in decisions if (d["decision_id"] in keep if keep is not None else d["action"] in ("KEEP", "MOVE"))]
        chosen = [d for d in chosen if d["action"] == "MOVE"] + [d for d in chosen if d["action"] != "MOVE"]
        if not chosen:
            raise ValueError("không còn câu nào được giữ")
        shots = [{"intent": d["text"][:160], "line": d["text"], "duration": round(d["t_out"] - d["t_in"], 2), "source": "footage", "query": d["text"][:120],
                  "framing": {"size": "trung"}} for d in chosen]
        self._planner.apply_storyboard(project_id, {"scenes": [{"title": "Copilot", "purpose": proposal.get("goal", "")[:200], "shots": shots}],
                                                    "shared": {"idea": proposal.get("goal", "")}})
        for s, d in zip(self._store.shots(project_id), chosen):
            self._store.set_state(s.shot_id, "accepted", checks=[],
                                  assignment={"kind": "footage", "asset_id": d["asset_id"], "moment_id": d["moment_id"], "t_in": d["t_in"], "t_out": d["t_out"],
                                              "score": None, "text": d["text"], "decided_by": "operator", "treat": {"live_sound": True},
                                              "copilot": {"decision_id": d["decision_id"], "reasons": d["reasons"]}})
        return len(chosen)
