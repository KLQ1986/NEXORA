"""Sourcing by generation: AI-generated shots, keyframe first (design v4.0, sections 18.4-18.6).

A still is generated and approved for every shot before any video is paid for. The approved still is
the first frame of the clip. Prompts are compiled deterministically from a structured description,
and every generation is recorded with its prompt and seed so that it can be reproduced or varied.

Several providers may serve the same kind of picture. Each shot goes to the provider the operator chose for it, else
to the first in the operator's order of preference; a provider that is down, out of quota or kept back by privacy
mode is passed over for the next one. Every still is looked at before it is shown: one that misses the brief or is
visibly broken is made again with another seed, a bounded number of times, and the best attempt is the one proposed.
"""
import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.projects import ProjectStore

GENERATE = PipelineDefinition("sourcing.generate", "1", [
    StageDef("keyframes", costly=True, gate=True, requires=("image_gen",)),                       # stills first: cheap to produce, cheap to correct
    StageDef("clips", depends_on=("keyframes",), costly=True, gate=True, requires=("video_gen",)),
])
# A model of one character, trained from the operator's pictures of it. Long and paid for, so it runs in the background and is asked for by name.
TRAIN = PipelineDefinition("sourcing.train", "1", [StageDef("train", costly=True, timeout_seconds=5 * 3600, lane="background", requires=("train",))])
MIN_PICTURES, MAX_PICTURES = 4, 20
COMPILER_VERSION = "2"
MAX_REPAIRS = 2              # after the first still, at most this many more are made for one shot
QUALITY_PASS = 6             # out of 10: below this a still is made again
PASS_OVER = frozenset({ErrorCode.UNAVAILABLE, ErrorCode.TIMEOUT, ErrorCode.RATE_LIMITED, ErrorCode.QUOTA_EXHAUSTED, ErrorCode.AUTH})
SHOT_SIZES = ("wide shot", "medium shot", "close-up", "extreme close-up")
CAMERAS = ("slow push in", "slow pull out", "pan left", "pan right", "static")
QUALITY_PROMPT = (
    "Đây là một ảnh được sinh ra cho yêu cầu: \"{subject}\".\n"
    "Chấm ảnh từ 0 đến 10: ảnh có đúng thứ được yêu cầu không, và có lỗi nhìn thấy được không (tay hoặc mặt méo, vật thể dính vào nhau, chữ vô nghĩa, bố cục cắt mất chủ thể). "
    "Chỉ trả về JSON với các khoá: diem (số nguyên 0 đến 10), loi (danh sách các lỗi thấy được, mỗi lỗi một cụm từ ngắn; danh sách rỗng nếu không có)."
)
WORDS_PER_SECOND = 2.6
ASPECT = {"landscape": "16:9", "portrait": "9:16", "square": "1:1"}


@dataclass(frozen=True)
class PromptSpec:
    """Provider-neutral description of one picture."""
    subject: str
    style: str = ""
    shot_size: str = "medium shot"
    camera: str = "slow push in"
    aspect: str = "16:9"
    duration: float = 4.0
    exclusions: str = "text, watermark, logo, distorted hands"
    cast: str = ""                       # how the named characters, places and props of the project look, so that they look the same in every shot
    references: tuple = ()               # asset ids of the pictures that show them
    models: tuple = ()                   # trained character models (LoRA files) to load for this picture
    model_urls: tuple = ()               # where the training endpoint keeps those models, for an image endpoint that loads them by address


def compile_prompt(spec: PromptSpec, *, kind: str) -> str:
    """The same spec always gives the same prompt."""
    parts = [spec.subject.strip().rstrip("."), spec.shot_size]
    if spec.cast:
        parts.append(spec.cast.strip().rstrip("."))
    if kind == "video":
        parts.append(f"camera: {spec.camera}")
    if spec.style:
        parts.append(f"style: {spec.style.strip()}")
    parts.append(f"aspect ratio {spec.aspect}")
    return ". ".join(parts) + f". Avoid: {spec.exclusions}."


def seed_for(shot_id: str, attempt: int) -> int:
    """A fixed seed per shot and attempt: the same request reproduces, a new attempt varies."""
    return int(hashlib.sha256(f"{shot_id}:{attempt}".encode()).hexdigest()[:8], 16)


