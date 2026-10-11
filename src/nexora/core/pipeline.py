"""Pipeline definitions: a pipeline is data, declared by a domain module and run by the core."""
from dataclasses import dataclass, field
from typing import Callable

from nexora.core.states import EffectClass


@dataclass(frozen=True)
class StageDef:
    key: str
    depends_on: tuple[str, ...] = ()
    effect_class: EffectClass = EffectClass.PURE
    costly: bool = False          # spends money; subject to the kill switch and budget guard
    gate: bool = False            # needs a human review before it counts as succeeded
    max_attempts: int = 3
    timeout_seconds: float = 3600.0


@dataclass(frozen=True)
class PipelineDefinition:
    pipeline_id: str
    version: str
    stages: list[StageDef] = field(default_factory=list)

    def __post_init__(self):
        seen: set[str] = set()
        for stage in self.stages:
            if stage.key in seen:
                raise ValueError(f"duplicate stage key: {stage.key}")
            missing = [d for d in stage.depends_on if d not in seen]
            if missing:
                raise ValueError(f"stage {stage.key} depends on stages not declared before it: {missing}")
            seen.add(stage.key)


class PipelineRegistry:
    """Pipelines and the handlers of their stages, as registered by the domain modules."""

    def __init__(self):
        self._pipelines: dict[str, tuple[PipelineDefinition, dict[str, Callable]]] = {}
        self._on_success: dict[str, Callable] = {}

    def register(self, pipeline: PipelineDefinition, handlers: dict[str, Callable], *, on_success: Callable | None = None) -> None:
        """`on_success(run_id, subject_ref)` is called once a run of this pipeline has succeeded; it may start the next one."""
        missing = [s.key for s in pipeline.stages if s.key not in handlers]
        if missing:
            raise ValueError(f"pipeline {pipeline.pipeline_id} has stages without a handler: {missing}")
        self._pipelines[pipeline.pipeline_id] = (pipeline, dict(handlers))
        if on_success:
            self._on_success[pipeline.pipeline_id] = on_success

    def on_success(self, pipeline_id: str) -> Callable | None:
        return self._on_success.get(pipeline_id)

    def definition(self, pipeline_id: str) -> PipelineDefinition:
        return self._pipelines[pipeline_id][0]

    def handler(self, pipeline_id: str, stage_key: str) -> Callable:
        return self._pipelines[pipeline_id][1][stage_key]
