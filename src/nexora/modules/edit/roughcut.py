"""Rough cut from what was said (design v4.0, section 19.1).

A recording of someone talking is cut by its words: silences go, a sentence said again keeps its last take, a
sentence that is only "ờ" or "à" goes. What is left becomes a script whose every line is one sentence, already tied
to the stretch of footage in which it is spoken and playing with its own sound. The plan is shown before anything is
made, and the operator may keep or drop any sentence.
"""
import difflib
import re
import unicodedata

from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.projects import ProjectStore

FILLERS = frozenset({"ờ", "à", "ừ", "ừm", "ờm", "ơ", "ạ", "um", "uh", "hmm", "ừa", "ờ thì", "kiểu"})
RETAKE_WINDOW = 3            # a sentence is compared with this many sentences after it
RETAKE_ALIKE = 0.75          # how alike two sentences must be to count as two takes of one line
HEAD, TAIL = 0.12, 0.2       # seconds kept before the first word and after the last, so a cut never clips a syllable
MIN_SURE = 0.35


def _norm(word: str) -> str:
    return re.sub(r"[^\w\s]", "", unicodedata.normalize("NFC", word.lower())).strip()


def plan(sentences: list[dict], *, duration: float | None = None) -> list[dict]:
    """`sentences`: dicts with t_start, t_end, text, words (each word with text, start, end, p), in order.
    Returns one entry per sentence: the range to cut, whether to keep it, and why not when it is dropped."""
    told = []
    for s in sentences:
        words = [w for w in s["words"] if _norm(w["text"])]
        spoken = [w for w in words if _norm(w["text"]) not in FILLERS]
        told.append({"words": spoken, "norm": " ".join(_norm(w["text"]) for w in spoken)})
    out = []
    for i, (s, t) in enumerate(zip(sentences, told)):
        entry = {"index": i, "text": s["text"], "keep": True, "reason": None, "t_in": s["t_start"], "t_out": s["t_end"], "doubtful": False, "take_of": None}
        if not t["words"]:
            entry.update(keep=False, reason="Chỉ có tiếng đệm.")
        else:
            entry["text"] = " ".join(w["text"] for w in t["words"])        # tiếng đệm ở đầu và cuối câu bị bỏ
            entry["t_in"] = max(0.0, round(t["words"][0]["start"] - HEAD, 2))
            entry["t_out"] = round(t["words"][-1]["end"] + TAIL, 2)
            if duration:
                entry["t_out"] = min(entry["t_out"], round(duration, 2))
            entry["doubtful"] = sum(w["p"] < MIN_SURE for w in t["words"]) * 2 > len(t["words"])
            for later in told[i + 1:i + 1 + RETAKE_WINDOW]:
                if not later["norm"]:
                    continue
                alike = difflib.SequenceMatcher(None, t["norm"], later["norm"]).ratio()
                false_start = len(t["norm"]) < len(later["norm"]) and later["norm"].startswith(t["norm"])
                if alike >= RETAKE_ALIKE or false_start:
                    entry.update(keep=False, reason="Câu này được nói lại ngay sau đó; giữ lần nói sau.", take_of=told.index(later, i + 1))
                    break
        out.append(entry)
    # Takes of one line are gathered under the take that is kept, so that the operator can hear them side by side and choose another.
    for entry in out:
        final = entry["take_of"]
        while final is not None and out[final]["take_of"] is not None:
            final = out[final]["take_of"]
        entry["take_of"] = final
    for entry in out:
        entry["takes"] = [e["index"] for e in out if e["take_of"] == entry["index"]] + [entry["index"]] if any(e["take_of"] == entry["index"] for e in out) else []
    for a, b in zip(out, out[1:]):                 # two kept ranges never overlap: the handle of one stops where the next begins
        if a["t_out"] > b["t_in"]:
            a["t_out"] = b["t_in"] = round((a["t_out"] + b["t_in"]) / 2, 2)
    return out


class RoughCut:
    def __init__(self, projects: ProjectStore, assets: AssetStore, index: MomentIndex):
        self._projects, self._assets, self._index = projects, assets, index

    def plan(self, asset_id: str) -> dict:
        moments = self._index.moments(asset_id, level="speech")
        duration = self._assets.original(asset_id).metadata.get("probe", {}).get("duration")
        entries = plan([{"t_start": m.t_start, "t_end": m.t_end, "text": m.text, "words": m.data.get("words", [])} for m in moments], duration=duration)
        kept = sum(e["t_out"] - e["t_in"] for e in entries if e["keep"])
        return {"asset_id": asset_id, "sentences": entries, "source_seconds": duration, "kept_seconds": round(kept, 1),
                "removed_seconds": round((duration or kept) - kept, 1)}

    def apply(self, project_id: str, asset_id: str, *, keep: list[int] | None = None) -> str:
        """Make the plan the project's script: one line per kept sentence, each already holding its stretch of the recording
        and playing its own sound. `keep` overrides the plan's own choice of sentences."""
        entries = self.plan(asset_id)["sentences"]
        chosen = [e for e in entries if (e["index"] in keep if keep is not None else e["keep"])]
        if not chosen:
            raise ValueError("nothing was kept")
        script_id = self._projects.save_script(project_id, [e["text"] for e in chosen])
        for shot, e in zip(self._projects.script(script_id)["shots"], chosen):
            self._projects.set_selection(shot.shot_id, status="accepted", asset_id=asset_id, t_in=e["t_in"], t_out=e["t_out"], decided_by="operator",
                                         reason="Dựng thô theo lời nói: giữ nguyên đoạn này của bản ghi.")
            self._projects.set_extras(shot.shot_id, live_sound=True)
        self._projects.set_match_approved(script_id, True)
        return script_id
