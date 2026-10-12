"""A benchmark of the operator's own making, and a way to tell whether a change made things worse (design v4.0, section 20.4).

A case is a script line and the stretch of footage a person has said is right for it. A run asks the search the same
questions under the configuration in force and counts how often the right stretch comes first, or among the first
three. Each run records that configuration, so that after a model, a prompt or a threshold is changed the next run
can be held against the last.
"""
import json
import time
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id
from nexora.core.index import MomentIndex

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_cases (case_id TEXT PRIMARY KEY, line TEXT NOT NULL, asset_id TEXT NOT NULL, t_in REAL NOT NULL, t_out REAL NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS eval_runs (run_id TEXT PRIMARY KEY, created_at REAL NOT NULL, config TEXT NOT NULL, cases INTEGER NOT NULL, first REAL NOT NULL, top3 REAL NOT NULL, details TEXT NOT NULL);
"""
WORSE_BY = 0.05          # a drop of more than this share of cases counts as a regression


def overlaps(a_in: float, a_out: float, b_in: float, b_out: float) -> bool:
    return min(a_out, b_out) - max(a_in, b_in) > 0.5 or (a_in <= b_in and a_out >= b_out) or (b_in <= a_in and b_out >= a_out)


class Evaluation:
    def __init__(self, db_path: str | Path, index: MomentIndex, *, threshold: float = 0.5):
        self._db, self._index, self._threshold = db.LocalConnections(db_path), index, threshold
        with db.write(self._conn) as c:
            for statement in SCHEMA.strip().split(";\n"):
                c.execute(statement)

    @property
    def _conn(self):
        return self._db.get()

    def add_case(self, line: str, asset_id: str, t_in: float, t_out: float) -> str:
        with db.write(self._conn) as c:
            row = c.execute("SELECT case_id FROM eval_cases WHERE line = ? AND asset_id = ?", (line, asset_id)).fetchone()
            case_id = row[0] if row else new_id("evc")
            c.execute("INSERT INTO eval_cases (case_id, line, asset_id, t_in, t_out, created_at) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(case_id) DO UPDATE SET t_in = excluded.t_in, t_out = excluded.t_out", (case_id, line, asset_id, round(t_in, 2), round(t_out, 2), time.time()))
        return case_id

    def remove_case(self, case_id: str) -> None:
        with db.write(self._conn) as c:
            c.execute("DELETE FROM eval_cases WHERE case_id = ?", (case_id,))

    def cases(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM eval_cases ORDER BY created_at, case_id")]

    def run(self, config: dict) -> dict:
        """Ask every case's question and record how the search did. `config` is whatever describes the installation now."""
        cases, details, first, top3 = self.cases(), [], 0, 0
        for case in cases:
            hits = self._index.search(case["line"], limit=3, min_score=self._threshold)
            rank = next((i for i, h in enumerate(hits, 1) if h.moment.asset_id == case["asset_id"] and overlaps(h.moment.t_start, h.moment.t_end, case["t_in"], case["t_out"])), None)
            first, top3 = first + (rank == 1), top3 + (rank is not None)
            details.append({"case_id": case["case_id"], "line": case["line"], "rank": rank, "best_score": hits[0].score if hits else None})
        n = len(cases) or 1
        run = {"run_id": new_id("evr"), "created_at": time.time(), "config": config, "cases": len(cases), "first": round(first / n, 3), "top3": round(top3 / n, 3), "details": details}
        with db.write(self._conn) as c:
            c.execute("INSERT INTO eval_runs (run_id, created_at, config, cases, first, top3, details) VALUES (?,?,?,?,?,?,?)",
                      (run["run_id"], run["created_at"], json.dumps(config, ensure_ascii=False), run["cases"], run["first"], run["top3"], json.dumps(details, ensure_ascii=False)))
        return run

    def runs(self, limit: int = 10) -> list[dict]:
        """Newest first. Each run says how it compares with the one before it, and what in the configuration changed between them."""
        rows = [{**dict(r), "config": json.loads(r["config"]), "details": json.loads(r["details"])}
                for r in self._conn.execute("SELECT * FROM eval_runs ORDER BY created_at DESC, run_id DESC LIMIT ?", (limit + 1,))]
        for newer, older in zip(rows, rows[1:]):
            before = {d["case_id"]: d["rank"] for d in older["details"]}
            newer["change"] = {"first": round(newer["first"] - older["first"], 3), "top3": round(newer["top3"] - older["top3"], 3),
                               "regression": newer["cases"] > 0 and (older["first"] - newer["first"] > WORSE_BY or older["top3"] - newer["top3"] > WORSE_BY),
                               "config": {k: [older["config"].get(k), v] for k, v in newer["config"].items() if older["config"].get(k) != v},
                               "lost": [d["line"] for d in newer["details"] if d["rank"] is None and before.get(d["case_id"]) is not None]}
        return rows[:limit]
