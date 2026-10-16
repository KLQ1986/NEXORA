"""The Visual Quality domain at work (design 2026-10-16): profile a source, assess it shot by shot, propose a recipe,
preview it with temporal QA, and apply it, for an asset of the library or for any file.

Pipelines, run by the orchestrator like all long work: `vq.analyse` (profile → assess → plan), `vq.preview`, `vq.apply`.
What a run is asked for (plan options, the time of a preview, where to write a result) is a request kept with the subject,
since a run carries only its subject.

Video Intelligence is optional: when the subject is an asset it has analysed, its shot boundaries are used; otherwise the
engine finds them itself.
"""
import json
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, Request
from nexora.core.assets import AssetStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.visual_quality import VisualQuality, filters_of
from nexora.core.visual_quality_store import VisualQualityStore
from nexora.modules.visual_quality import assess as A
from nexora.modules.visual_quality import measure as M
from nexora.modules.visual_quality import plan as P
from nexora.modules.visual_quality import qa as Q
from nexora.modules.visual_quality.profiler import DECODE_EXT, STILL_EXT, VERSION as PROFILE_VERSION, SourceProfiler
from nexora.modules.visual_quality.registry import BY_KEY

ANALYSE = PipelineDefinition("vq.analyse", "1", [
    StageDef("profile", timeout_seconds=3 * 3600, lane="background", requires=("ffmpeg", "ffprobe")),
    StageDef("assess", depends_on=("profile",), timeout_seconds=6 * 3600, lane="background", requires=("ffmpeg",)),
    StageDef("plan", depends_on=("assess",)),
])
PREVIEW = PipelineDefinition("vq.preview", "1", [StageDef("preview", timeout_seconds=3600, requires=("ffmpeg",))])
APPLY = PipelineDefinition("vq.apply", "1", [StageDef("apply", timeout_seconds=12 * 3600, lane="background", requires=("ffmpeg",))])
MAX_SHOTS = 48
VERIFY_SHOTS = 12          # shots whose risky steps are checked on their own frame (the longest first would be better; in order is simpler)
AI_ABSORBS = {"restore": frozenset({"deblock", "deband", "denoise"})}
AI_MARGIN = 0.5            # how much more natural (NIQE) an AI step must make a picture than the classic step to be kept
NIQE_SLACK = 0.3           # how much less natural a step may make a frame before it is dropped
STILL_WINDOW = 1.0                                       # seconds prepared around one frame of a video
# Steps that take more than one frame to make one: run on a stretch that crosses a cut, they blend the two shots.
ACROSS_FRAMES = frozenset({"interpolate", "stabilise", "deflicker", "denoise"})
ANALYZER = f"vq@{PROFILE_VERSION}.{A.VERSION}.{P.VERSION}"


