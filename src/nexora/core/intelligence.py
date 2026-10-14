"""Video Intelligence: the canonical model of what is known about a recording (design 2026-10-15).

A recording is analysed once. Everything learnt from it is kept here, in one shape, versioned by the analyzer that produced
it, so that every task that needs it (finding footage, matching a script, picking highlights, cutting short clips, learning
a style, studying another channel's videos, reports, agents) reads it instead of analysing again. Editors are readers like
any other; nothing here knows which editor is in use.

The model:

- **Recording**: one file, by asset; its technical description, provenance and rights.
- **Segment**: a stretch of a recording at a level: shot, beat, scene, event, span (a line of text on screen, a sound),
  sentence.
- **Observation**: one value of one field over one stretch, from one source: `measured` (computed from the signal),
  `recognized` (a dedicated recogniser), `model` (a vision or language model), `human` (the operator). It carries a
  confidence, the evidence it rests on, the analyzer and version that made it, and when.
- **Entity** and **Appearance**: a person, place or thing, and where it is seen.
- **Artifact**: a file derived from a recording (frames, measures, prints), by content.
- **Analyzer**: a declared producer of observations, with its version, what it needs and what it writes.

Several sources may observe the same field. `VideoIntelligence.value` fuses them by one rule: what the operator said, else
the most trusted source whose field has passed its accuracy gate (measured or recognised before a model), else the most
trusted source at all, marked as not released. Which fields have passed is told by the quality domain (`released`).

Only the analysis domain (`nexora.modules.intelligence`) writes, through `nexora.core.intelligence_store.IntelligenceStore`;
every other module reads through `VideoIntelligence`. The import contracts in pyproject.toml hold this.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from nexora.core import db
from nexora.core.ids import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS vi_recordings (asset_id TEXT PRIMARY KEY, checksum TEXT, technical TEXT NOT NULL DEFAULT '{}', provenance TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS vi_segments (segment_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, level TEXT NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL,
    data TEXT NOT NULL DEFAULT '{}', analyzer TEXT, updated_at REAL NOT NULL, UNIQUE (asset_id, level, t_start, t_end));
CREATE INDEX IF NOT EXISTS vi_segments_by_asset ON vi_segments(asset_id, level, t_start);
CREATE TABLE IF NOT EXISTS vi_observations (obs_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL, field TEXT NOT NULL,
    source TEXT NOT NULL, value TEXT NOT NULL, confidence TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '{}', analyzer TEXT NOT NULL, at REAL NOT NULL,
    UNIQUE (asset_id, t_start, t_end, field, source));
CREATE INDEX IF NOT EXISTS vi_observations_by_field ON vi_observations(asset_id, field, t_start);
CREATE TABLE IF NOT EXISTS vi_entities (entity_id TEXT PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL, name TEXT, data TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL, UNIQUE (kind, key));
CREATE TABLE IF NOT EXISTS vi_appearances (entity_id TEXT NOT NULL, asset_id TEXT NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (entity_id, asset_id, t_start));
CREATE TABLE IF NOT EXISTS vi_artifacts (asset_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, analyzer TEXT NOT NULL, updated_at REAL NOT NULL,
    PRIMARY KEY (asset_id, kind));
CREATE TABLE IF NOT EXISTS vi_analyzers (name TEXT PRIMARY KEY, version TEXT NOT NULL, needs TEXT NOT NULL, writes TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS vi_runs (asset_id TEXT NOT NULL, analyzer TEXT NOT NULL, version TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (asset_id, analyzer));
"""
SOURCES = ("human", "measured", "recognized", "model")          # most trusted first
LEVELS = ("shot", "beat", "scene", "event", "span", "sentence")


@dataclass(frozen=True)
class Observation:
    asset_id: str
    t_start: float
    t_end: float
    field: str
    source: str
    value: object
    confidence: str
    evidence: dict
    analyzer: str
    at: float


@dataclass(frozen=True)
class Value:
    """A field's value over a stretch after fusion: what to use, where it came from, and whether it may be relied on."""
    field: str
    value: object
    source: str
    confidence: str
    released: bool
    evidence: dict
    analyzer: str
    others: tuple = ()                       # the other sources' observations of the same field there


@dataclass(frozen=True)
class Segment:
    asset_id: str
    level: str
    t_start: float
    t_end: float
    data: dict
    analyzer: str | None


@dataclass(frozen=True)
class Analyzer:
    """A declared producer of observations: run again for a recording when its version changes or what it needs does."""
    name: str
    version: str
    needs: tuple[str, ...] = ()              # other analyzers, or "file", "frames", "sound"
    writes: tuple[str, ...] = ()             # fields and segment levels


