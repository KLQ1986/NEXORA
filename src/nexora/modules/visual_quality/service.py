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

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.visual_quality import VisualQuality, filters_of
from nexora.core.visual_quality_store import VisualQualityStore
from nexora.modules.visual_quality import assess as A
from nexora.modules.visual_quality import match as CM
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
STILL_TIERS = frozenset({"ffmpeg", "realesrgan", "codeformer", "nafnet", "local_tone"})     # what can run on one picture
# Opening a shade shows texture NIQE had not seen: measured on a backlit picture (2026-10-17), a clean relight cost 0.37 and
# one with a halo along the edge 0.63 (on a real backlit frame NIQE improved, 5.75 → 5.46). Between the two.
RELIGHT_NIQE_SLACK = 0.5
LOOK_PROMPT = ("Two versions of the same part of a photo. Which one looks clearer and more like a real, natural photograph? Also: does "
               "either version show something made up that is not believable (a face that looks like a different person, warped or "
               "garbled letters, painted or plastic texture, smeared shapes)? Answer JSON only: {\"better\": \"first\" or \"second\" or "
               "\"same\", \"invented\": \"first\" or \"second\" or \"none\", \"why\": \"a few words\"}")
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
        self._probed: dict[str, dict] = {}             # what a file says of itself, for planning the disk

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

    def approve(self, recipe_id: str, *, by: str = "operator") -> str | None:
        """Approve a recipe. What other versions of the subject had prepared goes (only the approved one is ever used), and when
        this one has steps a cut cannot do with filters, their files are prepared at once: a cut never has to fall back to the
        source as it is because nobody pressed apply. Returns that run, if any."""
        self.store.decide(recipe_id, "approved", decided_by=by)
        recipe = self.reader.by_id(recipe_id)
        if recipe is None:
            return None
        self._drop_prepared(recipe.subject, keep=recipe_id)
        needs = any(filters_of([s for s in shot["steps"] if not s.get("off")]) is None for shot in recipe.shots)
        return self.apply(recipe.subject) if needs and by != "policy" else None

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
            elif target["op"] == "match":
                target["params"]["lut"] = CM.bake(target["params"], self._work / "luts", amount=target["params"].get("amount", 1.0))
        if off is not None:
            target["off"] = bool(off)
        target["edited"] = True
        data["from"] = recipe_id
        return self.store.recipe(recipe.subject, data, status="proposed", decided_by="operator")

    def frame(self, subject: str, t: float, *, graded: bool = False, width: int = 1280) -> Path:
        """One frame of a subject for the screen, at `t` (a still: its picture), as the source is or with its colour steps
        (the encoding's transform, so a log file is seen as it will look). Kept, since the screen asks for the same ones."""
        profile = self.reader.profile(subject) or {}
        still = (profile.get("technical") or {}).get("kind") == "still"
        t = 0.0 if still else max(0.0, float(t))
        out = self._work / subject / "frames" / f"{t:.2f}_{'g' if graded else 's'}_{width}.jpg"
        if out.is_file():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        chain = (filters_of(self.colour_steps(profile)[0]) or []) if graded and profile else []
        self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(self.path_of(subject))},
                                                params={"kind": "still", "out": str(out), "t_in": t, "filters": chain, "width": width}))
        return out

    def export_path(self, subject: str, *, master: bool = False) -> Path:
        """Where the result of the approved recipe is written when the screen asks for it: beside the engine's work, named
        after the source and the recipe's version."""
        recipe = self.reader.recipe(subject, status="approved")
        if recipe is None:
            raise LookupError("no approved recipe")
        source = Path((self.reader.subject(subject) or {}).get("path") or subject)
        still = ((self.reader.profile(subject) or {}).get("technical") or {}).get("kind") == "still"
        ext = ".png" if still else ".mov" if master else ".mp4"
        return self._work / subject / "exports" / f"{source.stem}_vq_v{recipe.version}{ext}"

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

    def add_match(self, recipe_id: str, reference: str, t: float, *, shot: int | None = None, amount: float = 1.0, mode: str = "look") -> str:
        """Match a subject's colour to another's (footage cut together from different sources): a new proposed version of the
        recipe with a `match` step in the given shot, or in every shot, fitted to the reference's shot at `t` as that one will
        look (its own colour steps applied). Both sides are read after their colour steps, so the match is the last word on
        colour; a match already there is replaced. `mode`: `look` (tone, white balance, saturation: any two scenes) or `scene`
        (the whole spread of colours: two shots of one place)."""
        if mode not in CM.MODES:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"mode is one of {CM.MODES}", retryable=False)
        recipe = self.reader.by_id(recipe_id)
        if recipe is None:
            raise LookupError(recipe_id)
        if "ffmpeg:lut3d" not in self._have():
            raise AdapterError(ErrorCode.UNAVAILABLE, "this FFmpeg build has no lut3d", retryable=False)
        if reference == recipe.subject:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "a subject is not matched to itself", retryable=False)
        ref_profile = self.reader.profile(reference)
        if ref_profile is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "the reference has not been analysed yet", retryable=False)
        ref_still = (ref_profile.get("technical") or {}).get("kind") == "still"
        ref_recipe = self.reader.recipe(reference, status="approved") or self.reader.recipe(reference)
        ref_shots = (ref_recipe.shots if ref_recipe else None) or [{"t_start": 0.0, "t_end": float((ref_profile.get("technical") or {}).get("duration") or 0), "steps": []}]
        t = 0.0 if ref_still else max(0.0, float(t))
        ref_shot = next((x for x in ref_shots if x["t_start"] <= t <= max(x["t_end"], x["t_start"])), ref_shots[0])
        ref_chain = self._colour_chain(ref_shot["steps"]) if ref_recipe else (filters_of(self.colour_steps(ref_profile)[0]) or [])
        wanted = self._colour_pixels(reference, ref_shot, ref_chain, still=ref_still)
        still = ((self.reader.profile(recipe.subject) or {}).get("technical") or {}).get("kind") == "still"
        data = __import__("copy").deepcopy(recipe.data)
        amount = float(min(1.0, max(0.0, amount)))
        for k in ([shot] if shot is not None else range(len(data["shots"]))):
            here = data["shots"][k]
            steps = [x for x in here["steps"] if x["op"] != "match"]
            made = CM.fit(self._colour_pixels(recipe.subject, here, self._colour_chain(steps), still=still), wanted, mode=mode)
            params = {**made["controls"], "amount": amount, "mode": mode, "reference": {"subject": reference, "t": round(t, 2)},
                      "before": made["before"], "after": made["after"], "doubtful": made["doubtful"], "balanced": made["balanced"]}
            params["lut"] = CM.bake(params, self._work / "luts", amount=amount)
            why = f"khớp {'cả phân bố màu (cùng cảnh)' if mode == 'scene' else 'tông máy quay'} theo {reference} lúc {t:.1f}s (lệch {made['before']:.1f} → {made['after']:.1f})"
            if not made["balanced"]:
                why += "; không thấy mảng xám để đo cân bằng trắng, giữ nguyên nhiệt độ màu"
            if made["doubtful"]:
                why += "; KHÔNG CHẮC: " + (f"{', '.join(made['pinned'])} chạm giới hạn" if made["pinned"] else "khoảng lệch giảm ít") + ", có lẽ hai cảnh khác nhau về nội dung, xem kỹ trước khi duyệt"
            steps.append({"op": "match", "tier": "ffmpeg", "params": params, "edited": True, "why": why})
            here["steps"] = sorted(steps, key=lambda x: P.ORDER.index(x["op"]) if x["op"] in P.ORDER else 99)
        data["from"] = recipe_id
        return self.store.recipe(recipe.subject, data, status="proposed", decided_by="operator")

    @staticmethod
    def _colour_chain(steps: list[dict]) -> list[str]:
        """The filters of a shot's colour steps alone: how its colours will look, without the work on detail."""
        return filters_of([x for x in steps if x["op"] in ("color_transform", "tonemap", "levels", "match") and not x.get("off")]) or []

    def _colour_pixels(self, subject: str, shot: dict, chain: list[str], *, still: bool, frames: int = 5) -> np.ndarray:
        """Pixels of a shot as display RGB (0..1): a few frames across it (a still: its picture), small, through `chain`."""
        work = self._work / subject / "match"
        work.mkdir(parents=True, exist_ok=True)
        t0, t1 = float(shot.get("t_start") or 0.0), float(shot.get("t_end") or 0.0)
        times = [0.0] if still or t1 - t0 < 0.2 else [t0 + (t1 - t0) * (k + 0.5) / frames for k in range(frames)]
        pixels = []
        try:
            for k, t in enumerate(times):
                out = work / f"sample_{k}.png"
                self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(self.path_of(subject))},
                                                        params={"kind": "still", "out": str(out), "t_in": t, "filters": chain, "width": 480}))
                with Image.open(out) as im:
                    pixels.append(np.asarray(im.convert("RGB"), np.float64).reshape(-1, 3) / 255.0)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return np.concatenate(pixels)

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
        if "local_tone" in names:
            have.add("local_tone")
        if "deblur" in names:
            try:
                if (self._adapters.environment().get("deblur") or {}).get("deblur"):
                    have.add("nafnet")
            except Exception:
                pass
        if any(n.startswith("restore_remote") for n in names):
            have.add("vrt_remote")
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
        shutil.rmtree(self._work / ctx.subject_ref / "verify", ignore_errors=True)       # the trial renders of the checks
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

    def _look_judge(self, work: Path, step: dict, *, picture_ai: Path, picture_classic: Path, shot: dict) -> dict | None:
        """A second judge with eyes, after NIQE: the local vision model (Qwen3-VL) sees the same part of the picture with the AI
        step and with the classic one, twice with the two swapped (small models favour a side), and says which is clearer and
        whether the AI made up something false: a face turned into someone else, letters that are not there, texture painted
        over what was. It can only stop an AI step NIQE let through, when both looks agree; never put one in. None when no
        vision model is here."""
        if "model" not in {c.name for c in self._adapters.describe()}:
            return None
        try:
            a, b = _load_rgb(picture_ai), _load_rgb(picture_classic)
        except OSError:
            return None
        crops_a = _regions(a, shot) if step["op"] == "faces" else [_centre(a, 768)]
        crops_b = _regions(b, shot) if step["op"] == "faces" else [_centre(b, 768)]
        if not crops_a or len(crops_a) != len(crops_b):
            return None
        fa, fb = work / f"{step['op']}_judge_ai.jpg", work / f"{step['op']}_judge_classic.jpg"
        Image.fromarray((np.clip(crops_a[0], 0, 1) * 255).round().astype(np.uint8)).save(fa, quality=95)
        Image.fromarray((np.clip(crops_b[0], 0, 1) * 255).round().astype(np.uint8)).save(fb, quality=95)
        answers = []
        for first, second, ai_is in ((fa, fb, "first"), (fb, fa, "second")):
            try:
                out = self._adapters.submit("model", Request("describe", inputs={"images": [str(first), str(second)]},
                                                                params={"prompt": LOOK_PROMPT, "task": "judge", "max_tokens": 200})).outputs["json"]
            except (AdapterError, KeyError):
                return None
            better = str(out.get("better", "")).lower()
            invented = str(out.get("invented", "")).lower()
            answers.append({"ai_better": better == ai_is, "classic_better": better in ("first", "second") and better != ai_is,
                            "ai_invented": invented == ai_is, "why": str(out.get("why", ""))[:200]})
        veto = all(x["classic_better"] or x["ai_invented"] for x in answers)
        return {"veto": veto, "ai_better_both": all(x["ai_better"] for x in answers), "why": "; ".join(x["why"] for x in answers if x["why"])[:400]}

    @staticmethod
    def _judge_relight(with_it: Path, without: Path, niqe_with: float | None, niqe_without: float | None) -> tuple[bool, dict | str]:
        """A relight is kept when it brings a quarter or more of the near-black picture into sight, clips no more highlights,
        and costs no more naturalness than `RELIGHT_NIQE_SLACK`. NIQE alone barely sees shadows opened."""
        try:
            a, b = _load_rgb(with_it), _load_rgb(without)
        except OSError:
            return False, "không đọc được ảnh thử"
        ya, yb = M.luma(a), M.luma(b)
        dark_a, dark_b = float((ya < 0.1).mean()), float((yb < 0.1).mean())
        clip_a, clip_b = float((ya > 0.985).mean()), float((yb > 0.985).mean())
        note = {"dark_without": round(dark_b, 4), "dark_with": round(dark_a, 4), "clipped_without": round(clip_b, 4), "clipped_with": round(clip_a, 4),
                **({"niqe_without": round(niqe_without, 3), "niqe_with": round(niqe_with, 3)} if niqe_with is not None and niqe_without is not None else {})}
        opened = dark_b > 0.02 and dark_a <= dark_b * 0.75
        natural = niqe_with is None or niqe_without is None or niqe_with <= niqe_without + RELIGHT_NIQE_SLACK
        return bool(opened and clip_a <= clip_b + 0.005 and natural), note

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
        if path.suffix.lower() not in STILL_EXT:
            # A video's step is judged on the shot's middle frame, taken out once at full size, with the steps a picture can take.
            frame = work / f"frame_{(shot['t_start'] + shot['t_end']) / 2:.2f}.png"
            self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(path)}, params={
                "kind": "still", "out": str(frame), "t_in": (shot["t_start"] + shot["t_end"]) / 2, "filters": [], "deep": True}))
            path = frame
        on_still = lambda chain: [s for s in chain if s.get("tier", "ffmpeg") in STILL_TIERS]
        for step in [s for s in steps if "classic" in s]:
            classic = step["classic"]
            other = [classic if s is step else s for s in kept if s is not step or classic]
            # A restore by AI takes away noise, banding and blocks at once: with it, the classic steps for those are left out.
            absorbed = AI_ABSORBS.get(step["op"], frozenset())
            mine = [{k: v for k, v in s.items() if k != "classic"} for s in kept if s is step or s["op"] not in absorbed]
            scores, failed = {}, {}
            for name, chain in (("ai", on_still(mine)), ("classic", on_still([{k: v for k, v in s.items() if k != "classic"} for s in other]))):
                try:
                    file = self._render(path, chain, out=work / f"{step['op']}_{name}.png", kind="still")
                    picture = _load_rgb(file)
                    regions = _regions(picture, shot) if step["op"] == "faces" else [_centre(picture)]
                    values = [v for v in (A.niqe_of(r) for r in regions) if v is not None]
                    scores[name] = float(np.mean(values)) if values else None
                except AdapterError as e:
                    scores[name], failed[name] = None, str(e)[:300]
            ai, base = scores.get("ai"), scores.get("classic")
            if failed:
                # A step that could not be tried is not a step that lost: it is said as a failure, with the error.
                kept = other
                shot.setdefault("dropped", []).append({"op": step["op"], "why": "không thử được: " + "; ".join(f"{k}: {v}" for k, v in failed.items()), "failed": True})
                continue
            if step["op"] == "relight":
                keep, note = self._judge_relight(work / f"{step['op']}_ai.png", work / f"{step['op']}_classic.png", ai, base)
                if keep:
                    step["checked"] = note
                    kept = [{k: v for k, v in s.items() if k != "classic"} if s is step else s for s in kept]
                else:
                    kept = other
                    shot.setdefault("dropped", []).append({"op": step["op"], "why": f"không làm lộ thêm vùng tối đủ rõ ({note})"})
                continue
            seen = self._look_judge(work, step, picture_ai=work / f"{step['op']}_ai.png", picture_classic=work / f"{step['op']}_classic.png", shot=shot) \
                if ai is not None and base is not None and ai < base - AI_MARGIN else None
            if seen and seen.get("veto"):
                kept = other
                shot.setdefault("dropped", []).append({"op": step["op"], "why": f"Qwen3-VL thấy bản AI kém hơn: {seen['why']}", "judge": seen})
                continue
            if ai is not None and base is not None and ai < base - AI_MARGIN:
                step["checked"] = {"niqe_classic": round(base, 3), "niqe_ai": round(ai, 3), **({"judge": seen} if seen else {"judge": None})}
                kept = [{k: v for k, v in s.items() if k != "classic"} if s is step else s for s in kept if s is step or s["op"] not in absorbed]
            else:
                kept = other
                shot.setdefault("dropped", []).append({"op": step["op"], "why": ("AI không hơn khi để nguyên" if classic is None else "AI không hơn cách cổ điển") + (f" (NIQE {base:.2f} so với {ai:.2f})" if ai is not None and base is not None else "")})
        return kept

    def _render(self, path: Path, steps: list[dict], *, out: Path, kind: str, t_in: float = 0.0, seconds: float | None = None,
                width: int | None = None, colour: dict | None = None, codec: str | None = None, master: bool = False, deep: bool = False) -> Path:
        """A stretch through the steps: FFmpeg filters in one go; when a step needs another tool, the steps up to the last such
        one run first, in their order, and the FFmpeg steps after it finish the job."""
        chain = filters_of(steps)
        sound: dict = {}
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
                self._room(seconds or self._length(path) - t_in, path, keep=False)
                source, rest = self._prepare(path, steps, t_in=t_in, seconds=seconds, work=out.parent)
                # The processors give pictures only: the sound comes straight from the same stretch of the source.
                sound = {"sound_from": str(path), "sound_t_in": t_in}
                chain, path, t_in = filters_of(rest) or [], source, 0.0
        params = {"kind": kind, "out": str(out), "t_in": t_in, "filters": chain, "colour": colour or {}, "master": master, "deep": deep,
                  **sound}
        if seconds and kind != "still":
            params["seconds"] = seconds
        if width:
            params["width"] = width
        if codec:
            params["codec"] = codec
        try:
            self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(path)}, params=params))
        finally:
            if Path(path).name.startswith("prep_") and Path(path) != out:
                Path(path).unlink(missing_ok=True)                    # the last intermediate, read by the final render
        return out

    # The rates the disk is planned with, at 4K and 30 frames a second (measured on 0002, 2026-10-17), scaled by pixels and rate.
    STORE_RATE = 31e6           # bytes a second of a prepared file (HEVC 10-bit, Apple encoder)
    WORK_RATE = 116e6           # of an intermediate (ProRes 422 HQ)
    ROOM_MARGIN = 2e9           # always left free

    def _rate(self, path: Path) -> float:
        """How much bigger or smaller than 4K at 30 a picture is, for the rates above."""
        tech = self._technical(path)
        w, h = int(tech.get("width") or 3840), int(tech.get("height") or 2160)
        fps = float(tech.get("frame_rate") or 30.0)
        return (w * h) / (3840 * 2160) * fps / 30.0

    def _length(self, path: Path) -> float:
        return float(self._technical(path).get("duration") or 0.0)

    def _technical(self, path: Path) -> dict:
        """What the file says of its size, rate and length (the probe the profile is made from), kept by path."""
        key = str(path)
        if key not in self._probed:
            try:
                self._probed[key] = self._adapters.submit("ffprobe", Request("probe", inputs={"path": key})).outputs
            except AdapterError:
                self._probed[key] = {}
        return self._probed[key]

    def _room(self, seconds: float, path: Path, *, keep: bool, kept_seconds: float = 0.0) -> None:
        """Refuse before starting, rather than fail half way: the disk must hold the intermediates of the longest stretch (two
        at a time), what is kept (prepared files), and a margin."""
        k = self._rate(path)
        need = 2 * max(0.0, seconds) * self.WORK_RATE * k + (kept_seconds * self.STORE_RATE * k if keep else 0.0) + self.ROOM_MARGIN
        free = shutil.disk_usage(self._work if self._work.exists() else self._work.parent).free
        if free < need:
            raise AdapterError(ErrorCode.INSUFFICIENT_STORAGE, f"cần khoảng {need / 1e9:.1f} GB trống cho việc này, ổ chỉ còn {free / 1e9:.1f} GB "
                               "(bấm Dọn ở màn Chất lượng hình, hoặc giải phóng ổ)", retryable=False)

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
        elif tier == "local_tone":
            self._adapters.submit("local_tone", Request("relight", inputs={"path": str(source)}, params={**span, **{k: p[k] for k in ("shadows", "highlights") if k in p}}))
        elif tier == "nafnet":
            self._adapters.submit("deblur", Request("deblur", inputs={"path": str(source)}, params={**span, "kind": "video"}))
        elif tier == "vrt_remote":
            self._remote_restore(source, out, t_in=t_in, seconds=seconds, task="deblur")
        elif tier == "propainter":
            self._adapters.submit("inpaint", Request("remove", inputs={"path": str(source)}, params={**span, "regions": p["regions"]}))
        elif tier == "vidstab":
            self._adapters.submit("ffmpeg", Request("vq_stabilise", inputs={"path": str(source)}, params={**span, "smoothing": p.get("smoothing", 15), "zoom": p.get("zoom", 0)}))
        elif tier == "gyroflow":
            self._adapters.submit("gyroflow", Request("stabilise", inputs={"path": str(source)}, params={**span, "smoothness": p.get("smoothness", 0.5)}))
        else:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"no tool for {tier} on this machine", retryable=False)
        return out

    def _remote_restore(self, source: Path, out: Path, *, t_in: float, seconds: float | None, task: str) -> None:
        """A span sent to the operator's restoration endpoint (VRT/RVRT on a rented GPU). Only ever for a step the operator
        allowed to leave this machine (the recipe's `allow_cloud`); privacy mode still stops it in the registry. The span goes
        as a compact H.264 copy, and comes back cut to its exact number of frames, in ProRes like every other tool's."""
        name = next((c.name for c in self._adapters.describe() if c.name.startswith("restore_remote")), None)
        if name is None:
            raise AdapterError(ErrorCode.UNAVAILABLE, "no restoration endpoint (runpod_restore_endpoint in nexora.toml)", retryable=False)
        sent, back = out.with_name(out.stem + "_sent.mp4"), out.with_name(out.stem + "_back.mp4")
        self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(source)}, params={
            "kind": "video", "out": str(sent), "t_in": t_in, "filters": [], "codec": "h264", **({"seconds": seconds} if seconds else {})}))
        self._adapters.submit(name, Request("deblur", inputs={"video": str(sent)}, params={"out": str(back), "task": task}, privacy_class=PrivacyClass.CLOUD_ALLOWED))
        self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(back)}, params={
            "kind": "video", "out": str(out), "t_in": 0.0, "filters": [], "master": True, **({"seconds": seconds} if seconds else {})}))

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
                self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(current)}, params={"kind": "still", "out": str(baked), "filters": filters_of(pending) or [],
                                                                                                           "deep": True}))
                current, pending = baked, []
            current = self._process_still(step, current, work / f"prep_{stamp}_{k}_{step['op']}.png")
        return current, steps[last + 1:]

    def _process_still(self, step: dict, source: Path, out: Path) -> Path:
        tier, op, p = step.get("tier"), step["op"], step.get("params") or {}
        if tier == "nafnet":
            self._adapters.submit("deblur", Request("deblur", inputs={"path": str(source)}, params={"out": str(out), "kind": "still"}))
            return out
        if tier == "local_tone":
            self._adapters.submit("local_tone", Request("relight", inputs={"path": str(source)}, params={"out": str(out), "kind": "still",
                                                                                                     **{k: p[k] for k in ("shadows", "highlights") if k in p}}))
            return out
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
        between, so that each step sees what the steps before it made. Returns the intermediate (picture only: the final render
        takes the sound from the source) and the FFmpeg steps left after the last processor. Each intermediate is removed as
        soon as the next step has read it, so at most two are on the disk at once."""
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
                current = self._drop_intermediate(current, path, baked)
                offset, pending = 0.0, []
            made = self._process(step, current, work / f"prep_{stamp}_{k}_{step['op']}.mov", t_in=offset, seconds=seconds if offset or current == path else None)
            current = self._drop_intermediate(current, path, made)
            offset = 0.0
        return current, steps[last + 1:]

    @staticmethod
    def _drop_intermediate(previous: Path, source: Path, made: Path) -> Path:
        """`made` replaces `previous`; an intermediate (never the source) is removed once it has been read."""
        if Path(previous) != Path(source) and Path(previous) != Path(made) and Path(previous).name.startswith("prep_"):
            Path(previous).unlink(missing_ok=True)
        return made

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
        verdict = Q.compare(before, after, colour_changed=any(s["op"] in ("color_transform", "tonemap", "levels", "match") for s in steps), ops=[s["op"] for s in steps])
        data = {"files": {k: str(v) for k, v in files.items()}, "qa": verdict, "steps": [s["op"] for s in steps], "t_shot": [shot["t_start"], shot["t_end"]]}
        preview_id = self.store.preview(recipe.recipe_id, t0, seconds, data)
        self.store.metrics(recipe.recipe_id, [(shot["t_start"], shot["t_end"], name, b, a) for name, (b, a) in verdict["metrics"].items()])
        if request["request_id"]:
            self.store.finish_request(request["request_id"], "done", {"preview_id": preview_id, "verdict": verdict["verdict"]})
        self._tidy_previews(ctx.subject_ref)
        return {"preview_id": preview_id, "verdict": verdict["verdict"]}

    def render_approved(self, subject: str, out: str | Path | None, *, master: bool = False, heartbeat=lambda: None) -> dict:
        """The approved recipe of a subject, rendered: the files a cut takes for steps it cannot do with filters, and, with `out`,
        the whole result in one file (HEVC 10-bit, ProRes with `master`, PNG for a still) with the recipe's colour description.
        A shot already prepared is taken from its prepared file, so no AI step runs twice. The library's enhanced copy is made
        by this, so the copy and a cut are the same picture."""
        recipe = self.reader.recipe(subject, status="approved")
        if recipe is None:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "no approved recipe", retryable=False)
        path = self.path_of(subject)
        technical = (self.reader.profile(subject) or {}).get("technical", {})
        colour = recipe.data.get("output", {}).get("colour", {})
        work = self._work / subject / "apply" / recipe.recipe_id
        work.mkdir(parents=True, exist_ok=True)
        still = technical.get("kind") == "still"
        made: dict[int, Path] = {}
        if not still:
            # Room for every shot that will be kept prepared, and for the intermediates of the longest of them, before any starts.
            todo = [shot["t_end"] - shot["t_start"] for shot in recipe.shots if filters_of([s for s in shot["steps"] if not s.get("off")]) is None
                    and not self.reader.prepared_for(subject, shot["t_start"], shot["t_end"])]
            if todo:
                self._room(max(todo), path, keep=True, kept_seconds=sum(todo))
        for k, shot in enumerate(recipe.shots):
            steps = [s for s in shot["steps"] if not s.get("off")]
            if filters_of(steps) is not None:
                continue
            known = self.reader.prepared_for(subject, shot["t_start"], shot["t_end"]) if not still else None
            if known and Path(known[0]).is_file() and known[1] == 0:
                made[k] = Path(known[0])
                continue
            if still:
                file = self._render(path, steps, out=work / "still.png", kind="still", colour=colour, deep=True)
            else:
                # Kept for as long as the recipe is approved: HEVC 10-bit by the Apple encoder, a quarter of ProRes for the same
                # picture (SSIM 0.997), so a long shot's prepared file fits on the disk.
                file = self._render(path, steps, out=work / f"shot_{shot['t_start']:.2f}.mp4", kind="video", t_in=shot["t_start"],
                                    seconds=shot["t_end"] - shot["t_start"], colour=colour, codec="store")
            self.store.prepared(recipe.recipe_id, shot["t_start"], shot["t_end"], file)
            made[k] = Path(file)
            heartbeat()
        result: dict = {"prepared": len(made), "recipe_id": recipe.recipe_id, "version": recipe.version}
        if out:
            out = Path(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            if still:
                if 0 in made:      # already made above: written in the format asked, without running the AI a second time
                    self._adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(made[0])}, params={"kind": "still", "out": str(out), "filters": [], "colour": colour}))
                else:
                    self._render(path, [s for s in recipe.shots[0]["steps"] if not s.get("off")], out=out, kind="still", colour=colour)
            elif not made and (len(recipe.shots) == 1 or (len({str(s["steps"]) for s in recipe.shots}) == 1 and not self._across_frames(recipe.shots[0]["steps"]))):
                self._render(path, [s for s in recipe.shots[0]["steps"] if not s.get("off")], out=out, kind="video", colour=colour, master=master)
            else:
                # Shot by shot, each with its own steps (a prepared shot from its file), in the codec of the result, then joined
                # without re-encoding. Steps that look across frames never see across a cut this way.
                parts = []
                for k, shot in enumerate(recipe.shots):
                    part = work / f"part_{k:04d}{'.mov' if master else '.mp4'}"
                    if k in made:
                        parts.append(self._render(made[k], [], out=part, kind="video", colour=colour, master=master))
                    else:
                        steps = [s for s in shot["steps"] if not s.get("off")]
                        parts.append(self._render(path, steps, out=part, kind="video", t_in=shot["t_start"], seconds=shot["t_end"] - shot["t_start"],
                                                  colour=colour, master=master))
                    heartbeat()
                self._adapters.submit("ffmpeg", Request("concat", inputs={"paths": [str(x) for x in parts]}, params={"out": str(out), "plain": True}))
                for part in parts:
                    Path(part).unlink(missing_ok=True)
                result["parts"] = len(parts)
            result["out"] = str(out)
        return result

    # ------------------------------------------------------------------------------------------------------------ tidying
    PREVIEWS_KEPT = 6           # previews of a recipe kept with their pictures; older ones go

    def _drop_prepared(self, subject: str, *, keep: str | None) -> int:
        """Prepared files of a subject's recipes other than `keep`: never used again, so removed with their records."""
        others = [r.recipe_id for r in self.reader.recipes(subject) if r.recipe_id != keep]
        freed = 0
        for rid in others:
            folder = self._work / subject / "apply" / rid
            if folder.is_dir():
                freed += sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
                shutil.rmtree(folder, ignore_errors=True)
        self.store.forget_prepared(others)
        return freed

    def _tidy_previews(self, subject: str) -> int:
        """The working files of previews (the prepared intermediates) go once the preview is made, and only the newest
        previews of each recipe keep their pictures."""
        freed = 0
        root = self._work / subject / "previews"
        if not root.is_dir():
            return 0
        for f in root.glob("*/prep_*"):
            freed += f.stat().st_size
            f.unlink(missing_ok=True)
        for recipe in self.reader.recipes(subject):
            old = self.reader.previews(recipe.recipe_id)[self.PREVIEWS_KEPT:]
            for preview in old:
                folder = next((Path(v).parent for v in (preview.get("files") or {}).values()), None)
                if folder and folder.is_dir() and root in folder.parents:
                    freed += sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
                    shutil.rmtree(folder, ignore_errors=True)
            self.store.forget_previews([p["preview_id"] for p in old])
        return freed

    def tidy(self, subject: str | None = None) -> dict:
        """Everything the engine keeps that nothing will use again, removed: preview intermediates and old previews, the
        prepared files of recipes that are not approved, the checks' trial renders and cached frames. The recipes, profiles,
        the approved recipe's prepared files and anything exported stay. Returns what was freed."""
        subjects = [subject] if subject else [p.name for p in self._work.iterdir() if p.is_dir() and p.name not in ("luts", "tmp")] if self._work.is_dir() else []
        freed = 0
        for sub in subjects:
            if self.reader.subject(sub) is None:
                continue
            approved = self.reader.recipe(sub, status="approved")
            freed += self._drop_prepared(sub, keep=approved.recipe_id if approved else None)
            freed += self._tidy_previews(sub)
            for name in ("verify", "frames"):
                folder = self._work / sub / name
                if folder.is_dir():
                    freed += sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
                    shutil.rmtree(folder, ignore_errors=True)
        return {"subjects": len(subjects), "freed_bytes": freed}

    def _apply_stage(self, ctx):
        request = self._request(ctx.subject_ref, "apply")
        p = request["params"]
        result = self.render_approved(ctx.subject_ref, p.get("out"), master=bool(p.get("master")), heartbeat=ctx.heartbeat)
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
