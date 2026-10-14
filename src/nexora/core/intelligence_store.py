"""The writing side of the Video Intelligence canonical model (see `nexora.core.intelligence`). Only the analysis domain may
import this module; the import contracts in pyproject.toml forbid it to every other domain."""
import json
import time
from pathlib import Path
from typing import Iterable

from nexora.core import db
from nexora.core.ids import new_id
from nexora.core.intelligence import SOURCES, Analyzer, ensure_schema


class IntelligenceStore:
    """Writes the canonical model. Used by the analysis domain only."""

    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        ensure_schema(db_path)

    @property
    def _conn(self):
        return self._db.get()

    def recording(self, asset_id: str, *, checksum: str | None = None, technical: dict | None = None, provenance: dict | None = None,
                  summary: dict | None = None) -> None:
        with db.write(self._conn) as c:
            row = c.execute("SELECT * FROM vi_recordings WHERE asset_id = ?", (asset_id,)).fetchone()
            merged = {k: ({**json.loads(row[k]), **(v or {})} if row else (v or {})) for k, v in (("technical", technical), ("provenance", provenance), ("summary", summary))}
            c.execute("INSERT INTO vi_recordings (asset_id, checksum, technical, provenance, summary, updated_at) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(asset_id) DO UPDATE SET checksum = COALESCE(excluded.checksum, vi_recordings.checksum), technical = excluded.technical, "
                      "provenance = excluded.provenance, summary = excluded.summary, updated_at = excluded.updated_at",
                      (asset_id, checksum, *(json.dumps(merged[k], ensure_ascii=False) for k in ("technical", "provenance", "summary")), time.time()))

    def replace_segments(self, asset_id: str, level: str, segments: Iterable[tuple[float, float, dict]], *, analyzer: str) -> int:
        """Put the segments of one level of a recording in place of the ones before."""
        rows = list(segments)
        with db.write(self._conn) as c:
            c.execute("DELETE FROM vi_segments WHERE asset_id = ? AND level = ?", (asset_id, level))
            for a, b, data in rows:
                c.execute("INSERT OR REPLACE INTO vi_segments (segment_id, asset_id, level, t_start, t_end, data, analyzer, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                          (new_id("seg"), asset_id, level, round(a, 3), round(b, 3), json.dumps(data, ensure_ascii=False), analyzer, time.time()))
        return len(rows)

    def observe(self, asset_id: str, t_start: float, t_end: float, field: str, value, *, source: str, confidence: str = "medium",
                evidence: dict | None = None, analyzer: str) -> None:
        self.observe_many(asset_id, [(t_start, t_end, field, value, source, confidence, evidence or {})], analyzer=analyzer)

    def observe_many(self, asset_id: str, rows: Iterable[tuple], *, analyzer: str, replace: tuple[str, ...] = ()) -> int:
        """Record observations (t_start, t_end, field, value, source, confidence, evidence). `replace`: fields whose earlier
        observations by this analyzer's source go first, so that a stretch a new division no longer has keeps nothing stale."""
        rows = list(rows)
        now = time.time()
        with db.write(self._conn) as c:
            for f in replace:
                sources = {r[4] for r in rows if r[2] == f} or {"measured", "recognized", "model"}
                for s in sources:
                    if s != "human":
                        c.execute("DELETE FROM vi_observations WHERE asset_id = ? AND field = ? AND source = ?", (asset_id, f, s))
            for a, b, f, value, source, confidence, evidence in rows:
                if source not in SOURCES:
                    raise ValueError(f"unknown source {source}")
                c.execute("INSERT INTO vi_observations (obs_id, asset_id, t_start, t_end, field, source, value, confidence, evidence, analyzer, at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                          "ON CONFLICT(asset_id, t_start, t_end, field, source) DO UPDATE SET value = excluded.value, confidence = excluded.confidence, "
                          "evidence = excluded.evidence, analyzer = excluded.analyzer, at = excluded.at",
                          (new_id("obs"), asset_id, round(a, 3), round(b, 3), f, source, json.dumps(value, ensure_ascii=False), confidence,
                           json.dumps(evidence or {}, ensure_ascii=False), analyzer, now))
        return len(rows)

    def entity(self, kind: str, key: str, *, name: str | None = None, data: dict | None = None,
               appearances: Iterable[tuple[str, float, float, dict]] = ()) -> str:
        with db.write(self._conn) as c:
            row = c.execute("SELECT entity_id, name FROM vi_entities WHERE kind = ? AND key = ?", (kind, key)).fetchone()
            entity_id = row[0] if row else new_id("ent")
            c.execute("INSERT INTO vi_entities (entity_id, kind, key, name, data, updated_at) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(kind, key) DO UPDATE SET name = COALESCE(excluded.name, vi_entities.name), data = excluded.data, updated_at = excluded.updated_at",
                      (entity_id, kind, key, name, json.dumps(data or {}, ensure_ascii=False), time.time()))
            c.execute("DELETE FROM vi_appearances WHERE entity_id = ?", (entity_id,))
            for asset_id, a, b, evidence in appearances:
                c.execute("INSERT OR REPLACE INTO vi_appearances (entity_id, asset_id, t_start, t_end, evidence) VALUES (?,?,?,?,?)",
                          (entity_id, asset_id, round(a, 3), round(b, 3), json.dumps(evidence, ensure_ascii=False)))
        return entity_id

    def drop_entities(self, kind: str, keep: set[str]) -> None:
        """Forget entities of a kind no longer found, unless the operator named them."""
        with db.write(self._conn) as c:
            for entity_id, key, name in c.execute("SELECT entity_id, key, name FROM vi_entities WHERE kind = ?", (kind,)).fetchall():
                if key not in keep and not name:
                    c.execute("DELETE FROM vi_appearances WHERE entity_id = ?", (entity_id,))
                    c.execute("DELETE FROM vi_entities WHERE entity_id = ?", (entity_id,))

    def artifact(self, asset_id: str, kind: str, path: str | Path, *, analyzer: str) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT OR REPLACE INTO vi_artifacts (asset_id, kind, path, analyzer, updated_at) VALUES (?,?,?,?,?)", (asset_id, kind, str(path), analyzer, time.time()))

    def declare(self, analyzer: Analyzer) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT OR REPLACE INTO vi_analyzers (name, version, needs, writes, updated_at) VALUES (?,?,?,?,?)",
                      (analyzer.name, analyzer.version, json.dumps(list(analyzer.needs)), json.dumps(list(analyzer.writes)), time.time()))

    def ran(self, asset_id: str, analyzer: Analyzer) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT OR REPLACE INTO vi_runs (asset_id, analyzer, version, at) VALUES (?,?,?,?)", (asset_id, analyzer.name, analyzer.version, time.time()))

    def forget(self, asset_id: str) -> int:
        """Everything known about a recording, gone with it."""
        with db.write(self._conn) as c:
            n = c.execute("DELETE FROM vi_observations WHERE asset_id = ?", (asset_id,)).rowcount
            for table in ("vi_segments", "vi_recordings", "vi_appearances", "vi_artifacts", "vi_runs"):
                c.execute(f"DELETE FROM {table} WHERE asset_id = ?", (asset_id,))
        return n