def gate_key(field: str, source: str) -> str:
    """The name a field's accuracy gate goes by: the field itself for what is measured or recognised, `model.<field>` for a model's."""
    return f"model.{field}" if source == "model" else field


def ensure_schema(db_path: str | Path) -> None:
    conn = db.LocalConnections(db_path).get()
    with db.write(conn) as c:
        for statement in SCHEMA.strip().split(";\n"):
            if statement.strip():
                c.execute(statement)


class VideoIntelligence:
    """Reads the canonical model. What every module uses: search, matching, editing, reports, agents, new tasks."""

    def __init__(self, db_path: str | Path, *, released: Callable[[], set[str]] = lambda: set(), exists: Callable[[str], bool] = lambda asset_id: True,
                 search: Callable | None = None, alike: Callable | None = None):
        self._db = db.LocalConnections(db_path)
        ensure_schema(db_path)                                         # the tables exist before anyone reads them
        self._released, self._exists = released, exists
        self._search, self._alike = search, alike

    @property
    def _conn(self):
        return self._db.get()

    # ---------------------------------------------------------------------------------------------------- recordings
    def recording(self, asset_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM vi_recordings WHERE asset_id = ?", (asset_id,)).fetchone()
        if row is None or not self._exists(asset_id):
            return None
        return {"asset_id": asset_id, "checksum": row["checksum"], "technical": json.loads(row["technical"]), "provenance": json.loads(row["provenance"]),
                "summary": json.loads(row["summary"]), "updated_at": row["updated_at"]}

    def recordings(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT asset_id FROM vi_recordings ORDER BY asset_id") if self._exists(r[0])]

    def analysed(self, asset_id: str) -> dict[str, str]:
        """Which analyzers have run on a recording, and at which version."""
        return {r["analyzer"]: r["version"] for r in self._conn.execute("SELECT analyzer, version FROM vi_runs WHERE asset_id = ?", (asset_id,))}

    def stale(self, asset_id: str) -> list[str]:
        """Analyzers whose declared version is newer than the one that last ran on this recording, and those that need them."""
        declared = {r["name"]: (r["version"], json.loads(r["needs"])) for r in self._conn.execute("SELECT * FROM vi_analyzers")}
        done = self.analysed(asset_id)
        out = [name for name, (version, _) in declared.items() if done.get(name) != version]
        changed = True
        while changed:
            changed = False
            for name, (_, needs) in declared.items():
                if name not in out and any(n in out for n in needs):
                    out.append(name); changed = True
        return sorted(out)

    # ------------------------------------------------------------------------------------------------------ segments
    def segments(self, asset_id: str, level: str = "beat", between: tuple[float, float] | None = None) -> list[Segment]:
        if not self._exists(asset_id):
            return []
        q, args = "SELECT * FROM vi_segments WHERE asset_id = ? AND level = ?", [asset_id, level]
        if between:
            q += " AND t_end > ? AND t_start < ?"
            args += [between[0], between[1]]
        return [Segment(r["asset_id"], r["level"], r["t_start"], r["t_end"], json.loads(r["data"]), r["analyzer"])
                for r in self._conn.execute(q + " ORDER BY t_start", args)]

    # -------------------------------------------------------------------------------------------------- observations
    def observations(self, asset_id: str, field: str | None = None, between: tuple[float, float] | None = None) -> list[Observation]:
        if not self._exists(asset_id):
            return []
        q, args = "SELECT * FROM vi_observations WHERE asset_id = ?", [asset_id]
        if field:
            q += " AND field = ?"; args.append(field)
        if between:
            q += " AND t_end > ? AND t_start < ?"; args += [between[0], between[1]]
        return [Observation(r["asset_id"], r["t_start"], r["t_end"], r["field"], r["source"], json.loads(r["value"]), r["confidence"],
                            json.loads(r["evidence"]), r["analyzer"], r["at"]) for r in self._conn.execute(q + " ORDER BY t_start", args)]

    def fields(self, asset_id: str) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT DISTINCT field FROM vi_observations WHERE asset_id = ? ORDER BY field", (asset_id,))]

    def value(self, asset_id: str, t: float | tuple[float, float], field: str, *, released_only: bool = False) -> Value | None:
        """The value of a field at an instant, or over a stretch (the observation covering most of it), fused from every source."""
        a, b = (t, t + 1e-6) if isinstance(t, (int, float)) else t
        found = self.observations(asset_id, field, (a, b))
        if not found:
            return None
        return fuse(field, found, self._released(), span=(a, b), released_only=released_only)

    def values(self, asset_id: str, t: float | tuple[float, float], fields: Iterable[str] | None = None, *, released_only: bool = False) -> dict[str, Value]:
        a, b = (t, t + 1e-6) if isinstance(t, (int, float)) else t
        by_field: dict[str, list[Observation]] = {}
        for o in self.observations(asset_id, None, (a, b)):
            if fields is None or o.field in fields:
                by_field.setdefault(o.field, []).append(o)
        released = self._released()
        out = {}
        for f, found in by_field.items():
            v = fuse(f, found, released, span=(a, b), released_only=released_only)
            if v is not None:
                out[f] = v
        return out

    # ------------------------------------------------------------------------------------------------------ entities
    def entities(self, kind: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM vi_entities", []
        if kind:
            q += " WHERE kind = ?"; args.append(kind)
        out = []
        for r in self._conn.execute(q + " ORDER BY kind, key", args):
            seen = [dict(a) | {"evidence": json.loads(a["evidence"])} for a in self._conn.execute("SELECT * FROM vi_appearances WHERE entity_id = ? ORDER BY asset_id, t_start", (r["entity_id"],))
                    if self._exists(a["asset_id"])]
            out.append({"entity_id": r["entity_id"], "kind": r["kind"], "key": r["key"], "name": r["name"], "data": json.loads(r["data"]), "appearances": seen})
        return out

    def artifacts(self, asset_id: str) -> dict[str, str]:
        return {r["kind"]: r["path"] for r in self._conn.execute("SELECT kind, path FROM vi_artifacts WHERE asset_id = ?", (asset_id,))}

    # ------------------------------------------------------------------------------------------------ finding things
    def find(self, query: str, *, limit: int = 20, levels: tuple[str, ...] = ("segment",), wanted: dict[str, str] | None = None, exclude_assets=frozenset()):
        """Stretches that answer a query by meaning and words, lifted where released fields agree with what is `wanted` (e.g.
        {"shot_size": "cận"}) and lowered where they disagree. Returns (score, moment, reasons) best first."""
        if self._search is None:
            return []
        hits = self._search(query, limit=limit * 3, levels=levels, exclude_assets=exclude_assets)
        out = []
        for h in hits:
            change, why = self.fit(h.moment.asset_id, (h.moment.t_start, h.moment.t_end), wanted or {})
            out.append((round(h.score + change, 4), h.moment, why))
        return sorted(out, key=lambda x: -x[0])[:limit]

    def fit(self, asset_id: str, span: tuple[float, float], wanted: dict[str, str], *, bonus: float = 0.08, penalty: float = 0.15) -> tuple[float, list[str]]:
        """How far the released values over a stretch agree with what is wanted."""
        change, why = 0.0, []
        if not wanted:
            return change, why
        have = self.values(asset_id, span, wanted.keys(), released_only=True)
        for f, want in wanted.items():
            v = have.get(f)
            if v is None:
                continue
            if v.value == want:
                change += bonus
                why.append(f"{f} {want} ({v.source})")
            else:
                change -= penalty
        return change, why

    def alike(self, asset_id: str, t_start: float, t_end: float, *, limit: int = 8) -> list[tuple[float, str, float, float]]:
        return self._alike(asset_id, t_start, t_end, limit=limit) if self._alike else []


def fuse(field: str, found: list[Observation], released: set[str], *, span: tuple[float, float], released_only: bool = False) -> Value | None:
    """One value from several observations of a field (design 2026-10-15, section 3.2): the operator's word first; then the most
    trusted source whose gate is passed; then, unless only released values are wanted, the most trusted source there is.
    Among observations of one source, the one covering most of the stretch."""
    a, b = span

    def cover(o: Observation) -> float:
        return max(0.0, min(o.t_end, b) - max(o.t_start, a)) or (1e-9 if o.t_start <= a <= o.t_end else 0.0)

    best_by_source: dict[str, Observation] = {}
    for o in found:
        if cover(o) <= 0:
            continue
        if o.source not in best_by_source or cover(o) > cover(best_by_source[o.source]):
            best_by_source[o.source] = o
    if not best_by_source:
        return None
    order = [s for s in SOURCES if s in best_by_source]
    chosen, is_released = None, False
    if "human" in best_by_source:
        chosen, is_released = best_by_source["human"], True
    else:
        for s in order:
            if gate_key(field, s) in released:
                chosen, is_released = best_by_source[s], True
                break
    if chosen is None:
        if released_only:
            return None
        chosen = best_by_source[order[0]]
    return Value(field, chosen.value, chosen.source, chosen.confidence, is_released, chosen.evidence, chosen.analyzer,
                 tuple(o for s, o in best_by_source.items() if o is not chosen))