class VisualQualityService:
    def __init__(self, orch: Orchestrator, assets: AssetStore, adapters: AdapterRegistry, store: VisualQualityStore, reader: VisualQuality,
                 work_dir: str | Path, lut_dir: str | Path, *, shots_of=None):
        self._orch, self._assets, self._adapters = orch, assets, adapters
        self.store, self.reader = store, reader
        self._work, self._luts = Path(work_dir), Path(lut_dir)
        self._shots_of = shots_of                     # Video Intelligence's shots of an asset, when it has them
        self.profiler = SourceProfiler(adapters, self._work / "tmp")

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(ANALYSE, {"profile": self._profile_stage, "assess": self._assess_stage, "plan": self._plan_stage})
        registry.register(PREVIEW, {"preview": self._preview_stage})
        registry.register(APPLY, {"apply": self._apply_stage})

    # --------------------------------------------------------------------------------------------------------- subjects
    def subject_for_asset(self, asset_id: str) -> str:
        original = self._assets.original(asset_id)
        self.store.subject(asset_id, kind="asset", path=self._assets.path_of(original), checksum=original.checksum)
        return asset_id

    def subject_for_file(self, path: str | Path) -> str:
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        return self.store.new_job(path)

    def path_of(self, subject: str) -> Path:
        """The file the tools read: the subject's own, or, for a HEIC or a RAW, its 16-bit TIFF made once by the `stills` adapter."""
        known = self.reader.subject(subject)
        if known is None:
            raise LookupError(subject)
        path = Path(known["path"])
        if path.suffix.lower() not in DECODE_EXT or not path.is_file():
            return path
        return self._decoded(subject, path)[0]

    def _decoded(self, subject: str, original: Path) -> tuple[Path, dict]:
        out = self._work / subject / "source.tiff"
        info_file = out.with_suffix(".json")
        if not (out.is_file() and info_file.is_file() and out.stat().st_mtime >= original.stat().st_mtime):
            done = self._adapters.submit("stills", Request("decode", inputs={"path": str(original)}, params={"out": str(out)}))
            info_file.write_text(json.dumps(done.outputs))
        return out, json.loads(info_file.read_text())

    # ------------------------------------------------------------------------------------------------------- what is asked
    def analyse(self, subject: str, **options) -> str:
        """Profile, assess and plan a subject. `options`: target_height, target_fps, denoise, sharpen, stabilise, exposure."""
        self.store.request(subject, "plan", options)
        self._orch.supersede(ANALYSE.pipeline_id, subject)
        return self._orch.submit_run(ANALYSE, subject_ref=subject)

    def preview(self, subject: str, *, t: float | None = None, seconds: float = 3.0, recipe_id: str | None = None) -> str:
        self.store.request(subject, "preview", {"t": t, "seconds": seconds, "recipe_id": recipe_id})
        return self._orch.submit_run(PREVIEW, subject_ref=subject)

    def apply(self, subject: str, *, out: str | Path | None = None, master: bool = False) -> str:
        """Render the approved recipe: the prepared files a cut needs, and, with `out`, the whole result into that file."""
        self.store.request(subject, "apply", {"out": str(out) if out else None, "master": master})
        return self._orch.submit_run(APPLY, subject_ref=subject)

    def approve(self, recipe_id: str, *, by: str = "operator") -> None:
        self.store.decide(recipe_id, "approved", decided_by=by)

    def reject(self, recipe_id: str, *, by: str = "operator") -> None:
        self.store.decide(recipe_id, "rejected", decided_by=by)

    def edit_step(self, recipe_id: str, shot: int, step: int, *, params: dict | None = None, off: bool | None = None) -> str:
        """The operator changes a step: a new version of the recipe, proposed, with the change recorded."""
        recipe = self.reader.by_id(recipe_id)
        if recipe is None:
            raise LookupError(recipe_id)
        data = __import__("copy").deepcopy(recipe.data)
        target = data["shots"][shot]["steps"][step]
        if params:
            target["params"] = {**target.get("params", {}), **params}
            if target["op"] == "levels":                       # the baked LUT follows the new numbers
                target["params"]["lut"] = P.levels_lut(target["params"], self._work / "luts")
        if off is not None:
            target["off"] = bool(off)
        target["edited"] = True
        data["from"] = recipe_id
        return self.store.recipe(recipe.subject, data, status="proposed", decided_by="operator")

    def add_removal(self, recipe_id: str, shot: int, regions: list[list[float]]) -> str:
        """The operator marks what to take out of a shot (rectangles in the source's pixels, held for the whole shot): a new
        proposed version of the recipe with a `remove` step, filled by ProPainter from what the other frames show there."""
        recipe = self.reader.by_id(recipe_id)
        if recipe is None:
            raise LookupError(recipe_id)
        if "propainter" not in self._have():
            raise AdapterError(ErrorCode.UNAVAILABLE, "object removal is not set up (sh scripts/setup-propainter.sh)", retryable=False)
        technical = (self.reader.profile(recipe.subject) or {}).get("technical", {})
        if technical.get("kind") == "still":
            raise AdapterError(ErrorCode.INVALID_REQUEST, "object removal works on video, from the frames around", retryable=False)
        W, H = int(technical.get("width") or 0), int(technical.get("height") or 0)
        boxes = []
        for r in regions:
            x, y, w, h = (float(v) for v in r)
            if w < 4 or h < 4 or x < 0 or y < 0 or (W and x + w > W) or (H and y + h > H):
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"region {r} is not inside the {W}×{H} picture", retryable=False)
            boxes.append([round(x, 1), round(y, 1), round(w, 1), round(h, 1)])
        data = __import__("copy").deepcopy(recipe.data)
        steps = [s for s in data["shots"][shot]["steps"] if s["op"] != "remove"]
        steps.append({"op": "remove", "tier": "propainter", "params": {"regions": boxes}, "generative": True, "edited": True,
                      "why": f"xoá {len(boxes)} vùng người dùng chọn (ProPainter, AI lấp từ các khung lân cận)"})
        data["shots"][shot]["steps"] = sorted(steps, key=lambda s: P.ORDER.index(s["op"]) if s["op"] in P.ORDER else 99)
        data["from"] = recipe_id
        return self.store.recipe(recipe.subject, data, status="proposed", decided_by="operator")

    # ------------------------------------------------------------------------------------------------------------ helpers
    def _have(self) -> set[str]:
        have: set[str] = set()
        try:
            env = self._adapters.environment().get("ffmpeg") or {}
            have |= {f"ffmpeg:{k}" for k, v in (env.get("filters") or {}).items() if v}
        except Exception:
            have |= {"ffmpeg:fps", "ffmpeg:colorlevels", "ffmpeg:eq", "ffmpeg:lut3d"}
        names = {c.name for c in self._adapters.describe()}
        if "apple_frames" in names:
            try:
                env = self._adapters.environment().get("apple_frames") or {}
            except Exception:
                env = {}
            if env.get("available") and env.get("denoise"):
                have.add("apple_vt")
            if env.get("available") and env.get("interpolate"):
                have.add("apple_frc")
            if env.get("available") and env.get("superres"):
                have.add("apple_sr")
        if "restore_local" in names:
            try:
                if "realesrgan-x4plus" in ((self._adapters.environment().get("restore_local") or {}).get("esrgan") or []):
                    have.add("realesrgan")
            except Exception:
                pass
        if "restore_faces" in names:
            try:
                env = self._adapters.environment().get("restore_faces") or {}
            except Exception:
                env = {}
            if env.get("available") and env.get("find"):
                have.add("faces_find")
            if env.get("available") and env.get("restore"):
                have.add("faces")
        if "inpaint" in names:
            try:
                if (self._adapters.environment().get("inpaint") or {}).get("remove"):
                    have.add("propainter")
            except Exception:
                pass
        if "gyroflow" in names:
            try:
                if (self._adapters.environment().get("gyroflow") or {}).get("available"):
                    have.add("gyroflow")
            except Exception:
                pass
        if "ffmpeg:vidstabdetect" in have:
            have.add("vidstab")
        return have

    def _request(self, subject: str, kind: str) -> dict:
        pending = self.reader.requests(subject, kind=kind, status="pending")
        return pending[-1] if pending else {"request_id": None, "params": {}}

    def colour_steps(self, profile: dict) -> tuple[list[dict], list[str]]:
        """The steps that bring a source's encoding to Rec.709, and notes (a LUT fetched, an encoding not known)."""
        key = profile.get("encoding")
        notes: list[str] = []
        if not key:
            return [], ["không nhận ra profile màu: không chuyển màu"]
        enc = BY_KEY[key]
        if enc.transform == "none":
            return [], []
        if enc.transform == "tonemap":
            return [{"op": "tonemap", "tier": "ffmpeg", "params": {"curve": enc.source, "peak": 100}, "why": f"{enc.name} → SDR Rec.709"}], []
        if enc.transform == "lut":
            lut = self._luts / enc.source
            if not lut.is_file() and enc.fetch:
                try:
                    lut = Path(self._adapters.submit("color", Request("fetch", params={"url": enc.fetch, "name": enc.source})).outputs["lut"])
                    notes.append(f"đã tải LUT chính hãng: {enc.source}")
                except AdapterError as err:
                    return [], [f"thiếu LUT {enc.source} và không tải được ({err})"]
            if not lut.is_file():
                return [], [f"thiếu LUT {enc.source}"]
            return [{"op": "color_transform", "tier": "ffmpeg", "params": {"lut": str(lut), "encoding": key}, "why": f"{enc.name} → Rec.709 (LUT của hãng)"}], notes
        if enc.transform == "ocio":
            try:
                lut = self._adapters.submit("color", Request("bake", params={"source": enc.source})).outputs["lut"]
            except AdapterError as err:
                return [], [f"không tạo được chuyển đổi OpenColorIO cho {enc.name} ({err})"]
            return [{"op": "color_transform", "tier": "ffmpeg", "params": {"lut": lut, "encoding": key}, "why": f"{enc.name} → Rec.709 (OpenColorIO, ACES 2)"}], []
        return [], []

    def _shots(self, subject: str, path: Path, technical: dict) -> list[tuple[float, float]]:
        duration = float(technical.get("duration") or 0.0)
        if technical.get("kind") == "still" or duration <= 0:
            return [(0.0, 0.0)]
        known = None
        if self._shots_of and (self.reader.subject(subject) or {}).get("kind") == "asset":
            try:
                known = self._shots_of(subject)
            except Exception:
                known = None
        if not known:
            try:
                cuts = self._adapters.submit("ffmpeg", Request("scenecuts", inputs={"path": str(path)}, params={"color_transfer": technical.get("color_transfer")})).outputs["cuts"]
            except AdapterError:
                cuts = []
            edges = [0.0] + [c for c in cuts if 0.5 < c < duration - 0.5] + [duration]
            known = list(zip(edges, edges[1:]))
        known = [(round(a, 3), round(b, 3)) for a, b in known if b - a > 0.05]
        while len(known) > MAX_SHOTS:                    # too many to measure one by one: the shortest joins its neighbour
            i = min(range(len(known) - 1), key=lambda k: known[k][1] - known[k][0] + known[k + 1][1] - known[k + 1][0])
            known[i:i + 2] = [(known[i][0], known[i + 1][1])]
        return known

    # ------------------------------------------------------------------------------------------------------------- stages
    def _profile_stage(self, ctx):
        path = self.path_of(ctx.subject_ref)
        if not path.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{path} is not at hand")
        made = self.profiler.profile(path, subject=ctx.subject_ref)
        original = Path(self.reader.subject(ctx.subject_ref)["path"])
        if original.suffix.lower() in DECODE_EXT:
            # What the original is, not what its working copy is: the format, the bits of the sensor, the camera.
            info = self._decoded(ctx.subject_ref, original)[1]
            tech = made["technical"]
            tech.update({"container": info.get("from"), "decoded": True, "raw": bool(info.get("raw")), "bit_depth": info.get("bit_depth") or tech.get("bit_depth")})
            for key in ("make", "model", "software"):
                tech[key] = tech.get(key) or info.get(key)
            make, model = str(tech.get("make") or ""), str(tech.get("model") or "")
            tech["device"] = tech.get("device") or (model if model.lower().startswith(make.lower()) else f"{make} {model}").strip() or None
        if made["technical"].get("kind") != "still" and "gyroflow" in self._have():
            try:
                made["technical"]["gyro"] = bool(self._adapters.submit("gyroflow", Request("probe", inputs={"path": str(path)})).outputs.get("gyro"))
            except AdapterError:
                made["technical"]["gyro"] = False
        self.store.profile(ctx.subject_ref, made, analyzer=ANALYZER)
        return {"encoding": made["encoding"], "content": made["content"], "warnings": len(made["warnings"])}

    def _assess_stage(self, ctx):
        profile = self.reader.profile(ctx.subject_ref)
        path = self.path_of(ctx.subject_ref)
        colour, notes = self.colour_steps(profile)
        chain = filters_of(colour) or []
        technical = profile["technical"]
        still = technical.get("kind") == "still"
        rate = float(technical.get("frame_rate") or 25.0)
        shots, defects = [], []
        faces = self._faces(path) if still and "faces_find" in self._have() else []
        for k, (t0, t1) in enumerate(self._shots(ctx.subject_ref, path, technical)):
            mid = (t0 + t1) / 2
            if still:
                from nexora.modules.visual_quality.profiler import _rgb
                frame = _rgb(path) if not chain else self.profiler._still(path, t=0.0, subject=ctx.subject_ref, filters=chain)
            else:
                frame = self.profiler._still(path, t=mid, subject=ctx.subject_ref, filters=chain, width=_measure_width(technical))
            if frame is None:
                continue
            depth = int(technical.get("bit_depth") or 8)
            lk = M.look(frame, depth=depth)
            flick = shake = 0.0
            if not still and t1 - t0 > 0.6:
                burst = self.profiler.sample(path, duration=t1 - t0, subject=ctx.subject_ref, filters=chain, width=480, t_in=max(t0, mid - 0.8),
                                             seconds=min(1.6, t1 - t0), fps=min(rate, 15.0), tag=f"burst{k}")
                flick = M.flicker([float(M.luma(f).mean()) for f in burst])
                shake = M.shake(burst)
            score = A.ShotScore(t0, t1, lk, flick, shake, A.niqe_of(frame))
            shot_defects = A.defects_of(score, content=profile["content"], frame=frame)
            defects += shot_defects
            shots.append({"t_start": t0, "t_end": t1, "scores": score.scores(), "display": M.as_dict(lk), "defects": shot_defects,
                          **({"faces": faces, "size": [frame.shape[1], frame.shape[0]]} if faces else {})})
            ctx.heartbeat()
        self.store.defects(ctx.subject_ref, defects, analyzer=ANALYZER)
        work = self._work / ctx.subject_ref
        work.mkdir(parents=True, exist_ok=True)
        (work / "assessment.json").write_text(__import__("json").dumps({"shots": shots, "colour": colour, "notes": notes}, ensure_ascii=False))
        return {"shots": len(shots), "defects": len(defects)}

    def _plan_stage(self, ctx):
        import json
        profile = self.reader.profile(ctx.subject_ref)
        made = json.loads((self._work / ctx.subject_ref / "assessment.json").read_text())
        request = self._request(ctx.subject_ref, "plan")
        options = {**request["params"], "lut_dir": str(self._work / "luts")}
        have = self._have()
        shots = []
        path = self.path_of(ctx.subject_ref)
        still = profile["technical"].get("kind") == "still"
        verified = 0
        for shot in made["shots"]:
            steps = P.plan_shot(shot, profile=profile, colour=made["colour"], have=have, options=options)
            if verified < VERIFY_SHOTS and any(s["op"] in P.RISKY and s.get("tier", "ffmpeg") == "ffmpeg" for s in steps):
                steps = self._verify(path, shot, steps, subject=ctx.subject_ref, still=still)
                verified += 1
                ctx.heartbeat()
            if any("classic" in s for s in steps):
                steps = self._choose_ai(path, shot, steps, subject=ctx.subject_ref)
                ctx.heartbeat()
            shots.append({"t_start": shot["t_start"], "t_end": shot["t_end"], "steps": steps, "scores": shot["scores"], "dropped": shot.get("dropped", []),
                          "defects": [{"kind": d["kind"], "severity": d["severity"]} for d in shot["defects"]]})
        data = {"version": P.VERSION, "encoding": profile.get("encoding"), "encoding_name": profile.get("encoding_name"),
                "content": profile["content"], "shots": shots, "output": {"colour": P.output_colour(profile, made["colour"])},
                "notes": made["notes"] + profile.get("warnings", []), "options": {k: v for k, v in options.items() if k != "lut_dir"}, "made_by": ANALYZER}
        recipe_id = self.store.recipe(ctx.subject_ref, data)
        if options.get("approve"):
            self.approve(recipe_id, by="policy")
        if request["request_id"]:
            self.store.finish_request(request["request_id"], "done", {"recipe_id": recipe_id})
        return {"recipe_id": recipe_id, "steps": sum(len(s["steps"]) for s in shots)}

    def _verify(self, path: Path, shot: dict, steps: list[dict], *, subject: str, still: bool) -> list[dict]:
        """Each risky step of a shot shows on the shot's middle frame that it does not make the picture less natural: NIQE with
        the step against without it (all the other steps kept). One that costs more than `NIQE_SLACK` is dropped, and said."""
        t = 0.0 if still else (shot["t_start"] + shot["t_end"]) / 2
        technical = (self.reader.profile(subject) or {}).get("technical", {})
        cache: dict[str, float | None] = {}

        def niqe(chain: list[str]) -> float | None:
            key = "|".join(chain)
            if key not in cache:
                frame = self.profiler._still(path, t=t, subject=subject, filters=chain, width=1280)
                cache[key] = A.niqe_of(frame) if frame is not None else None
            return cache[key]

        kept = list(steps)
        # A denoise first gets its strength from its method noise, on the frame at the size its noise was measured at.
        for step in [s for s in steps if s["op"] == "denoise" and s.get("tier", "ffmpeg") == "ffmpeg"]:
            sigma = float(step["params"].get("sigma") or 0.0)
            chain = filters_of(kept)
            if chain is None or sigma <= 0:
                continue

            def frame(strength, step=step):
                trial = [s for s in kept if s is not step] if strength is None else \
                        [{**s, "params": {**s["params"], "strength": strength}} if s is step else s for s in kept]
                got = self.profiler._still(path, t=t, subject=subject, filters=filters_of(trial), width=None if still else _measure_width(technical))
                if got is None:
                    raise AdapterError(ErrorCode.OUTPUT_INVALID, "no frame to tune the denoise on", retryable=False)
                return got

            try:
                strength, ratio = P.tune_denoise(frame, sigma)
            except AdapterError:
                continue
            step["params"]["strength"] = strength
            step["method_noise"] = ratio
        for step in [s for s in steps if s["op"] in P.RISKY and s.get("tier", "ffmpeg") == "ffmpeg"]:
            with_it = filters_of(kept)
            without = filters_of([s for s in kept if s is not step])
            if with_it is None or without is None:
                continue
            a, b = niqe(with_it), niqe(without)
            if a is not None and b is not None and a > b + NIQE_SLACK:
                kept = [s for s in kept if s is not step]
                shot.setdefault("dropped", []).append({"op": step["op"], "why": f"làm kém tự nhiên hơn trên khung của shot (NIQE {b:.2f} → {a:.2f})"})
            elif a is not None and b is not None:
                step["checked"] = {"niqe_without": round(b, 3), "niqe_with": round(a, 3)}
        return kept

    def _faces(self, path: Path) -> list[dict]:
        try:
            found = self._adapters.submit("restore_faces", Request("find", inputs={"path": str(path)})).outputs.get("faces", [])
        except AdapterError:
            return []
        return [{"box": [round(v, 1) for v in f["box"]], "quality": round(float(f.get("quality") or 0.0), 3)} for f in found]

    def _choose_ai(self, path: Path, shot: dict, steps: list[dict], *, subject: str) -> list[dict]:
        """Each step by AI that makes detail up against the classic step it stands for, on the picture itself at full size: the
        AI is kept only when it is clearly more natural (NIQE lower by `AI_MARGIN`), else the classic step takes its place."""
        work = self._work / subject / "verify"
        work.mkdir(parents=True, exist_ok=True)
        kept = list(steps)
        for step in [s for s in steps if "classic" in s]:
            classic = step["classic"]
            other = [classic if s is step else s for s in kept if s is not step or classic]
            # A restore by AI takes away noise, banding and blocks at once: with it, the classic steps for those are left out.
            absorbed = AI_ABSORBS.get(step["op"], frozenset())
            mine = [{k: v for k, v in s.items() if k != "classic"} for s in kept if s is step or s["op"] not in absorbed]
            scores = {}
            for name, chain in (("ai", mine), ("classic", [{k: v for k, v in s.items() if k != "classic"} for s in other])):
                try:
                    file = self._render(path, chain, out=work / f"{step['op']}_{name}.png", kind="still")
                    picture = _load_rgb(file)
                    regions = _regions(picture, shot) if step["op"] == "faces" else [_centre(picture)]
                    values = [v for v in (A.niqe_of(r) for r in regions) if v is not None]
                    scores[name] = float(np.mean(values)) if values else None
                except AdapterError as e:
                    scores[name] = None
                    shot.setdefault("notes", []).append(f"{step['op']} ({name}): {e}")
            ai, base = scores.get("ai"), scores.get("classic")
            if ai is not None and base is not None and ai < base - AI_MARGIN:
                step["checked"] = {"niqe_classic": round(base, 3), "niqe_ai": round(ai, 3)}
                kept = [{k: v for k, v in s.items() if k != "classic"} if s is step else s for s in kept if s is step or s["op"] not in absorbed]
            else:
                kept = other
                shot.setdefault("dropped", []).append({"op": step["op"], "why": ("AI không hơn khi để nguyên" if classic is None else "AI không hơn cách cổ điển") + (f" (NIQE {base:.2f} so với {ai:.2f})" if ai is not None and base is not None else "")})
        return kept

    def _render(self, path: Path, steps: list[dict], *, out: Path, kind: str, t_in: float = 0.0, seconds: float | None = None,
                width: int | None = None, colour: dict | None = None, codec: str | None = None, master: bool = False) -> Path:
        """A stretch through the steps: FFmpeg filters in one go; when a step needs another tool, the steps up to the last such
        one run first, in their order, and the FFmpeg steps after it finish the job."""
        chain = filters_of(steps)
        if chain is None:
            if kind == "still" and path.suffix.lower() in STILL_EXT:
                source, rest = self._prepare_still(path, steps, work=out.parent)
                chain, path, t_in = filters_of(rest) or [], source, 0.0
            elif kind == "still":
                # One frame of a video: the tools that look across frames get a second around it, not the rest of the file.
                start = max(0.0, t_in - STILL_WINDOW / 2)
                source, rest = self._prepare(path, steps, t_in=start, seconds=STILL_WINDOW, work=out.parent)
                chain, path, t_in = filters_of(rest) or [], source, t_in - start
            else:
                source, rest = self._prepare(path, steps, t_in=t_in, seconds=seconds, work=out.parent)
                chain, path, t_in = filters_of(rest) or [], source, 0.0
        params = {"kind": kind, "out": str(out), "t_in": t_in, "filters": chain, "colour": colour or {}, "master": master}
        if seconds and kind != "still":
            params["seconds"] = seconds
        if width:
            params["width"] = width
        if codec:
            params["codec"] = codec
        self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(path)}, params=params))
        return out

    def _process(self, step: dict, source: Path, out: Path, *, t_in: float, seconds: float | None) -> Path:
        """One step that is not an FFmpeg filter, by the tool its tier names; the result is a picture-only intermediate."""
        tier, op, p = step.get("tier"), step["op"], step.get("params") or {}
        span = {"out": str(out), "t_in": t_in, **({"seconds": seconds} if seconds else {})}
        if tier == "apple_vt":
            if op == "denoise":
                self._adapters.submit("apple_frames", Request("denoise", inputs={"path": str(source)}, params={**span, "strength": p.get("strength", 0.5)}))
            elif op == "interpolate":
                self._adapters.submit("apple_frames", Request("interpolate", inputs={"path": str(source)}, params={**span, "fps": p["fps"]}))
            elif op == "upscale":
                self._adapters.submit("apple_frames", Request("superres", inputs={"path": str(source)}, params=span))
            else:
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"Apple's processors do not do {op}", retryable=False)
        elif tier == "propainter":
            self._adapters.submit("inpaint", Request("remove", inputs={"path": str(source)}, params={**span, "regions": p["regions"]}))
        elif tier == "vidstab":
            self._adapters.submit("ffmpeg", Request("vq_stabilise", inputs={"path": str(source)}, params={**span, "smoothing": p.get("smoothing", 15), "zoom": p.get("zoom", 0)}))
        elif tier == "gyroflow":
            self._adapters.submit("gyroflow", Request("stabilise", inputs={"path": str(source)}, params={**span, "smoothness": p.get("smoothness", 0.5)}))
        else:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"no tool for {tier} on this machine", retryable=False)
        return out

    def _prepare_still(self, path: Path, steps: list[dict], *, work: Path) -> tuple[Path, list[dict]]:
        """`_prepare` for a picture: the steps in their order up to the last that needs a processor, FFmpeg steps between them
        written to 16-bit PNG; returns the picture and the FFmpeg steps left."""
        last = max(i for i, s in enumerate(steps) if s.get("tier", "ffmpeg") != "ffmpeg")
        stamp = int(time.time() * 1000)
        current, pending = path, []
        for k, step in enumerate(steps[:last + 1]):
            if step.get("tier", "ffmpeg") == "ffmpeg":
                pending.append(step)
                continue
            if pending:
                baked = work / f"prep_{stamp}_{k}_ffmpeg.png"
                self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(current)}, params={"kind": "still", "out": str(baked), "filters": filters_of(pending) or []}))
                current, pending = baked, []
            current = self._process_still(step, current, work / f"prep_{stamp}_{k}_{step['op']}.png")
        return current, steps[last + 1:]

    def _process_still(self, step: dict, source: Path, out: Path) -> Path:
        tier, op, p = step.get("tier"), step["op"], step.get("params") or {}
        if tier == "codeformer":
            self._adapters.submit("restore_faces", Request("restore", inputs={"path": str(source)}, params={"out": str(out), "weight": p.get("weight", 0.7),
                                                                                                         "blend": p.get("blend", 0.8)}))
            return out
        if tier != "realesrgan":
            raise AdapterError(ErrorCode.UNAVAILABLE, f"no tool for {tier} on a still", retryable=False)
        with Image.open(source) as im:
            w, h = im.size
        if op == "restore":
            size = (w, h)
        elif op == "upscale":
            height = int(p.get("height") or h * 4)
            size = (round(w * height / h / 2) * 2, height)
        else:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"Real-ESRGAN does not do {op}", retryable=False)
        self._adapters.submit("restore_local", Request("esrgan", inputs={"path": str(source)}, params={"out": str(out), "model": p.get("model", P.AI_MODEL), "size": list(size)}))
        return out

    def _prepare(self, path: Path, steps: list[dict], *, t_in: float, seconds: float | None, work: Path) -> tuple[Path, list[dict]]:
        """Run the steps in their order up to the last that needs a processor: FFmpeg steps between processors are rendered in
        between, so that each step sees what the steps before it made. Returns the intermediate (with the source's sound
        put back) and the FFmpeg steps left after the last processor."""
        # Gyroflow reads the gyro by the original's timeline and corrects its lens: it goes first, on the original.
        steps = sorted(steps, key=lambda s: s.get("tier") != "gyroflow")
        last = max(i for i, s in enumerate(steps) if s.get("tier", "ffmpeg") != "ffmpeg")
        stamp = int(time.time() * 1000)
        current, offset, pending = path, t_in, []
        for k, step in enumerate(steps[:last + 1]):
            if step.get("tier", "ffmpeg") == "ffmpeg":
                pending.append(step)
                continue
            if pending:
                baked = work / f"prep_{stamp}_{k}_ffmpeg.mov"
                self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(current)}, params={
                    "kind": "video", "out": str(baked), "t_in": offset, "filters": filters_of(pending) or [], "master": True,
                    **({"seconds": seconds} if seconds else {})}))
                current, offset, pending = baked, 0.0, []
            current = self._process(step, current, work / f"prep_{stamp}_{k}_{step['op']}.mov", t_in=offset, seconds=seconds if offset or current == path else None)
            offset = 0.0
        sounded = work / f"prep_{stamp}_sound.mov"
        self._adapters.submit("ffmpeg", Request("vq_mux", inputs={"path": str(current)}, params={"out": str(sounded), "sound_from": str(path), "t_in": t_in,
                                                                                               **({"seconds": seconds} if seconds else {})}))
        return sounded, steps[last + 1:]

    def _preview_stage(self, ctx):
        request = self._request(ctx.subject_ref, "preview")
        p = request["params"]
        recipe = self.reader.by_id(p["recipe_id"]) if p.get("recipe_id") else self.reader.recipe(ctx.subject_ref)
        if recipe is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "no recipe to preview", retryable=False)
        path = self.path_of(ctx.subject_ref)
        technical = (self.reader.profile(ctx.subject_ref) or {}).get("technical", {})
        still = technical.get("kind") == "still"
        shots = recipe.shots
        t = p.get("t")
        if t is None:
            worst = max(shots, key=lambda s: sum(d["severity"] for d in s.get("defects", [])), default=shots[0])
            t = (worst["t_start"] + worst["t_end"]) / 2
        shot = next((s for s in shots if s["t_start"] <= t <= max(s["t_end"], s["t_start"])), shots[0])
        steps = [s for s in shot["steps"] if not s.get("off")]
        seconds = 0 if still else min(float(p.get("seconds") or 3.0), max(0.5, shot["t_end"] - shot["t_start"]))
        t0 = 0.0 if still else max(shot["t_start"], min(t - seconds / 2, shot["t_end"] - seconds))
        out = self._work / ctx.subject_ref / "previews" / f"{recipe.recipe_id}_{t0:.2f}"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True, exist_ok=True)
        colour = recipe.data.get("output", {}).get("colour", {})
        source_tags = {k: technical.get(k) for k in ("color_primaries", "color_transfer", "color_space") if technical.get(k)}
        files = {"before_still": self._render(path, [], out=out / "before.png", kind="still", t_in=t0 + seconds / 2, width=1280),
                 "after_still": self._render(path, steps, out=out / "after.png", kind="still", t_in=t0 + seconds / 2, width=1280)}
        if not still:
            files["before_video"] = self._render(path, [], out=out / "before.mp4", kind="video", t_in=t0, seconds=seconds, width=1280, codec="h264", colour=source_tags)
            files["after_video"] = self._render(path, steps, out=out / "after.mp4", kind="video", t_in=t0, seconds=seconds, width=1280, codec="h264", colour=colour)
            fps = min(float(technical.get("frame_rate") or 25.0), 12.0)
            before = self.profiler.sample(files["before_video"], duration=seconds, subject=ctx.subject_ref, width=640, fps=fps, tag="qa_before")
            after = self.profiler.sample(files["after_video"], duration=seconds, subject=ctx.subject_ref, width=640, fps=fps, tag="qa_after")
        else:
            from nexora.modules.visual_quality.profiler import _rgb
            before, after = [_rgb(files["before_still"])], [_rgb(files["after_still"])]
        verdict = Q.compare(before, after, colour_changed=any(s["op"] in ("color_transform", "tonemap", "levels") for s in steps), ops=[s["op"] for s in steps])
        data = {"files": {k: str(v) for k, v in files.items()}, "qa": verdict, "steps": [s["op"] for s in steps], "t_shot": [shot["t_start"], shot["t_end"]]}
        preview_id = self.store.preview(recipe.recipe_id, t0, seconds, data)
        self.store.metrics(recipe.recipe_id, [(shot["t_start"], shot["t_end"], name, b, a) for name, (b, a) in verdict["metrics"].items()])
        if request["request_id"]:
            self.store.finish_request(request["request_id"], "done", {"preview_id": preview_id, "verdict": verdict["verdict"]})
        return {"preview_id": preview_id, "verdict": verdict["verdict"]}

    def _apply_stage(self, ctx):
        request = self._request(ctx.subject_ref, "apply")
        p = request["params"]
        recipe = self.reader.recipe(ctx.subject_ref, status="approved")
        if recipe is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "no approved recipe", retryable=False)
        path = self.path_of(ctx.subject_ref)
        technical = (self.reader.profile(ctx.subject_ref) or {}).get("technical", {})
        colour = recipe.data.get("output", {}).get("colour", {})
        work = self._work / ctx.subject_ref / "apply" / recipe.recipe_id
        work.mkdir(parents=True, exist_ok=True)
        prepared = 0
        still = technical.get("kind") == "still"
        # Shots whose steps need another tool are rendered ahead, so that a cut (or, for a still, an extract) takes them from a file.
        for shot in recipe.shots:
            steps = [s for s in shot["steps"] if not s.get("off")]
            if filters_of(steps) is None:
                seconds = shot["t_end"] - shot["t_start"]
                if still:
                    file = self._render(path, steps, out=work / "still.png", kind="still", colour=colour)
                else:
                    file = self._render(path, steps, out=work / f"shot_{shot['t_start']:.2f}.mov", kind="video", t_in=shot["t_start"], seconds=seconds,
                                        colour=colour, master=True)
                self.store.prepared(recipe.recipe_id, shot["t_start"], shot["t_end"], file)
                prepared += 1
                ctx.heartbeat()
        result: dict = {"prepared": prepared}
        if p.get("out"):
            out = Path(p["out"])
            out.parent.mkdir(parents=True, exist_ok=True)
            if still and prepared:
                # Already made above: written in the format asked, without running the AI a second time.
                self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(work / "still.png")}, params={"kind": "still", "out": str(out), "filters": [], "colour": colour}))
            elif still:
                steps = [s for s in recipe.shots[0]["steps"] if not s.get("off")]
                self._render(path, steps, out=out, kind="still", colour=colour)
            elif len(recipe.shots) == 1 or (len({str(s["steps"]) for s in recipe.shots}) == 1 and not self._across_frames(recipe.shots[0]["steps"])):
                steps = [s for s in recipe.shots[0]["steps"] if not s.get("off")]
                self._render(path, steps, out=out, kind="video", colour=colour, master=bool(p.get("master")))
            else:
                # Shot by shot, each with its own steps, in the codec of the result, then joined without re-encoding. Steps that
                # look across frames (interpolation, stabilising, deflicker, temporal denoise) never see across a cut this way.
                master = bool(p.get("master"))
                parts = []
                for k, shot in enumerate(recipe.shots):
                    steps = [s for s in shot["steps"] if not s.get("off")]
                    parts.append(self._render(path, steps, out=work / f"part_{k:04d}{'.mov' if master else '.mp4'}", kind="video", t_in=shot["t_start"],
                                              seconds=shot["t_end"] - shot["t_start"], colour=colour, master=master))
                    ctx.heartbeat()
                self._adapters.submit("ffmpeg", Request("concat", inputs={"paths": [str(x) for x in parts]}, params={"out": str(out), "plain": True}))
            result["out"] = str(out)
        if request["request_id"]:
            self.store.finish_request(request["request_id"], "done", result)
        return result

    @staticmethod
    def _across_frames(steps: list[dict]) -> bool:
        return any(s["op"] in ACROSS_FRAMES for s in steps if not s.get("off"))

    def benchmark(self, subject: str, *, t: float | None = None) -> dict:
        """The engine measured on one clean frame of a subject (its graded look), damaged on purpose; kept with the subject."""
        from nexora.modules.visual_quality import benchmark as B
        profile = self.reader.profile(subject)
        if profile is None:
            raise LookupError(subject)
        path = self.path_of(subject)
        colour, _ = self.colour_steps(profile)
        when = t if t is not None else float(profile["technical"].get("duration") or 0.0) / 2
        frame = self.profiler._still(path, t=when, subject=subject, filters=filters_of(colour) or [], width=1280)
        if frame is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "no frame to measure on", retryable=False)
        h, w = frame.shape[:2]
        crop = frame[max(0, h // 2 - 300):h // 2 + 300, max(0, w // 2 - 450):w // 2 + 450]
        made = B.run(self._adapters, crop, lut_dir=self._work / "luts")
        made["subject"], made["t"] = subject, when
        B.save(made, self._work / subject / "bench")
        return made

    def forget(self, subject: str) -> None:
        self.store.forget(subject)
        shutil.rmtree(self._work / subject, ignore_errors=True)


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), np.float32) / 255.0