def split_duration(seconds: float, limit: float) -> list[float]:
    """Sub-shot lengths for a shot longer than the provider's clip limit."""
    if seconds <= limit:
        return [round(seconds, 2)]
    parts = int(-(-seconds // limit))
    return [round(seconds / parts, 2)] * parts


class Generation:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, assets: AssetStore, adapters: AdapterRegistry, media_dir: str | Path,
                 *, max_clip_seconds: float = 8.0, judge: bool = False, prefer=None):
        self._orch, self._projects, self._assets, self._adapters = orch, projects, assets, adapters
        self._judge = judge                                   # a vision model is there to look at each still
        self._prefer = prefer or (lambda kind: [])            # the operator's order of providers for "image_gen" or "video_gen"
        self._media, self._limit = Path(media_dir) / "generated", max_clip_seconds
        self._media.mkdir(parents=True, exist_ok=True)

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(GENERATE, {"keyframes": self._keyframes, "clips": self._clips})
        registry.register(TRAIN, {"train": self._train})

    def start_training(self, project_id: str, name: str, asset_ids: list[str]) -> str:
        """Train a model of one character of the project's bible from pictures in the library. The pictures are sent to the
        operator's training endpoint, so only pictures allowed to leave this machine are taken unless the project permits it."""
        project = self._projects.project(project_id)
        bible = json.loads(project.get("bible") or "[]")
        entry = next((e for e in bible if e["name"] == name and e.get("kind") == "character"), None)
        pictures = [a for a in dict.fromkeys(asset_ids) if (self._assets.asset(a) or {}).get("kind") == "image"][:MAX_PICTURES]
        if entry is None or len(pictures) < MIN_PICTURES:
            raise ValueError(f"training needs a character of this project and at least {MIN_PICTURES} pictures from the library")
        import re, unicodedata
        plain = "".join(c for c in unicodedata.normalize("NFD", name.replace("đ", "d").replace("Đ", "D")) if unicodedata.category(c) != "Mn")
        entry["training"] = {"assets": pictures, "status": "queued", "trigger": "nx" + re.sub(r"[^a-z0-9]", "", plain.lower())[:12]}
        self._projects.update_project(project_id, bible=json.dumps(bible, ensure_ascii=False))
        return self._orch.submit_run(TRAIN, subject_ref=f"{project_id}|{name}")

    def _train(self, ctx):
        project_id, _, name = ctx.subject_ref.partition("|")
        project = self._projects.project(project_id)
        bible = json.loads(project.get("bible") or "[]")
        entry = next(e for e in bible if e["name"] == name)
        job = entry["training"]
        may_leave = bool(json.loads(project.get("options") or "{}").get("footage_may_leave"))
        private = [a for a in job["assets"] if (self._assets.asset(a) or {}).get("privacy_class") != "cloud_allowed"]
        paths = [str(self._assets.path_of(self._assets.original(a))) for a in job["assets"]]
        out = self._media / f"character_{hashlib.sha256(ctx.subject_ref.encode()).hexdigest()[:12]}.safetensors"
        result, provider = self._submit("train", None, Request("train", inputs={"images": paths}, params={"out": str(out), "name": name, "trigger": job["trigger"]}, attempt_id=ctx.claim.attempt_id,
                                                              privacy_class=PrivacyClass.LOCAL_ONLY if private and not may_leave else PrivacyClass.CLOUD_ALLOWED))
        if result.usage.cost:
            ctx.record_cost(provider=provider, units=result.usage.units, cost=result.usage.cost)
        bible = json.loads(self._projects.project(project_id).get("bible") or "[]")            # read again: the operator may have edited it meanwhile
        for e in bible:
            if e["name"] == name:
                e["model"] = str(out)
                e["training"] = {**job, "status": "done", "base_model": result.outputs.get("model"), "model_url": result.outputs.get("model_url")}
        self._projects.update_project(project_id, bible=json.dumps(bible, ensure_ascii=False))
        return {"model": str(out), "pictures": len(paths)}

    def providers(self, kind: str) -> list[dict]:
        """Every adapter that makes this kind of picture: `image_gen` itself or `image_gen.<name>`, in the operator's order."""
        found = [c for c in self._adapters.describe() if c.name == kind or c.name.startswith(kind + ".")]
        order = {name: i for i, name in enumerate(self._prefer(kind))}
        found.sort(key=lambda c: order.get(c.name, len(order)))
        return [{"name": c.name, "label": c.name.partition(".")[2] or "mặc định", "runs": c.runs} for c in found]

    def available(self) -> dict:
        image, video = self.providers("image_gen"), self.providers("video_gen")
        return {"image": bool(image), "video": bool(video), "image_providers": image, "video_providers": video}

    def _submit(self, kind: str, wanted: str | None, request: Request):
        """Send the request to the provider chosen for the shot, else down the order of preference. Returns (result, provider name)."""
        names = [p["name"] for p in self.providers(kind)]
        if not names:
            # No provider is configured: only the operator can fix that, so the stage waits instead of failing.
            raise AdapterError(ErrorCode.AUTH, f"no {kind} provider is configured")
        order = ([wanted] if wanted in names else []) + [n for n in names if n != wanted]
        for i, name in enumerate(order):
            try:
                return self._adapters.submit(name, request), name
            except AdapterError as err:
                if err.code not in PASS_OVER or i == len(order) - 1:
                    raise
        raise AssertionError("unreachable")

    def start(self, script_id: str) -> str:
        self._projects.set_match_approved(script_id, False)
        project = self._projects.project(self._projects.script(script_id)["project_id"])
        cap = project.get("budget_cap")
        # A project's budget covers all of its paid work: this run may spend only what earlier runs have left.
        left = None if cap is None else max(0.0, cap - self.spent(project["project_id"]))
        self._orch.supersede(GENERATE.pipeline_id, script_id)
        return self._orch.submit_run(GENERATE, subject_ref=script_id, budget_cap=left)

    def spent(self, project_id: str) -> float:
        return sum(self._orch.run_cost(r) for s in self._projects.script_ids(project_id) for r in self._orch.runs_for_subject(s))

    def spec_for(self, shot, project: dict) -> PromptSpec:
        """The picture for a shot: what the operator asked to see if they said so, else the line itself; framed as they chose;
        and with every character, place or prop of the project's bible that the shot names described the same way each time."""
        gen = shot.gen
        subject = gen.get("subject") or shot.brief or shot.text
        named = f"{shot.text} {subject}".lower()
        cast = [e for e in json.loads(project.get("bible") or "[]") if e.get("kind") == "style" or e["name"].lower() in named]
        return PromptSpec(subject=subject, style=project.get("style") or "", aspect=ASPECT.get(project["format"], "16:9"),
                          shot_size=gen.get("shot_size") if gen.get("shot_size") in SHOT_SIZES else "medium shot",
                          camera=gen.get("camera") if gen.get("camera") in CAMERAS else "slow push in",
                          duration=round(max(2.5, len(shot.text.split()) / WORDS_PER_SECOND), 2),
                          cast="; ".join(f"{e['name']}: {' '.join(filter(None, [(e.get('training') or {}).get('trigger') if e.get('model') else None, e.get('description')]))}"
                                         for e in cast if e.get("description") or e.get("model")),
                          models=tuple(e["model"] for e in cast if e.get("model")),
                          model_urls=tuple((e.get("training") or {}).get("model_url") for e in cast if e.get("model") and (e.get("training") or {}).get("model_url")),
                          references=tuple(e["asset_id"] for e in cast if e.get("asset_id")))

    def _reference_paths(self, spec: PromptSpec) -> list[str]:
        paths = []
        for asset_id in spec.references:
            if self._assets.asset(asset_id):
                path = self._assets.path_of(self._assets.original(asset_id))
                if path.is_file():
                    paths.append(str(path))
        return paths

    def vary(self, shot_id: str) -> int:
        """Ask for a different picture of the same thing: the next run makes this shot's still again with a new seed."""
        attempt = int(self._projects.shot(shot_id).gen.get("attempt", 0)) + 1
        self._projects.annotate_shot(shot_id, gen={"attempt": attempt})
        return attempt

    def _look(self, path: Path, spec: PromptSpec, attempt_id: str) -> dict | None:
        """What the vision model makes of a still: a mark out of 10 and the defects it sees. None when no model can look."""
        if not self._judge:
            return None
        try:
            out = self._adapters.submit("model", Request("describe", inputs={"images": [str(path)]}, attempt_id=attempt_id,
                                                        params={"prompt": QUALITY_PROMPT.format(subject=spec.subject), "task": "quality", "max_tokens": 200})).outputs["json"]
            score = max(0, min(10, int(float(out["diem"]))))
        except (AdapterError, KeyError, TypeError, ValueError):
            return None                                   # a judge that cannot answer must not hold the picture back
        return {"score": score, "issues": [str(i) for i in out.get("loi") or [] if str(i).strip()][:5]}

    def _keyframes(self, ctx):
        # A generation request carries a prompt written for it and stills generated for it, never the operator's footage,
        # so it may go to a cloud provider.
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        made = repaired = 0
        for shot in script["shots"]:
            spec = self.spec_for(shot, project)
            prompt, turn = compile_prompt(spec, kind="image"), int(shot.gen.get("attempt", 0))
            seeds = [seed_for(shot.shot_id, turn * 10 + repair) for repair in range(MAX_REPAIRS + 1)]
            latest = (self._projects.generations(shot.shot_id, kind="keyframe") or [None])[-1]
            if latest and latest["prompt"] == prompt and latest["seed"] in seeds:
                continue                                                # the still asked for exists: an approved still is never regenerated silently
            tries = []
            for repair, seed in enumerate(seeds):
                out = self._media / (f"{shot.shot_id}_key.png" if not turn and not repair else f"{shot.shot_id}_key_{turn}_{repair}.png")
                result, provider = self._submit("image_gen", shot.gen.get("provider_image"), Request(
                    "generate", inputs={"prompt": prompt, "references": self._reference_paths(spec), "models": [m for m in spec.models if Path(m).is_file()], "model_urls": list(spec.model_urls)}, params={"out": str(out), "seed": seed, "aspect": spec.aspect},
                    attempt_id=ctx.claim.attempt_id, privacy_class=PrivacyClass.CLOUD_ALLOWED))
                if result.usage.cost:
                    ctx.record_cost(provider=provider, units=result.usage.units, cost=result.usage.cost)
                quality = self._look(out, spec, ctx.claim.attempt_id)
                tries.append({"out": out, "seed": seed, "provider": result.outputs.get("provider", provider), "model": result.outputs.get("model"), "quality": quality})
                ctx.heartbeat()
                if quality is None or quality["score"] >= QUALITY_PASS:
                    break
            best = max(tries, key=lambda t: (t["quality"] or {"score": 10})["score"])
            for t in sorted(tries, key=lambda t: t is best):            # the chosen still is recorded last, so it is the current one
                asset_id, _ = self._assets.create_asset(t["out"], kind="image", origin="generated", privacy_class="cloud_allowed")
                self._projects.add_generation(shot.shot_id, kind="keyframe" if t is best else "keyframe_try", spec=asdict(spec), prompt=prompt, compiler_version=COMPILER_VERSION,
                                              provider=t["provider"], model=t["model"], seed=t["seed"], asset_id=asset_id,
                                              quality={**t["quality"], "tries": len(tries)} if t["quality"] else None)
            made += 1
            repaired += len(tries) - 1
        return {"keyframes": made, "repairs": repaired}

    def _clips(self, ctx):
        script = self._projects.script(ctx.subject_ref)
        known = {f.name for f in fields(PromptSpec)}
        made = 0
        for shot in script["shots"]:
            key = self._projects.generations(shot.shot_id, kind="keyframe")[-1]
            spec = PromptSpec(**{k: v for k, v in key["spec"].items() if k in known})
            still = self._assets.path_of(self._assets.original(key["asset_id"]))
            lengths = split_duration(spec.duration, self._limit)            # no request exceeds the provider's clip limit
            prompt, seed = compile_prompt(spec, kind="video"), key["seed"]
            latest = (self._projects.generations(shot.shot_id, kind="clip") or [None])[-1]
            if latest and latest["prompt"] == prompt and latest["seed"] == seed and \
                    self._assets.original(latest["asset_id"]).metadata.get("first_frame_asset") == key["asset_id"]:
                continue                                                # this clip was already made from this still
            out = self._media / f"{shot.shot_id}_clip_{seed}.mp4"
            result, provider = self._submit("video_gen", shot.gen.get("provider_video"), Request(
                "generate", inputs={"prompt": prompt, "first_frame": str(still), "references": self._reference_paths(spec)},
                params={"out": str(out), "seed": seed, "duration": sum(lengths), "segments": lengths, "aspect": spec.aspect, "camera": spec.camera},
                attempt_id=ctx.claim.attempt_id, privacy_class=PrivacyClass.CLOUD_ALLOWED))
            asset_id, version_id = self._assets.create_asset(out, kind="video", origin="generated", privacy_class="cloud_allowed")
            self._assets.update_metadata(version_id, probe={"duration": sum(lengths)}, usable_ranges=[[0.0, sum(lengths)]], first_frame_asset=key["asset_id"])
            self._projects.add_generation(shot.shot_id, kind="clip", spec=asdict(spec), prompt=prompt, compiler_version=COMPILER_VERSION,
                                          provider=result.outputs.get("provider", provider), model=result.outputs.get("model"), seed=seed, asset_id=asset_id)
            self._projects.set_selection(shot.shot_id, status="proposed", asset_id=asset_id, t_in=0.0, t_out=sum(lengths), score=None,
                                         reason="Clip sinh bằng AI từ ảnh đã duyệt.")
            if result.usage.cost:
                ctx.record_cost(provider=provider, units=result.usage.units, cost=result.usage.cost)
            made += 1
            ctx.heartbeat()
        return {"clips": made}

    def approve(self, run_id: str) -> None:
        """Approve whichever gate of the run is waiting. Approving the clips makes the script ready to render."""
        stage = next(s for s in self._orch.stages(run_id) if s.status.value == "waiting_review")
        self._orch.decide_review(stage.stage_id, approve=True)
        if stage.stage_key == "clips":
            script_id = self._orch.run_info(run_id)["subject_ref"]
            for sel in self._projects.selections(script_id):
                self._projects.set_selection(sel.shot_id, status="accepted", asset_id=sel.asset_id, t_in=sel.t_in, t_out=sel.t_out, reason=sel.reason, decided_by="operator")
            self._projects.set_match_approved(script_id, True)
