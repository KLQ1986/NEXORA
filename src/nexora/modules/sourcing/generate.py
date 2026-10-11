"""Sourcing by generation: AI-generated shots, keyframe first (design v4.0, sections 18.4-18.6).

A still is generated and approved for every shot before any video is paid for. The approved still is
the first frame of the clip. Prompts are compiled deterministically from a structured description,
and every generation is recorded with its prompt and seed so that it can be reproduced or varied.
"""
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.projects import ProjectStore

GENERATE = PipelineDefinition("sourcing.generate", "1", [
    StageDef("keyframes", costly=True, gate=True),                       # stills first: cheap to produce, cheap to correct
    StageDef("clips", depends_on=("keyframes",), costly=True, gate=True),
])
COMPILER_VERSION = "1"
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


def compile_prompt(spec: PromptSpec, *, kind: str) -> str:
    """The same spec always gives the same prompt."""
    parts = [spec.subject.strip().rstrip("."), spec.shot_size]
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
                 *, max_clip_seconds: float = 8.0):
        self._orch, self._projects, self._assets, self._adapters = orch, projects, assets, adapters
        self._media, self._limit = Path(media_dir) / "generated", max_clip_seconds
        self._media.mkdir(parents=True, exist_ok=True)

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(GENERATE, {"keyframes": self._keyframes, "clips": self._clips})

    def available(self) -> dict:
        names = {c.name for c in self._adapters.describe()}
        return {"image": "image_gen" in names, "video": "video_gen" in names}

    def start(self, script_id: str) -> str:
        self._projects.set_match_approved(script_id, False)
        return self._orch.submit_run(GENERATE, subject_ref=script_id)

    def spec_for(self, shot, project: dict) -> PromptSpec:
        return PromptSpec(subject=shot.text, style=project.get("style") or "", aspect=ASPECT.get(project["format"], "16:9"),
                          duration=round(max(2.5, len(shot.text.split()) / WORDS_PER_SECOND), 2))

    def _require(self, name: str) -> None:
        if name not in {c.name for c in self._adapters.describe()}:
            # No provider is configured: only the operator can fix that, so the stage waits instead of failing.
            raise AdapterError(ErrorCode.AUTH, f"no {name} provider is configured")

    def _keyframes(self, ctx):
        # A generation request carries a prompt written for it and stills generated for it, never the operator's footage,
        # so it may go to a cloud provider.
        self._require("image_gen")
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        made = 0
        for shot in script["shots"]:
            if self._projects.generations(shot.shot_id, kind="keyframe"):
                continue                                                # already generated: an approved still is never regenerated silently
            spec = self.spec_for(shot, project)
            prompt, seed = compile_prompt(spec, kind="image"), seed_for(shot.shot_id, 0)
            out = self._media / f"{shot.shot_id}_key.png"
            result = self._adapters.submit("image_gen", Request("generate", inputs={"prompt": prompt}, params={"out": str(out), "seed": seed, "aspect": spec.aspect},
                                                               attempt_id=ctx.claim.attempt_id, privacy_class=PrivacyClass.CLOUD_ALLOWED))
            asset_id, _ = self._assets.create_asset(out, kind="image", origin="generated", privacy_class="cloud_allowed")
            self._projects.add_generation(shot.shot_id, kind="keyframe", spec=asdict(spec), prompt=prompt, compiler_version=COMPILER_VERSION,
                                          provider=result.outputs.get("provider", "image_gen"), model=result.outputs.get("model"), seed=seed, asset_id=asset_id)
            if result.usage.cost:
                ctx.record_cost(provider="image_gen", units=result.usage.units, cost=result.usage.cost)
            made += 1
            ctx.heartbeat()
        return {"keyframes": made}

    def _clips(self, ctx):
        self._require("video_gen")
        script = self._projects.script(ctx.subject_ref)
        made = 0
        for shot in script["shots"]:
            key = self._projects.generations(shot.shot_id, kind="keyframe")[-1]
            spec = PromptSpec(**key["spec"])
            still = self._assets.path_of(self._assets.original(key["asset_id"]))
            lengths = split_duration(spec.duration, self._limit)            # no request exceeds the provider's clip limit
            prompt, seed = compile_prompt(spec, kind="video"), seed_for(shot.shot_id, 0)
            out = self._media / f"{shot.shot_id}_clip.mp4"
            result = self._adapters.submit("video_gen", Request("generate", inputs={"prompt": prompt, "first_frame": str(still)},
                                                               params={"out": str(out), "seed": seed, "duration": sum(lengths), "segments": lengths, "aspect": spec.aspect},
                                                               attempt_id=ctx.claim.attempt_id, privacy_class=PrivacyClass.CLOUD_ALLOWED))
            asset_id, version_id = self._assets.create_asset(out, kind="video", origin="generated", privacy_class="cloud_allowed")
            self._assets.update_metadata(version_id, probe={"duration": sum(lengths)}, usable_ranges=[[0.0, sum(lengths)]], first_frame_asset=key["asset_id"])
            self._projects.add_generation(shot.shot_id, kind="clip", spec=asdict(spec), prompt=prompt, compiler_version=COMPILER_VERSION,
                                          provider=result.outputs.get("provider", "video_gen"), model=result.outputs.get("model"), seed=seed, asset_id=asset_id)
            self._projects.set_selection(shot.shot_id, status="proposed", asset_id=asset_id, t_in=0.0, t_out=sum(lengths), score=None,
                                         reason="Clip sinh bằng AI từ ảnh đã duyệt.")
            if result.usage.cost:
                ctx.record_cost(provider="video_gen", units=result.usage.units, cost=result.usage.cost)
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
