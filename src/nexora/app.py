"""Composition root: builds the system from its parts. The only place that knows every layer."""
import os
from dataclasses import dataclass
from pathlib import Path

from nexora.adapters.graphics import CaptionAdapter
from nexora.adapters.media import FFmpegAdapter, FFprobeAdapter
from nexora.core.adapter import AdapterRegistry
from nexora.core.adapter import Adapter, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineRegistry
from nexora.core.projects import ProjectStore
from nexora.core.worker import Worker
from nexora.modules.library.ingest import Library
from nexora.modules.distribution.package import Distribution
from nexora.modules.edit.render import Edit
from nexora.modules.library.understand import Understanding
from nexora.modules.planning.scripts import Planning
from nexora.modules.quality.review import review_cut
from nexora.modules.sourcing.generate import Generation
from nexora.modules.sourcing.match import Sourcing


@dataclass
class System:
    data_dir: Path
    orch: Orchestrator
    assets: AssetStore
    adapters: AdapterRegistry
    registry: PipelineRegistry
    worker: Worker
    library: Library
    index: MomentIndex
    projects: ProjectStore
    planning: Planning
    sourcing: Sourcing
    edit: Edit
    distribution: Distribution
    generation: Generation


def fill_gap_from_stock(system: "System", shot_id: str, query: str) -> dict:
    """Resolve a gap with licensed stock: search, bring the clip into the Library like any footage, and propose it for the shot.
    Only the query text leaves the machine. Lives here because it joins two modules that may not import each other."""
    out_dir = system.data_dir / "media" / "stock"
    result = system.adapters.submit("stock", Request("search", inputs={"queries": [query]}, params={"out_dir": str(out_dir), "clips_per_query": 1},
                                                    privacy_class=PrivacyClass.CLOUD_ALLOWED))
    if not result.files:
        return {"found": False}
    clip = result.outputs["clips"][0]
    rights = {"source": clip.get("source"), "source_url": clip.get("source_url"), "license": clip.get("license"), "creator": clip.get("creator"), "query": query}
    asset_id, run_id = system.library.ingest(result.files[0], origin="licensed", rights=rights)
    system.sourcing.use_asset(shot_id, asset_id, reason=f"Clip stock từ {clip.get('source')}. Giấy phép: {clip.get('license')}. Nguồn: {clip.get('source_url')}")
    return {"found": True, "asset_id": asset_id, "run_id": run_id, "rights": rights}


def build(data_dir: str | Path, *, min_free_bytes: int = 2 * 1024**3, model: Adapter | None = None,
          segment_seconds: float = 12.0, voice: Adapter | None = None, match_threshold: float = 0.5, judge: bool = True,
          generators: list[Adapter] | None = None, stock: Adapter | None = None) -> System:
    """`model` is the adapter for vision, reasoning and embeddings; without one, footage is ingested but not understood."""
    data_dir = Path(data_dir).resolve()          # tools resolve relative paths differently; keep every path absolute
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "nexora.db"
    orch, assets = Orchestrator(db_path), AssetStore(db_path)
    adapters = AdapterRegistry()
    adapters.register(FFprobeAdapter())
    adapters.register(FFmpegAdapter())
    adapters.register(CaptionAdapter())
    if voice is not None:
        adapters.register(voice)
    index = MomentIndex(db_path)
    understanding = None
    if model is not None:
        adapters.register(model)
        index.embed = lambda texts: adapters.submit("model", Request("embed", inputs={"texts": texts})).outputs["vectors"]
        understanding = Understanding(assets, index, adapters, data_dir / "media", segment_seconds=segment_seconds)
    registry = PipelineRegistry()
    library = Library(orch, assets, adapters, data_dir / "media", min_free_bytes=min_free_bytes, understanding=understanding)
    library.register(registry)
    projects = ProjectStore(db_path)
    planning = Planning(projects, assets, index, adapters)
    sourcing = Sourcing(orch, projects, index, threshold=match_threshold, adapters=adapters, judge=judge and model is not None)
    sourcing.register(registry)
    edit = Edit(orch, projects, assets, adapters, data_dir / "media", voice=voice is not None, reviewer=review_cut)
    edit.register(registry)
    if stock is not None:
        adapters.register(stock)
    for generator in generators or []:
        adapters.register(generator)
    generation = Generation(orch, projects, assets, adapters, data_dir / "media")
    generation.register(registry)
    distribution = Distribution(projects, assets, adapters, data_dir / "exports")
    worker = Worker(orch, registry, worker_id=f"worker-{os.getpid()}")
    return System(data_dir, orch, assets, adapters, registry, worker, library, index, projects, planning, sourcing, edit, distribution, generation)
