"""A time-coded text index over assets: moments, full-text search and vectors, in the same SQLite file.

Media-agnostic: a moment is a time range of an asset with text. Library writes it; Sourcing reads it.
"""
import json
import math
import re
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nexora.core import db
from nexora.core.ids import new_id


@dataclass(frozen=True)
class Moment:
    moment_id: str
    asset_id: str
    level: str
    t_start: float
    t_end: float
    text: str
    data: dict
    source: str
    analyzer: str | None


@dataclass(frozen=True)
class Hit:
    moment: Moment
    score: float            # 0..1: the larger of word coverage and vector similarity


def _moment(row) -> Moment:
    return Moment(row["moment_id"], row["asset_id"], row["level"], row["t_start"], row["t_end"], row["text"],
                  json.loads(row["data"]), row["source"], row["analyzer"])


def _tokens(query: str) -> list[str]:
    return [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1 or t.isdigit()]


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class MomentIndex:
    def __init__(self, path: str | Path, *, embed: Callable[[list[str]], list[list[float]]] | None = None):
        self._db = db.LocalConnections(path)
        self.embed = embed

    @property
    def _conn(self):
        return self._db.get()

    # ------------------------------------------------------------------ writes
    def upsert(self, asset_id: str, level: str, t_start: float, t_end: float, text: str, *, data: dict | None = None,
               analyzer: str | None = None) -> str:
        """Store a moment. A text corrected by the operator is never overwritten."""
        with db.write(self._conn) as c:
            row = c.execute("SELECT moment_id, source FROM moments WHERE asset_id = ? AND level = ? AND t_start = ? AND t_end = ?",
                            (asset_id, level, t_start, t_end)).fetchone()
            if row is None:
                moment_id = new_id("mom")
                c.execute("INSERT INTO moments (moment_id, asset_id, level, t_start, t_end, text, data, analyzer, created_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?)", (moment_id, asset_id, level, t_start, t_end, text, json.dumps(data or {}), analyzer, time.time()))
                c.execute("INSERT INTO moments_fts (text, moment_id) VALUES (?, ?)", (text, moment_id))
                return moment_id
            if row["source"] != "human":
                c.execute("UPDATE moments SET text = ?, data = ?, analyzer = ? WHERE moment_id = ?", (text, json.dumps(data or {}), analyzer, row["moment_id"]))
                self._reindex(c, row["moment_id"], text)
            return row["moment_id"]

    def correct(self, moment_id: str, text: str) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE moments SET text = ?, source = 'human' WHERE moment_id = ?", (text, moment_id))
            self._reindex(c, moment_id, text)

    def _reindex(self, c, moment_id: str, text: str) -> None:
        c.execute("DELETE FROM moments_fts WHERE moment_id = ?", (moment_id,))
        c.execute("INSERT INTO moments_fts (text, moment_id) VALUES (?, ?)", (text, moment_id))
        c.execute("DELETE FROM moment_vectors WHERE moment_id = ?", (moment_id,))       # stale until embedded again

    def set_vector(self, moment_id: str, vector: list[float]) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO moment_vectors (moment_id, vector) VALUES (?, ?) ON CONFLICT(moment_id) DO UPDATE SET vector = excluded.vector",
                      (moment_id, array("f", vector).tobytes()))

    # ------------------------------------------------------------------ reads
    def get(self, asset_id: str, level: str, t_start: float, t_end: float) -> Moment | None:
        row = self._conn.execute("SELECT * FROM moments WHERE asset_id = ? AND level = ? AND t_start = ? AND t_end = ?",
                                 (asset_id, level, t_start, t_end)).fetchone()
        return _moment(row) if row else None

    def by_id(self, moment_id: str) -> Moment | None:
        row = self._conn.execute("SELECT * FROM moments WHERE moment_id = ?", (moment_id,)).fetchone()
        return _moment(row) if row else None

    def moment(self, moment_id: str) -> Moment | None:
        row = self._conn.execute("SELECT * FROM moments WHERE moment_id = ?", (moment_id,)).fetchone()
        return _moment(row) if row else None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM moments WHERE level = 'segment'").fetchone()[0]

    def remove(self, asset_id: str, level: str) -> None:
        with db.write(self._conn) as c:
            ids = [r[0] for r in c.execute("SELECT moment_id FROM moments WHERE asset_id = ? AND level = ?", (asset_id, level))]
            for moment_id in ids:
                c.execute("DELETE FROM moments_fts WHERE moment_id = ?", (moment_id,))
                c.execute("DELETE FROM moment_vectors WHERE moment_id = ?", (moment_id,))
                c.execute("DELETE FROM moments WHERE moment_id = ?", (moment_id,))

    def moments(self, asset_id: str, *, level: str | None = None) -> list[Moment]:
        rows = self._conn.execute("SELECT * FROM moments WHERE asset_id = ? AND (? IS NULL OR level = ?) ORDER BY t_start, level",
                                  (asset_id, level, level))
        return [_moment(r) for r in rows]

    def without_vectors(self, asset_id: str) -> list[Moment]:
        rows = self._conn.execute("SELECT m.* FROM moments m LEFT JOIN moment_vectors v USING (moment_id) "
                                  "WHERE m.asset_id = ? AND v.moment_id IS NULL ORDER BY m.t_start", (asset_id,))
        return [_moment(r) for r in rows]

    def search(self, query: str, *, limit: int = 20, level: str | tuple[str, ...] = "segment", min_score: float = 0.0,
               exclude: frozenset[str] = frozenset(), exclude_assets: frozenset[str] = frozenset()) -> list[Hit]:
        """Hybrid search: words (ignoring diacritics) and meaning (vectors), merged into one ranked list.
        `level` names the kinds of moment to return: one, or several to search pictures, speech and notes together."""
        levels = (level,) if isinstance(level, str) else tuple(level)
        tokens = _tokens(query)
        if not tokens:
            return []
        coverage: dict[str, float] = {}
        for token in tokens:
            rows = self._conn.execute("SELECT moment_id FROM moments_fts WHERE moments_fts MATCH ?", (f'"{token}"',))
            for (moment_id,) in rows:
                coverage[moment_id] = coverage.get(moment_id, 0.0) + 1.0 / len(tokens)
        similarity: dict[str, float] = {}
        if self.embed is not None:
            try:
                q = self.embed([query])[0]
            except Exception:
                q = None                                 # the embedding model is unavailable: fall back to words alone
            if q is not None:
                for moment_id, blob in self._conn.execute("SELECT moment_id, vector FROM moment_vectors"):
                    v = array("f"); v.frombytes(blob)
                    similarity[moment_id] = _cosine(q, v)
        hits = []
        for moment_id in set(coverage) | set(similarity):
            score = max(coverage.get(moment_id, 0.0), similarity.get(moment_id, 0.0))
            if score < min_score or moment_id in exclude:
                continue
            moment = self.by_id(moment_id)
            if moment and moment.level in levels and moment.asset_id not in exclude_assets:
                hits.append((score, coverage.get(moment_id, 0.0) + similarity.get(moment_id, 0.0), moment))
        hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
        return [Hit(m, round(s, 4)) for s, _, m in hits[:limit]]
