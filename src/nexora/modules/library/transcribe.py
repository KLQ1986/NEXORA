"""Speech in footage as time-coded text: every word with its own start and end (design v4.0, section 17.2).

Only footage that has sound is listened to, and a recording in which nobody speaks simply yields no words. The words
are kept on the asset; sentences built from them go into the same index as picture descriptions, so one search finds
what was shown and what was said.
"""
from nexora.core.adapter import AdapterError, AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.pipeline import PipelineDefinition, StageDef

TRANSCRIBE = PipelineDefinition("library.transcribe", "1", [StageDef("listen", timeout_seconds=6 * 3600, lane="background", requires=("speech",))])

PAUSE = 0.7              # a silence this long ends a sentence even without a full stop
MAX_WORDS = 20
CLAUSE_WORDS = 8         # a comma ends a sentence once it already has this many words
MIN_SURE = 0.35          # below this the model was guessing; a transcript shows such words as doubtful


def sentences(words: list[dict]) -> list[dict]:
    """Group timed words into sentences: at a full stop, at a pause, at a comma once the sentence is long enough, or when it has run long.
    Speech models often give no pauses and few full stops, so the last two rules do most of the work."""
    out, current = [], []
    for i, word in enumerate(words):
        current.append(word)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or word["text"][-1:] in ".?!…" or nxt["start"] - word["end"] >= PAUSE or len(current) >= MAX_WORDS \
                or (word["text"][-1:] in ",;:" and len(current) >= CLAUSE_WORDS):
            out.append({"t_start": current[0]["start"], "t_end": current[-1]["end"], "text": " ".join(w["text"] for w in current), "words": current})
            current = []
    return out


class Transcription:
    def __init__(self, assets: AssetStore, index: MomentIndex, adapters: AdapterRegistry):
        self._assets, self._index, self._adapters = assets, index, adapters

    def handlers(self) -> dict:
        return {"listen": self._listen}

    def wanted(self, asset_id: str) -> bool:
        meta = self._assets.original(asset_id).metadata
        probe = meta.get("probe", {})
        return bool(probe.get("has_audio")) and not probe.get("audio_only") and "duplicate_of" not in meta

    def words(self, asset_id: str) -> list[dict]:
        return [w for m in self._index.moments(asset_id, level="speech") for w in m.data.get("words", [])]

    def _listen(self, ctx):
        original = self._assets.original(ctx.subject_ref)
        versions = {v.role: v for v in self._assets.versions(ctx.subject_ref)}
        path = self._assets.path_of(original)
        if not path.is_file() and "proxy" in versions:
            path = self._assets.path_of(versions["proxy"])               # the drive with the original is away: the proxy carries the same sound
        words = self._adapters.submit("speech", Request("transcribe", inputs={"path": str(path)}, attempt_id=ctx.claim.attempt_id)).outputs["words"]
        self._index.remove(ctx.subject_ref, "speech")
        made = sentences(words)
        for s in made:
            self._index.upsert(ctx.subject_ref, "speech", round(s["t_start"], 2), round(s["t_end"], 2), s["text"], data={"words": s["words"]}, analyzer="speech:v1")
        embedded = 0
        pending = [m for m in self._index.without_vectors(ctx.subject_ref) if m.level == "speech"]
        try:
            for start in range(0, len(pending), 32):
                batch = pending[start:start + 32]
                vectors = self._adapters.submit("model", Request("embed", inputs={"texts": [m.text for m in batch]}, attempt_id=ctx.claim.attempt_id)).outputs["vectors"]
                for moment, vector in zip(batch, vectors):
                    self._index.set_vector(moment.moment_id, vector)
                embedded += len(batch)
        except AdapterError:
            pass                                    # without the embedding model, speech is still found by its words
        spoken = round(sum(w["end"] - w["start"] for w in words), 1)
        self._assets.update_metadata(original.version_id, speech={"words": len(words), "sentences": len(made), "seconds": spoken,
                                                                 "doubtful": sum(w["p"] < MIN_SURE for w in words)})
        return {"words": len(words), "sentences": len(made), "embedded": embedded}
