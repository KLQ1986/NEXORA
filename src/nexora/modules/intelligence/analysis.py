"""Measuring a recording and working out its shots and beats, as stages of a run (footage understanding, round 1).

`signals` decodes the footage once and keeps the measures beside it; `structure` turns them into shots and beats. Neither
needs a model, so footage has its structure as soon as it has been taken in. The structure is worked out again, from the
measures already kept, whenever something it depends on changes: the words spoken in it become known, the operator places
or removes a boundary, or a rule is changed.
"""
import json
from pathlib import Path
from typing import Callable

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, Request
from nexora.core.assets import AssetStore
from nexora.core.pipeline import PipelineDefinition, StageDef
from nexora.core.timebase import to_seconds
from nexora.modules.intelligence import signals as measures
from nexora.modules.intelligence.structure import Rules, build, coverage_faults

STRUCTURE = PipelineDefinition("library.structure", "1", [
    StageDef("signals", timeout_seconds=6 * 3600, lane="background", requires=("ffmpeg",)),
    StageDef("structure", depends_on=("signals",), lane="background"),
])
MAX_ANALYSIS_RATE = 30.0         # frames a second looked at; footage shot faster is thinned to this
PIN_REACH = 0.3                  # seconds within which a mark of the operator's is the same mark


class Analysis:
    def __init__(self, assets: AssetStore, adapters: AdapterRegistry, media_dir: str | Path, *, rules: Rules = Rules(),
                 words: Callable[[str], list[tuple[float, float]]] | None = None):
        self._assets, self._adapters, self._media = assets, adapters, Path(media_dir)
        self.rules = rules
        self._words = words or (lambda asset_id: [])          # the words spoken in an asset, as (start, end) in seconds
        self.store = None                                       # the canonical model, once the domain has handed it over

    def handlers(self) -> dict:
        return {"signals": self._signals_stage, "structure": self._structure_stage}

    # ------------------------------------------------------------------ where things are kept
    def _path(self, original, suffix: str) -> Path:
        return self._media / original.checksum[:2] / f"{original.checksum}{suffix}"

    def signals(self, asset_id: str) -> measures.Signals | None:
        original = self._assets.original(asset_id)
        return measures.Signals.load(self._path(original, "_signals.npz")) if original.checksum else None

    def structure(self, asset_id: str) -> dict | None:
        """The shots and beats of an asset as last worked out, or None when it has not been analysed."""
        original = self._assets.original(asset_id)
        if not original.checksum or "structure" not in original.metadata:
            return None
        path = self._path(original, "_structure.json")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def pinned(self, asset_id: str) -> list[dict]:
        return list(self._assets.original(asset_id).metadata.get("pinned_boundaries", []))

    # ------------------------------------------------------------------ stages
    def _signals_stage(self, ctx):
        original = self._assets.original(ctx.subject_ref)
        meta = original.metadata
        probe = meta.get("probe", {})
        if "duplicate_of" in meta or probe.get("still") or not probe.get("duration"):
            return {"skipped": "nothing to measure"}
        target = self._path(original, "_signals.npz")
        if measures.Signals.load(target) is not None:
            return {"cached": True}
        versions = {v.role: v for v in self._assets.versions(ctx.subject_ref)}
        source = next((p for p in (self._assets.path_of(versions[r]) for r in ("proxy", "original") if r in versions) if p.is_file()), None)
        if source is None:
            raise AdapterError(ErrorCode.MISSING_INPUT, "neither the footage nor its proxy is available")
        on_proxy = "proxy" in versions and source == self._assets.path_of(versions["proxy"])
        rate = min(float(probe.get("frame_rate") or 25.0) or 25.0, MAX_ANALYSIS_RATE)
        raw = self._path(original, "_analysis.raw")
        try:
            out = self._adapters.submit("ffmpeg", Request("analysis", inputs={"path": str(source)}, attempt_id=ctx.claim.attempt_id, params={
                "out": str(raw), "fps": rate, "width": measures.WIDTH, "height": measures.HEIGHT,
                "color_transfer": None if on_proxy else probe.get("color_transfer")})).outputs          # the proxy is already in SDR
            found = measures.analyse(measures.read_frames(raw), out["fps"])
            if out["blur"]:
                import numpy as np
                found.blur, found.blur_rate = np.array(out["blur"], np.float32), float(out["blur_rate"])
            found.save(target)
        finally:
            raw.unlink(missing_ok=True)
        return {"frames": found.frames, "fps": found.fps}

    def _structure_stage(self, ctx):
        made = self.restructure(ctx.subject_ref)
        return {"skipped": "nothing was measured"} if made is None else {"shots": len(made["shots"]), "beats": len(made["beats"])}

    # ------------------------------------------------------------------ working the structure out
    def _build(self, asset_id: str, *, pinned: list[dict]) -> dict | None:
        original = self._assets.original(asset_id)
        meta = original.metadata
        found = None if "duplicate_of" in meta else self.signals(asset_id)       # a second copy of a file is not looked at twice
        if found is None:
            return None
        usable = meta.get("usable_ranges") or [[0.0, found.duration]]
        usable = [[a, min(b, found.duration)] for a, b in usable if a < found.duration]       # the measures end where the last frame does
        return build(found, usable=usable, words=self._words(asset_id), pinned=pinned, source_rate=meta.get("probe", {}).get("frame_rate"), rules=self.rules)

    def restructure(self, asset_id: str) -> dict | None:
        """Work the shots and beats out again from the measures kept. Returns the structure, or None when there are no measures."""
        made = self._build(asset_id, pinned=self.pinned(asset_id))
        if made is None:
            return None
        original = self._assets.original(asset_id)
        path = self._path(original, "_structure.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        partial.write_text(json.dumps(made, ensure_ascii=False), encoding="utf-8")
        partial.replace(path)
        cuts = sorted(to_seconds(s["start"], 2) for s in made["shots"] if s["transition_in"] in ("cut", "dissolve", "marked"))
        self._assets.update_metadata(original.version_id, scene_cuts=cuts,
                                     structure={"version": made["version"], "shots": len(made["shots"]), "beats": len(made["beats"]), "bars": made["bars"]["value"]})
        if self.store is not None and self._assets.asset(asset_id) is not None:
            from nexora.modules.intelligence import publish
            from nexora.modules.intelligence.analyzers import BY_NAME
            publish.structure(self.store, asset_id, made, BY_NAME["structure"])
        return made

    def as_measured(self, asset_id: str) -> dict | None:
        """The structure the rules give on their own, without the operator's marks: what a benchmark holds against those marks."""
        return self._build(asset_id, pinned=[])

    def faults(self, asset_id: str) -> list[str]:
        made = self.structure(asset_id)
        if made is None:
            return []
        original = self._assets.original(asset_id)
        found = self.signals(asset_id)
        usable = original.metadata.get("usable_ranges") or []
        if found is not None:
            usable = [[a, min(b, found.duration)] for a, b in usable if a < found.duration]
        return coverage_faults(made, usable)

    # ------------------------------------------------------------------ the operator's marks
    def pin(self, asset_id: str, *, kind: str, op: str, t: float) -> dict | None:
        """Place a boundary (`op` "add") or take one away ("remove") at `t` seconds. The mark is kept: every later division of
        this footage has a boundary there, or has none. "clear" forgets a mark and leaves the place to the rules again."""
        if kind not in ("shot", "beat") or op not in ("add", "remove", "clear"):
            raise ValueError("unknown kind of mark")
        original = self._assets.original(asset_id)
        marks = [m for m in self.pinned(asset_id) if abs(float(m["t"]) - t) > PIN_REACH]
        if op != "clear":
            marks.append({"kind": kind, "op": op, "t": round(float(t), 3)})
        self._assets.update_metadata(original.version_id, pinned_boundaries=sorted(marks, key=lambda m: m["t"]))
        return self.restructure(asset_id)
