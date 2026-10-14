"""Speech in footage as time-coded text: every word with its own start and end (design v4.0, section 17.2).

Only footage that has sound is listened to, and a recording in which nobody speaks simply yields no words. The words
are kept on the asset; sentences built from them go into the same index as picture descriptions, so one search finds
what was shown and what was said.
"""
import difflib
import re
import tempfile
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.pipeline import PipelineDefinition, StageDef

TRANSCRIBE = PipelineDefinition("library.transcribe", "2", [StageDef("listen", timeout_seconds=6 * 3600, lane="background", requires=("speech",))])

PAUSE = 0.7              # a silence this long ends a sentence even without a full stop
MAX_WORDS = 20
CLAUSE_WORDS = 8         # a comma ends a sentence once it already has this many words
MIN_SURE = 0.35          # below this the model was guessing; a transcript shows such words as doubtful


# What a speech model writes when it hears no one: thanks and requests to subscribe learnt from the subtitles of online videos.
INVENTED = re.compile(r"subscribe|đăng k[ýí] (cho )?kênh|la ?la ?school|ghiền mì gõ|bấm chuông|nhớ like|cảm ơn các bạn đã (theo dõi|xem|lắng nghe)|"
                      r"hẹn gặp lại (các bạn )?(trong|ở) (những |các )?(video|tập)|video hấp dẫn|thank you for watching", re.IGNORECASE)
VOICE_KINDS = frozenset({"speech", "whispering", "shout", "yell", "singing", "children_shouting", "screaming", "laughter", "chatter", "babble", "crowd"})
REPEATS = 3              # the same sentence this many times in a row is the model going round in a loop
SPEECH_FLOOR = 0.3       # a window counts as having a voice in it when a voice is among its likeliest sounds at least this surely


def voiced(windows: list[dict], start: float, end: float) -> float | None:
    """The share of [start, end] that the sound classifier heard a voice in; None when nothing was classified there."""
    inside = [w for w in windows if w["t"] < end and w["t"] + w.get("d", 1.0) > start]
    if not inside:
        return None
    return sum(1 for w in inside if any(k in VOICE_KINDS and c >= SPEECH_FLOOR for k, c in w.get("top", []))) / len(inside)


