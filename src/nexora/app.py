"""Composition root: builds the system from its parts. The only place that knows every layer."""
import os
from dataclasses import dataclass
from pathlib import Path

from nexora.adapters.media import FFmpegAdapter, FFprobeAdapter
from nexora.core.adapter import AdapterRegistry
from nexora.core.adapter import Adapter, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineRegistry
from nexora.core.worker import Worker
from nexora.modules.library.ingest import Library
from nexora.modules.library.understand import Understanding


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


def build(data_dir: str | Path, *, min_free_bytes: int = 2 * 1024**3, model: Adapter | None = None,
          segment_seconds: float = 12.0) -> System:
    """`model` is the adapter for vision, reasoning and embeddings; without one, footage is ingested but not understood."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "nexora.db"
    orch, assets = Orchestrator(db_path), AssetStore(db_path)
    adapters = AdapterRegistry()
    adapters.register(FFprobeAdapter())
    adapters.register(FFmpegAdapter())
    index = MomentIndex(db_path)
    understanding = None
    if model is not None:
        adapters.register(model)
        index.embed = lambda texts: adapters.submit("model", Request("embed", inputs={"texts": texts})).outputs["vectors"]
        understanding = Understanding(assets, index, adapters, data_dir / "media", segment_seconds=segment_seconds)
    registry = PipelineRegistry()
    library = Library(orch, assets, adapters, data_dir / "media", min_free_bytes=min_free_bytes, understanding=understanding)
    library.register(registry)
    worker = Worker(orch, registry, worker_id=f"worker-{os.getpid()}")
    return System(data_dir, orch, assets, adapters, registry, worker, library, index)
