"""The Video Intelligence domain at work (design 2026-10-15): it takes a recording the library has taken in, measures and
divides it, recognises what is in it, listens to it, describes it, and keeps everything in the canonical model. It knows
nothing of projects, scripts or editors; they read what it keeps through `nexora.core.intelligence.VideoIntelligence`.

Order of work for a new recording: structure (signals, shots, beats) → profile (frames looked at, sound listened to, sensors
read, fields joined) → understand (beats described, summary, index); speech in parallel, and a new division of the beats
when the words become known.
"""
from nexora.core.adapter import AdapterError
from nexora.core.assets import AssetStore
from nexora.core.intelligence_store import IntelligenceStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineRegistry
from nexora.modules.intelligence.analysis import STRUCTURE, Analysis
from nexora.modules.intelligence.analyzers import ANALYZERS
from nexora.modules.intelligence.structure import beat_seconds

class Intelligence:
    def __init__(self, orch: Orchestrator, assets: AssetStore, store: IntelligenceStore, analysis: Analysis, *, profiler=None, understanding=None, transcription=None):
        self._orch, self._assets, self.store = orch, assets, store
        self.analysis, self.profiler = analysis, profiler
        self._understanding, self._transcription = understanding, transcription
        self.on_understood = []                     # called with an asset id once it has been described and indexed
        for analyzer in ANALYZERS:
            store.declare(analyzer)
        for part in (analysis, profiler, understanding, transcription):
            if part is not None:
                part.store = store                   # every analyzer writes what it learns into the canonical model

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(STRUCTURE, self.analysis.handlers(), on_success=lambda run_id, asset_id: self.profile(asset_id))
        if self.profiler is not None:
            from nexora.modules.intelligence.profiler import PROFILE
            # The profile comes before the description: what was measured and recognised is what the model is told about.
            registry.register(PROFILE, self.profiler.handlers(), on_success=lambda run_id, asset_id: self.understand(asset_id, force=True))
        if self._transcription:
            from nexora.modules.intelligence.transcribe import TRANSCRIBE
            registry.register(TRANSCRIBE, self._transcription.handlers(), on_success=lambda run_id, asset_id: self.redivide(asset_id))
        if self._understanding:
            from nexora.modules.intelligence.understand import UNDERSTAND
            registry.register(UNDERSTAND, self._understanding.handlers(), on_success=lambda run_id, asset_id: [self.follow(asset_id)] + [listener(asset_id) for listener in self.on_understood])

    # ------------------------------------------------------------------------------------------- what the library hands over
    def taken_in(self, asset_id: str) -> None:
        """A recording has been taken in by the library: analyse it."""
        meta = self._assets.original(asset_id).metadata
        if "duplicate_of" in meta:
            return
        kind = (self._assets.asset(asset_id) or {}).get("kind")
        if kind == "image":
            self.understand(asset_id)
            return
        if kind != "video":
            return
        self.analyse(asset_id, once=True)
        self.transcribe(asset_id)

    def noted(self, asset_id: str, note: str | None) -> None:
        """The operator wrote a note about a recording: it is what they know about it, found by search like what was seen."""
        if note is None or self._understanding is None:
            return
        index = self._understanding._index
        index.remove(asset_id, "note", only=lambda m: not m.data.get("kept"))     # a correction kept from an earlier division is not the note
        if note.strip():
            duration = self._assets.original(asset_id).metadata.get("probe", {}).get("duration") or 0.0
            index.upsert(asset_id, "note", 0.0, round(float(duration), 1), note.strip())
            index.correct(index.get(asset_id, "note", 0.0, round(float(duration), 1)).moment_id, note.strip())      # the operator's words
            try:
                self._understanding.embed_pending(asset_id)
            except AdapterError:
                pass                                 # found by its words until the embedding model is back

    def publish_existing(self, asset_id: str) -> dict:
        """Put what was already learnt about a recording into the canonical model, from the files and the index kept for it,
        without analysing it again. For a library analysed before the canonical model existed."""
        from nexora.modules.intelligence import publish
        from nexora.modules.intelligence.analyzers import BY_NAME
        done = {}
        made = self.analysis.structure(asset_id)
        if made:
            publish.structure(self.store, asset_id, made, BY_NAME["structure"]); done["structure"] = len(made.get("beats", []))
        if self.profiler is not None and self.profiler.profile(asset_id):
            self.profiler.build(asset_id); done["profile"] = True
        if self._understanding is not None:
            index = self._understanding._index
            beats = index.moments(asset_id, level="segment")
            if beats:
                publish.descriptions(self.store, asset_id, beats, BY_NAME["describe"]); done["descriptions"] = len(beats)
            found = [m.data["event"] for m in index.moments(asset_id, level="event") if m.data.get("event")]
            publish.events(self.store, asset_id, found, BY_NAME["events"]); done["events"] = len(found)
            video = index.moments(asset_id, level="video")
            if video and video[0].data.get("detail"):
                publish.summary(self.store, asset_id, video[0].data["detail"])
            sentences = index.moments(asset_id, level="speech")
            publish.speech(self.store, asset_id, sentences, BY_NAME["speech"]); done["sentences"] = len(sentences)
        if self.profiler is not None and done.get("profile"):
            shoot = self.profiler.shoot_of(asset_id)
            publish.scenes(self.store, self.profiler.scenes(shoot), shoot, BY_NAME["scenes"])
            everyone = [a["asset_id"] for a in self._assets.assets() if a["kind"] == "video"]
            publish.entities(self.store, "person", self.profiler.people(everyone))
            publish.entities(self.store, "place", self.profiler.places(everyone))
            done["followed"] = self.follow(asset_id)
        return done

    def settle_flag(self, moment_id: str, index: int, state: str, note: str | None = None) -> list[dict]:
        """The operator closes a flag on a beat: "resolved" (put right, or the model was right after all) or "ignored"."""
        import time
        idx = self._understanding._index if self._understanding else None
        moment = idx.by_id(moment_id) if idx else None
        if moment is None or state not in ("open", "resolved", "ignored"):
            raise ValueError("bad_flag")
        flags = list(moment.data.get("flags") or [])
        if not 0 <= index < len(flags):
            raise LookupError(index)
        flags[index] = {**flags[index], "state": state, "settled_at": time.time(), **({"note": note} if note else {})}
        idx.merge_data(moment.moment_id, flags=flags)
        self.store.observe(moment.asset_id, moment.t_start, moment.t_end, "flags", flags, source="measured", confidence="high", analyzer="operator")
        return flags

    def name_person(self, key: str, name: str) -> None:
        """The operator names a person found in the library; the name follows them through every later grouping."""
        from nexora.modules.intelligence import publish
        self.profiler.name_person(key, name)
        everyone = [a["asset_id"] for a in self._assets.assets() if a["kind"] == "video"]
        publish.entities(self.store, "person", self.profiler.people(everyone))

    def follow(self, asset_id: str) -> dict:
        """Follow what the beats of a recording show into entities of the library (design 2026-10-15, section 9 E): things named
        beat after beat, people and animals known again across cuts, and where every sound comes from."""
        from nexora.modules.intelligence import publish
        from nexora.modules.intelligence.analyzers import BY_NAME
        if self.profiler is None or self._assets.asset(asset_id) is None:
            return {}
        everyone = [a["asset_id"] for a in self._assets.assets() if a["kind"] == "video"]
        things, subjects, sounds = self.profiler.things(everyone), self.profiler.subjects(everyone), self.profiler.sounds(asset_id)
        publish.entities(self.store, "thing", things)
        publish.entities(self.store, "subject", subjects)
        publish.followed(self.store, asset_id, sounds, BY_NAME["follow"])
        return {"things": len(things), "subjects": len(subjects), "sounds": len(sounds)}

    def _motion(self, asset_id: str, a: float, b: float) -> float:
        """How much the subject moves in a stretch of a recording, measured (0 when it was not)."""
        found = self.analysis.signals(asset_id)
        subject = getattr(found, "subject", None)
        if subject is None or not len(subject):
            return 0.0
        fps = found.fps
        return float(subject[int(a * fps):max(int(a * fps) + 1, int(b * fps))].mean())

    def story(self, vi, asset_id: str) -> dict | None:
        """How a recording tells its story, beat by beat (design 2026-10-15, section 9 G)."""
        from nexora.modules.intelligence import story
        return story.story(vi, asset_id, motion=lambda a, b: self._motion(asset_id, a, b))

    def recut(self, vi, asset_ids: list[str], *, seconds: float, names: dict[str, str]) -> dict:
        """A proposal for cutting recordings again to a length, as a plan and an edit decision list."""
        from nexora.modules.intelligence import story
        return story.recut(vi, asset_ids, seconds=seconds, names=names, motion=self._motion)

    def forget(self, asset_id: str) -> int:
        return self.store.forget(asset_id)

    # ------------------------------------------------------------------------------------------------------- running work
    @property
    def segment_seconds(self) -> float | None:
        return self._understanding._seconds if self._understanding else None

    @property
    def understands(self) -> bool:
        return self._understanding is not None

    def understand(self, asset_id: str, *, force: bool = False) -> str | None:
        """Describe a recording. Duplicates are skipped; `force` starts a new run."""
        from nexora.modules.intelligence.understand import UNDERSTAND
        if self._understanding is None or "duplicate_of" in self._assets.original(asset_id).metadata:
            return None
        if force:
            self._orch.supersede(UNDERSTAND.pipeline_id, asset_id)       # an earlier run still waiting would only do the same work again
        return self._orch.submit_run(UNDERSTAND, subject_ref=asset_id, idempotency_key=None if force else f"understand:{asset_id}")

    def retell(self, asset_id: str) -> int:
        """Put the beats of a recording into words again from what the model already said, without asking it to look again."""
        return self._understanding.retell(asset_id) if self._understanding is not None else 0

    def profile(self, asset_id: str) -> str | None:
        """Measure and recognise what is in a recording, beat by beat, then describe it. Without a profiler, describe at once."""
        from nexora.modules.intelligence.profiler import PROFILE
        if self.profiler is None:
            return self.understand(asset_id, force=True)
        if "duplicate_of" in self._assets.original(asset_id).metadata:
            return None
        self._orch.supersede(PROFILE.pipeline_id, asset_id)          # an earlier run still waiting would only do the same work again
        return self._orch.submit_run(PROFILE, subject_ref=asset_id)

    def transcribe(self, asset_id: str, *, force: bool = False) -> str | None:
        """Listen to a recording for speech. Footage without sound is left alone."""
        from nexora.modules.intelligence.transcribe import TRANSCRIBE
        if self._transcription is None or not self._transcription.wanted(asset_id):
            if not self._assets.original(asset_id).metadata.get("probe", {}).get("has_audio"):
                # Footage without sound has been listened to as far as it can be: there is nothing to hear, nothing owed (0189).
                from nexora.modules.intelligence.analyzers import BY_NAME
                self.store.ran(asset_id, BY_NAME["speech"])
            return None
        return self._orch.submit_run(TRANSCRIBE, subject_ref=asset_id, idempotency_key=None if force else f"transcribe:{asset_id}")

    def redivide(self, asset_id: str) -> dict | None:
        """Work out the shots and beats again from what was measured: after the words became known, after the operator placed a
        mark, after a rule changed. When the beats come out different, the recording is profiled and described again; a beat
        the new division leaves alone keeps its description, so nothing is asked of a model twice."""
        before = beat_seconds(self.analysis.structure(asset_id) or {})
        made = self.analysis.restructure(asset_id)
        if made is not None and beat_seconds(made) != before:
            self.profile(asset_id)
        return made

    def mark_boundary(self, asset_id: str, *, kind: str, op: str, t: float) -> dict | None:
        """The operator places, removes or lets go of a boundary; it is kept through every later division."""
        before = beat_seconds(self.analysis.structure(asset_id) or {})
        made = self.analysis.pin(asset_id, kind=kind, op=op, t=t)
        if made is not None and beat_seconds(made) != before:
            self.profile(asset_id)
        return made

    def analyse(self, asset_id: str, *, once: bool = False) -> str:
        """Measure a recording and divide it, then profile and describe it. `once`: not again if it has been started before."""
        return self._orch.submit_run(STRUCTURE, subject_ref=asset_id, idempotency_key=f"structure:{asset_id}" if once else None)

    def find_unmeasured(self) -> list[str]:
        """Start analysing every video taken in before footage was divided into shots and beats. Runs with the background work."""
        runs = []
        for asset in self._assets.assets():
            if asset["kind"] != "video":
                continue
            original = self._assets.original(asset["asset_id"])
            meta = original.metadata
            if "duplicate_of" in meta or "structure" in meta or not meta.get("probe", {}).get("duration") or not original.checksum:
                continue
            runs.append(self.analyse(asset["asset_id"], once=True))
        return runs

    def deepen(self, moment_id: str) -> list[str]:
        return self._understanding.deepen(moment_id)

    def sync(self, first: str, second: str, *, media_dir) -> dict:
        """Line up two recordings of the same event by their sound and remember it on both, so that a cut can switch camera at the same instant."""
        from nexora.core.adapter import Request
        from nexora.modules.intelligence.sync import MIN_SYNC_CONFIDENCE, best_offset
        envelopes = []
        for asset_id in (first, second):
            original = self._assets.original(asset_id)
            if not original.metadata.get("probe", {}).get("has_audio"):
                raise ValueError("no_audio")
            versions = {v.role: v for v in self._assets.versions(asset_id)}
            path = self._assets.path_of(original)
            path = path if path.is_file() else self._assets.path_of(versions["proxy"])
            envelopes.append(self.analysis._adapters.submit("ffmpeg", Request("envelope", inputs={"path": str(path)}, params={"out": str(media_dir / f"{asset_id}.raw")})).outputs)
        offset, sure = best_offset(envelopes[0]["envelope"], envelopes[1]["envelope"], envelopes[0]["rate"])
        if sure < MIN_SYNC_CONFIDENCE:
            raise ValueError("not_alike")
        for asset_id, other, shift in ((first, second, offset), (second, first, -offset)):
            original = self._assets.original(asset_id)
            self._assets.update_metadata(original.version_id, angles={**original.metadata.get("angles", {}), other: shift})
        return {"offset": offset, "confidence": sure}
