"""Slice 1 exit criteria: a two-step pipeline runs through the worker and calls FFprobe on a real
file; a worker that dies mid-run is recovered and finished stages are not run again."""
import subprocess

from nexora.adapters.media import FFprobeAdapter
from nexora.core.adapter import AdapterRegistry, Request
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.states import RunStatus
from nexora.core.worker import Worker

T0 = 3_000_000.0
PIPE = PipelineDefinition("probe-demo", "1", [StageDef("probe"), StageDef("summarise", depends_on=("probe",))])


def test_pipeline_probes_a_real_file_and_survives_a_dead_worker(tmp_path):
    video = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    adapters = AdapterRegistry()
    adapters.register(FFprobeAdapter())
    calls = {"probe": 0, "summarise": 0}

    def probe(ctx):
        calls["probe"] += 1
        return adapters.submit("ffprobe", Request("probe", inputs={"path": str(video)})).outputs

    def summarise(ctx):
        calls["summarise"] += 1
        return {"text": f'{ctx.inputs["probe"]["width"]}x{ctx.inputs["probe"]["height"]}'}

    registry = PipelineRegistry()
    registry.register(PIPE, {"probe": probe, "summarise": summarise})
    db_path = tmp_path / "nexora.db"

    first = Worker(Orchestrator(db_path), registry, worker_id="w1")
    run = Orchestrator(db_path).submit_run(PIPE, now=T0)
    assert first.run_once(now=T0)                                   # probe succeeds
    Orchestrator(db_path).claim_next("w1", now=T0 + 1)              # w1 claims summarise, then dies

    orch = Orchestrator(db_path)                                    # a fresh process
    second = Worker(orch, registry, worker_id="w2")
    second.recover(now=T0 + 10)
    assert second.run_once(now=T0 + 4000)                           # after the backoff
    assert orch.run_status(run) is RunStatus.SUCCEEDED
    assert calls == {"probe": 1, "summarise": 1}                    # the finished stage was not run again
    assert next(s for s in orch.stages(run) if s.stage_key == "summarise").outputs == {"text": "320x180"}
