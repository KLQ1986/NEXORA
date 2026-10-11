"""Composition root: builds the system from its parts. The only place that knows every layer."""
import os
from dataclasses import dataclass
from pathlib import Path

from nexora.adapters.media import FFmpegAdapter, FFprobeAdapter
from nexora.core.adapter import AdapterRegistry
from nexora.core.assets import AssetStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineRegistry
from nexora.core.worker import Worker
from nexora.modules.library.ingest import Library


@dataclass
class System:
    data_dir: Path
    orch: Orchestrator
    assets: AssetStore
    adapters: AdapterRegistry
    registry: PipelineRegistry
    worker: Worker
    library: Library


def build(data_dir: str | Path) -> System:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "nexora.db"
    orch, assets = Orchestrator(db_path), AssetStore(db_path)
    adapters = AdapterRegistry()
    adapters.register(FFprobeAdapter())
    adapters.register(FFmpegAdapter())
    registry = PipelineRegistry()
    library = Library(orch, assets, adapters, data_dir / "media")
    library.register(registry)
    worker = Worker(orch, registry, worker_id=f"worker-{os.getpid()}")
    return System(data_dir, orch, assets, adapters, registry, worker, library)
