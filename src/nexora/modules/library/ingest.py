"""Ingest: bring a video file into the Library (design v4.0, sections 15.1 and 17.1).

The original is never modified. Everything derived from it — proxy, thumbnail, measurements — is a
new asset version or metadata on the original version.
"""
import shutil
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, Request
from nexora.core.assets import AssetStore, sha256_file
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef

INGEST = PipelineDefinition("library.ingest", "1", [
    StageDef("checksum"),
    StageDef("probe", depends_on=("checksum",)),
    StageDef("usable", depends_on=("probe",)),
    StageDef("proxy", depends_on=("usable",)),
    StageDef("thumbnail", depends_on=("usable",)),
])

MIN_USABLE_SECONDS = 0.1


def usable_ranges(duration: float, black: list[list[float]]) -> list[list[float]]:
    """The parts of [0, duration] that are not black."""
    out, cursor = [], 0.0
    for start, end in sorted(black):
        if start - cursor >= MIN_USABLE_SECONDS:
            out.append([round(cursor, 3), round(start, 3)])
        cursor = max(cursor, end)
    if duration - cursor >= MIN_USABLE_SECONDS:
        out.append([round(cursor, 3), round(duration, 3)])
    return out


class Library:
    def __init__(self, orch: Orchestrator, assets: AssetStore, adapters: AdapterRegistry, media_dir: str | Path,
                 *, min_free_bytes: int = 2 * 1024**3):
        self._orch, self._assets, self._adapters = orch, assets, adapters
        self._min_free = min_free_bytes
        self._media = Path(media_dir)
        self._media.mkdir(parents=True, exist_ok=True)
        assets.add_volume("managed", self._media, kind="internal")

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(INGEST, {"checksum": self._checksum, "probe": self._probe, "usable": self._usable,
                                   "proxy": self._proxy, "thumbnail": self._thumbnail})

    def ingest(self, path: str | Path) -> tuple[str, str]:
        """Register a file and start its ingest run. Ingesting the same file again returns the same asset and run."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        asset_id, _ = self._assets.create_asset(path, kind="video", origin="self_shot")
        run_id = self._orch.submit_run(INGEST, subject_ref=asset_id, idempotency_key=f"ingest:{asset_id}")
        return asset_id, run_id

    # ------------------------------------------------------------------ stage handlers
    def _source(self, ctx):
        original = self._assets.original(ctx.subject_ref)
        path = self._assets.path_of(original)
        if not path.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{path} is not available")
        return original, path

    def _is_duplicate(self, ctx) -> bool:
        return "duplicate_of" in self._assets.original(ctx.subject_ref).metadata

    def _derived_path(self, original, suffix: str) -> Path:
        folder = self._media / original.checksum[:2]
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{original.checksum}{suffix}"

    def _checksum(self, ctx):
        original, path = self._source(ctx)
        checksum = sha256_file(path)
        self._assets.set_checksum(original.version_id, checksum)
        duplicate_of = self._assets.find_original_by_checksum(checksum, exclude_asset=ctx.subject_ref)
        if duplicate_of:
            self._assets.update_metadata(original.version_id, duplicate_of=duplicate_of)
        return {"checksum": checksum, "duplicate_of": duplicate_of}

    def _probe(self, ctx):
        if self._is_duplicate(ctx):
            return {"skipped": "duplicate"}
        original, path = self._source(ctx)
        info = self._adapters.submit("ffprobe", Request("probe", inputs={"path": str(path)}, attempt_id=ctx.claim.attempt_id)).outputs
        self._assets.update_metadata(original.version_id, probe=info)
        return info

    def _usable(self, ctx):
        if self._is_duplicate(ctx):
            return {"skipped": "duplicate"}
        original, path = self._source(ctx)
        black = self._adapters.submit("ffmpeg", Request("blackdetect", inputs={"path": str(path)}, attempt_id=ctx.claim.attempt_id)).outputs["black_ranges"]
        duration = ctx.inputs["probe"]["duration"]
        frozen = self._adapters.submit("ffmpeg", Request("freezedetect", inputs={"path": str(path)}, attempt_id=ctx.claim.attempt_id)).outputs["frozen_ranges"]
        frozen = [[a, duration if b is None else b] for a, b in frozen]
        ranges = usable_ranges(duration, black)          # a frozen picture is recorded, not excluded: a still shot can be wanted
        self._assets.update_metadata(original.version_id, black_ranges=black, frozen_ranges=frozen, usable_ranges=ranges)
        return {"black_ranges": black, "frozen_ranges": frozen, "usable_ranges": ranges}

    def _proxy(self, ctx):
        if self._is_duplicate(ctx):
            return {"skipped": "duplicate"}
        original, path = self._source(ctx)
        if shutil.disk_usage(self._media).free < self._min_free:
            raise AdapterError(ErrorCode.INSUFFICIENT_STORAGE, f"less than {self._min_free} bytes free for derived media")
        out = self._derived_path(original, "_proxy.mp4")
        self._adapters.submit("ffmpeg", Request("proxy", inputs={"path": str(path)}, params={"out": str(out), "max_height": 720},
                                               attempt_id=ctx.claim.attempt_id))
        version_id = self._assets.add_version(ctx.subject_ref, out, role="proxy", parents=[original.version_id],
                                              attempt_id=ctx.claim.attempt_id, metadata={"max_height": 720})
        return {"proxy_version_id": version_id}

    def _thumbnail(self, ctx):
        if self._is_duplicate(ctx):
            return {"skipped": "duplicate"}
        original, path = self._source(ctx)
        ranges = ctx.inputs["usable"]["usable_ranges"]
        if not ranges:
            return {"skipped": "no usable picture"}
        start, end = ranges[0]
        out = self._derived_path(original, "_thumb.jpg")
        self._adapters.submit("ffmpeg", Request("thumbnail", inputs={"path": str(path)},
                                               params={"out": str(out), "at": round(start + (end - start) * 0.1, 3)},
                                               attempt_id=ctx.claim.attempt_id))
        version_id = self._assets.add_version(ctx.subject_ref, out, role="thumbnail", parents=[original.version_id],
                                              attempt_id=ctx.claim.attempt_id)
        return {"thumbnail_version_id": version_id}