def drop_invented(made: list[dict], windows: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Take out sentences a speech model invented. Three kinds of evidence, never one alone for a sentence a person could say:
    - the same sentence over and over (three or more in a row): the first is kept;
    - a stock phrase of online videos ("hãy subscribe cho kênh") said twice or more, or where no voice was heard;
    - a sentence where the sound classifier heard no voice at all and the model itself was unsure of the words.
    Returns (kept, dropped); each dropped sentence carries its reason."""
    windows = windows or []
    kept, dropped = [], []
    norm = lambda text: re.sub(r"[^\w\s]", "", text.lower()).strip()
    stock = sum(1 for s in made if INVENTED.search(s["text"]))
    for i, s in enumerate(made):
        text = norm(s["text"])
        run = 0
        for earlier in reversed(made[:i]):
            if difflib.SequenceMatcher(None, norm(earlier["text"]), text).ratio() >= 0.85:
                run += 1
            else:
                break
        heard = voiced(windows, s["t_start"], s["t_end"])
        sure = sum(w.get("p", 1.0) for w in s["words"]) / max(len(s["words"]), 1)
        reason = None
        if run >= REPEATS - 1:
            reason = "lặp lại nguyên văn câu trước nhiều lần"
        elif INVENTED.search(s["text"]) and (stock >= 2 or heard == 0):
            reason = "câu sáo của video trên mạng, không có giọng người tương ứng"
        elif heard == 0 and sure < 0.6:
            reason = "không nghe thấy giọng người ở đoạn này và mô hình không chắc"
        if reason:
            dropped.append({**{k: s[k] for k in ("t_start", "t_end", "text")}, "reason": reason})
        else:
            kept.append(s)
    # A word or two left over from an invented sentence that was cut in pieces ("Mì" of "Ghiền Mì Gõ") goes with it.
    gone = {w for d in dropped for w in norm(d["text"]).split()}
    leftovers = [s for s in kept if len(norm(s["text"]).split()) <= 2 and gone and set(norm(s["text"]).split()) <= gone]
    for s in leftovers:
        kept.remove(s)
        dropped.append({**{k: s[k] for k in ("t_start", "t_end", "text")}, "reason": "mảnh còn lại của một câu bịa đã bỏ"})
    return kept, sorted(dropped, key=lambda d: d["t_start"])


def tighten(words: list[dict], envelope: list[float], rate: int) -> list[dict]:
    """Bring each word's start and end in to where its sound is (design 10-13, section 12). A speech model gives every word
    an end that meets the next word's start, so silence is swallowed: a word can seem to last twenty seconds. The level of the
    file a hundredth of a second at a time says where the voice actually is. The threshold sits 30% of the way from the noise
    floor to the level of speech, and at least 6 dB above the floor; a word keeps at least 60 ms."""
    import math
    if not envelope or not words:
        return words
    db = [20 * math.log10(max(v, 1.0)) for v in envelope]
    ordered = sorted(db)
    floor, loud = ordered[len(ordered) // 10], ordered[min(len(ordered) - 1, len(ordered) * 95 // 100)]
    bar = max(floor + 0.3 * (loud - floor), floor + 6.0)
    out = []
    for w in words:
        a, b = int(w["start"] * rate), max(int(w["start"] * rate) + 1, int(math.ceil(w["end"] * rate)))
        a, b = max(0, min(a, len(db) - 1)), max(1, min(b, len(db)))
        voiced_at = [k for k in range(a, b) if db[k] >= bar]
        if voiced_at:
            start, end = voiced_at[0] / rate, (voiced_at[-1] + 1) / rate
            # A long silence inside one word means the word is at one side of it: keep the stretch nearest the word's start.
            gaps = [(x, y) for x, y in zip(voiced_at, voiced_at[1:]) if (y - x) / rate > 0.6]
            if gaps:
                end = (gaps[0][0] + 1) / rate
            start, end = max(start, w["start"]), min(end, w["end"])
            if end - start < 0.06:
                end = min(w["end"], start + 0.06)
            out.append({**w, "start": round(start, 2), "end": round(end, 2)})
        else:
            out.append({**w, "end": round(min(w["end"], w["start"] + 1.0), 2)})       # no sound found: the word is at its start
    return out


BANDS = 24               # bands of the spectrum a voice is described by
SAME_VOICE = 0.12        # cosine distance under which two sentences are said in the same voice
MOST_SPEAKERS = 4


def voice_print(samples, rate: int):
    """What a voice sounds like over a stretch: the shape of its spectrum in 24 bands on a log scale between 80 Hz and 4 kHz,
    with the spread over time, and the typical pitch. Loudness is taken out, so a near and a far voice of one person agree."""
    import numpy as np
    step = int(rate * 0.025)
    n = len(samples) // step
    if n < 4:
        return None
    frames = samples[: n * step].reshape(n, step) * np.hanning(step)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    energy = power.sum(1)
    voiced = energy > np.percentile(energy, 40)
    if voiced.sum() < 3:
        return None
    freqs = np.fft.rfftfreq(step, 1 / rate)
    edges = np.geomspace(80, min(4000, rate / 2 - 1), BANDS + 1)
    bands = np.stack([power[:, (freqs >= a) & (freqs < b)].sum(1) for a, b in zip(edges, edges[1:])], 1)[voiced]
    logs = np.log(bands + 1e-9)
    logs -= logs.mean(1, keepdims=True)
    lags = np.arange(int(rate / 400), int(rate / 70))
    pitches = []
    for frame in frames[voiced][:: max(1, int(voiced.sum()) // 40)]:
        ac = np.correlate(frame, frame, "full")[len(frame) - 1:]
        if ac[0] > 0 and len(ac) > lags[-1]:
            lag = lags[np.argmax(ac[lags])]
            if ac[lag] / ac[0] > 0.3:
                pitches.append(rate / lag)
    pitch = float(np.median(pitches)) if pitches else 0.0
    return np.concatenate([logs.mean(0), 0.5 * logs.std(0), [np.log(max(pitch, 50.0)) - np.log(150.0)]])


def speakers(prints: list) -> list[int | None]:
    """Group sentences by voice: agglomerative, joining the two closest groups while they are closer than `SAME_VOICE`, at
    most four voices. A sentence too short to have a print gets the voice of the sentence before it. Numbered from 1 in the
    order the voices are first heard."""
    import numpy as np
    known = [i for i, p in enumerate(prints) if p is not None]
    if not known:
        return [None] * len(prints)
    vecs = np.array([prints[i] for i in known], dtype=float)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    groups = [[k] for k in range(len(known))]
    centre = lambda g: vecs[g].mean(0) / (np.linalg.norm(vecs[g].mean(0)) + 1e-9)
    while len(groups) > 1:
        best = None
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                d = 1 - float(centre(groups[a]) @ centre(groups[b]))
                if best is None or d < best[0]:
                    best = (d, a, b)
        if best[0] > SAME_VOICE and len(groups) <= MOST_SPEAKERS:
            break
        _, a, b = best
        groups[a] += groups.pop(b)
    label = {}
    for g in groups:
        for k in g:
            label[known[k]] = g
    order, out, last = [], [], None
    for i in range(len(prints)):
        if i in label:
            g = id(label[i])
            if g not in order:
                order.append(g)
            last = order.index(g) + 1
        out.append(last)
    first = next((x for x in out if x is not None), None)
    return [x if x is not None else first for x in out]


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
        self.store = None                                       # the canonical model, once the domain has handed it over

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
        heard = self._adapters.submit("speech", Request("transcribe", inputs={"path": str(path)}, params={"prompt": self.vocabulary(ctx.subject_ref)},
                                                       attempt_id=ctx.claim.attempt_id)).outputs
        words, windows = heard["words"], []
        if any(c.name == "sound" for c in self._adapters.describe()):
            try:
                windows = self._adapters.submit("sound", Request("listen", inputs={"path": str(path)}, params={"window": 1.0, "hop": 0.5},
                                                                attempt_id=ctx.claim.attempt_id)).outputs["windows"]
            except AdapterError:
                windows = []                        # without the classifier, only repetition and stock phrases are caught
        try:
            level = self._adapters.submit("ffmpeg", Request("envelope", inputs={"path": str(path)}, attempt_id=ctx.claim.attempt_id,
                                                           params={"out": str(Path(tempfile.gettempdir()) / f"nexora-{ctx.subject_ref}-{ctx.claim.attempt_id}.env"), "rate": 100,
                                                                   "max_seconds": original.metadata.get("probe", {}).get("duration") or 36000})).outputs
            words = tighten(words, level["envelope"], level["rate"])
        except AdapterError:
            pass                                    # the words keep the times the model gave
        self._index.remove(ctx.subject_ref, "speech")
        made, dropped = drop_invented(sentences(words), windows)
        words = [w for s in made for w in s["words"]]
        voices = self._voices(path, made, ctx)
        for k, s in enumerate(made):
            data = {"words": s["words"]}
            if voices[k] is not None:
                data["speaker"] = {"value": voices[k], "source": "measured", "confidence": "medium" if len(set(v for v in voices if v)) > 1 else "low"}
            self._index.upsert(ctx.subject_ref, "speech", round(s["t_start"], 2), round(s["t_end"], 2), s["text"], data=data, analyzer="speech:v2")
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
        if self.store is not None and self._assets.asset(ctx.subject_ref) is not None:
            from nexora.modules.intelligence import publish
            from nexora.modules.intelligence.analyzers import BY_NAME
            publish.speech(self.store, ctx.subject_ref, self._index.moments(ctx.subject_ref, level="speech"), BY_NAME["speech"])
        spoken = round(sum(w["end"] - w["start"] for w in words), 1)
        self._assets.update_metadata(original.version_id, speech={"words": len(words), "sentences": len(made), "seconds": spoken,
                                                                 "doubtful": sum(w["p"] < MIN_SURE for w in words), "language": heard.get("language"),
                                                                 "dropped": dropped, "voice_checked": bool(windows)})
        return {"words": len(words), "sentences": len(made), "embedded": embedded, "dropped": len(dropped)}

    def _voices(self, path, made: list[dict], ctx) -> list[int | None]:
        """Who says each sentence, by the sound of the voice; nothing when the sound cannot be read."""
        import numpy as np
        if len(made) < 2:
            return [1 if made else None] * len(made)
        raw = Path(tempfile.gettempdir()) / f"nexora-{ctx.subject_ref}-{ctx.claim.attempt_id}.pcm"
        try:
            got = self._adapters.submit("ffmpeg", Request("pcm", inputs={"path": str(path)}, params={"out": str(raw), "rate": 16000}, attempt_id=ctx.claim.attempt_id)).outputs
            samples = np.fromfile(raw, dtype=np.float32)
        except (AdapterError, OSError):
            return [None] * len(made)
        finally:
            raw.unlink(missing_ok=True)
        rate = got["rate"]
        prints = []
        for s in made:
            spans = [samples[int(w["start"] * rate):int(w["end"] * rate)] for w in s["words"]]
            chunk = np.concatenate(spans) if spans else np.zeros(0, np.float32)
            prints.append(voice_print(chunk, rate) if len(chunk) >= rate * 0.6 else None)
        return speakers(prints)

    def vocabulary(self, asset_id: str) -> str:
        """Names the speech model should expect: what the operator wrote about the recording, its shoot and its title. Names of
        people and places are where speech models go most wrong, and a hint of them in the prompt helps most."""
        original, asset = self._assets.original(asset_id), self._assets.asset(asset_id) or {}
        parts = [asset.get("note") or "", asset.get("title") or "", asset.get("session") or "", self._assets.path_of(original).parent.name]
        text = ". ".join(p.strip() for p in parts if p and p.strip())
        return text[:400]