def _centre(img: np.ndarray, side: int = 1024) -> np.ndarray:
    """The middle of a picture at its own size: where detail made up or lost shows, without measuring all of a large one."""
    h, w = img.shape[:2]
    y, x = max(0, (h - side) // 2), max(0, (w - side) // 2)
    return img[y:y + side, x:x + side]


def _measure_width(technical: dict, most: int = 960) -> int:
    """The width frames are measured at: 960, or the source's own when smaller. Enlarging a frame smooths its noise away (a
    640-wide clip with σ 9 read 2.5 at 960, 2026-10-17), so measures are never taken on an enlarged picture."""
    width = int(technical.get("display_width") or technical.get("width") or most)
    return max(16, min(most, width - width % 2))


def _regions(picture: np.ndarray, shot: dict, side: int = 384) -> list[np.ndarray]:
    """The faces of a picture, each cut out (with a margin) and brought to one size, to be measured where a face step works:
    boxes are in the assessed picture's pixels and are scaled to this one's, which an enlargement may have made larger."""
    w0 = float((shot.get("size") or [picture.shape[1]])[0])
    k = picture.shape[1] / max(w0, 1.0)
    out = []
    for face in shot.get("faces", []):
        x, y, w, h = (v * k for v in face["box"])
        m = 0.15 * max(w, h)
        x0, y0 = int(max(0, x - m)), int(max(0, y - m))
        x1, y1 = int(min(picture.shape[1], x + w + m)), int(min(picture.shape[0], y + h + m))
        if x1 - x0 < 16 or y1 - y0 < 16:
            continue
        crop = Image.fromarray((np.clip(picture[y0:y1, x0:x1], 0, 1) * 255).round().astype(np.uint8)).resize((side, side), Image.LANCZOS)
        out.append(np.asarray(crop, np.float32) / 255.0)
    return out
