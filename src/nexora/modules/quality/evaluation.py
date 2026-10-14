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
CREATE TABLE IF NOT EXISTS eval_boundaries (asset_id TEXT NOT NULL, kind TEXT NOT NULL, t REAL NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (asset_id, kind, t));
CREATE TABLE IF NOT EXISTS eval_references (asset_id TEXT PRIMARY KEY, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS eval_structure_runs (run_id TEXT PRIMARY KEY, created_at REAL NOT NULL, config TEXT NOT NULL, summary TEXT NOT NULL, details TEXT NOT NULL);
"""
WORSE_BY = 0.05          # a drop of more than this share of cases counts as a regression
NEAR = 0.5               # seconds: a boundary found this close to one the operator marked is that boundary
KINDS = ("shot", "beat")


def score_boundaries(found: list[float], marked: list[float], *, near: float = NEAR) -> dict:
    """How the boundaries the rules found compare with the ones a person marked. Each marked boundary is answered by at most
    one found boundary and the other way round, nearest first. `precision` is the share of what was found that a person had
    marked; `recall` the share of what a person marked that was found."""
    pairs = sorted((abs(f - m), i, j) for i, f in enumerate(found) for j, m in enumerate(marked) if abs(f - m) <= near)
    used_found, used_marked = set(), set()
    for _, i, j in pairs:
        if i not in used_found and j not in used_marked:
            used_found.add(i); used_marked.add(j)
    matched = len(used_found)
    return {"found": len(found), "marked": len(marked), "matched": matched,
            "precision": round(matched / len(found), 3) if found else None, "recall": round(matched / len(marked), 3) if marked else None,
            "missed": [marked[j] for j in range(len(marked)) if j not in used_marked], "extra": [found[i] for i in range(len(found)) if i not in used_found]}


def overlaps(a_in: float, a_out: float, b_in: float, b_out: float) -> bool:
    return min(a_out, b_out) - max(a_in, b_in) > 0.5 or (a_in <= b_in and a_out >= b_out) or (b_in <= a_in and b_out >= a_out)


class Evaluation:
    def __init__(self, db_path: str | Path, index: MomentIndex, *, threshold: float = 0.5, measured=None, faults=None):
        self._db, self._index, self._threshold = db.LocalConnections(db_path), index, threshold
        self._measured = measured or (lambda asset_id: None)      # asset id -> the boundaries the rules find on their own, by kind
        self._faults = faults or (lambda: {})                     # every asset whose beats leave a second out or share one, with what is wrong
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

    # ------------------------------------------------------------------ how footage is divided
    def set_reference(self, asset_id: str, marks: dict[str, list[float]]) -> None:
        """Take the boundaries of an asset as they stand, after the operator has put them right, as the answer for that asset.
        The whole asset is the answer: a boundary that is not in `marks` is one the operator says is not there."""
        now = time.time()
        with db.write(self._conn) as c:
            c.execute("DELETE FROM eval_boundaries WHERE asset_id = ?", (asset_id,))
            c.execute("INSERT INTO eval_references (asset_id, created_at) VALUES (?, ?) ON CONFLICT(asset_id) DO UPDATE SET created_at = excluded.created_at", (asset_id, now))
            for kind in KINDS:
                for t in sorted({round(float(t), 2) for t in marks.get(kind, [])}):
                    c.execute("INSERT INTO eval_boundaries (asset_id, kind, t, created_at) VALUES (?,?,?,?)", (asset_id, kind, t, now))

    def clear_reference(self, asset_id: str) -> None:
        with db.write(self._conn) as c:
            c.execute("DELETE FROM eval_boundaries WHERE asset_id = ?", (asset_id,))
            c.execute("DELETE FROM eval_references WHERE asset_id = ?", (asset_id,))

    def forget_asset(self, asset_id: str) -> int:
        """An asset has left the library: the answers it held, for the search and for the division, go with it."""
        with db.write(self._conn) as c:
            cases = c.execute("SELECT COUNT(*) FROM eval_cases WHERE asset_id = ?", (asset_id,)).fetchone()[0]
            c.execute("DELETE FROM eval_cases WHERE asset_id = ?", (asset_id,))
            c.execute("DELETE FROM eval_boundaries WHERE asset_id = ?", (asset_id,))
            c.execute("DELETE FROM eval_references WHERE asset_id = ?", (asset_id,))
        return cases

    def references(self) -> dict[str, dict[str, list[float]]]:
        out = {r["asset_id"]: {kind: [] for kind in KINDS} for r in self._conn.execute("SELECT asset_id FROM eval_references ORDER BY created_at, asset_id")}
        for r in self._conn.execute("SELECT asset_id, kind, t FROM eval_boundaries ORDER BY t"):
            if r["asset_id"] in out and r["kind"] in out[r["asset_id"]]:
                out[r["asset_id"]][r["kind"]].append(r["t"])
        return out

    def run_structure(self, config: dict) -> dict:
        """Hold the boundaries the rules find, with none of the operator's marks, against the ones the operator marked, asset by
        asset and over all of them; and count the assets in the whole library whose beats leave a second out or share one."""
        details, total = [], {kind: {"found": 0, "marked": 0, "matched": 0} for kind in KINDS}
        for asset_id, marks in self.references().items():
            found = self._measured(asset_id)
            if found is None:
                details.append({"asset_id": asset_id, "missing": True})
                continue
            row = {"asset_id": asset_id}
            for kind in KINDS:
                row[kind] = score_boundaries(found.get(kind, []), marks[kind])
                for key in total[kind]:
                    total[kind][key] += row[kind][key]
            details.append(row)
        faults = self._faults()
        summary = {"assets": len(details), "faults": len(faults), "faulty": sorted(faults)[:20]}
        for kind in KINDS:
            t = total[kind]
            summary[kind] = {**t, "precision": round(t["matched"] / t["found"], 3) if t["found"] else None, "recall": round(t["matched"] / t["marked"], 3) if t["marked"] else None}
        run = {"run_id": new_id("evs"), "created_at": time.time(), "config": config, "summary": summary, "details": details}
        with db.write(self._conn) as c:
            c.execute("INSERT INTO eval_structure_runs (run_id, created_at, config, summary, details) VALUES (?,?,?,?,?)",
                      (run["run_id"], run["created_at"], json.dumps(config, ensure_ascii=False), json.dumps(summary, ensure_ascii=False), json.dumps(details, ensure_ascii=False)))
        return run

    def structure_runs(self, limit: int = 10) -> list[dict]:
        """Newest first, each with how it differs from the one before: in what it scored and in what was configured."""
        rows = [{**dict(r), "config": json.loads(r["config"]), "summary": json.loads(r["summary"]), "details": json.loads(r["details"])}
                for r in self._conn.execute("SELECT * FROM eval_structure_runs ORDER BY created_at DESC, run_id DESC LIMIT ?", (limit + 1,))]
        for newer, older in zip(rows, rows[1:]):
            change = {"config": {k: [older["config"].get(k), v] for k, v in newer["config"].items() if older["config"].get(k) != v}}
            for kind in KINDS:
                for measure in ("precision", "recall"):
                    a, b = newer["summary"][kind][measure], older["summary"][kind][measure]
                    change[f"{kind}_{measure}"] = round(a - b, 3) if a is not None and b is not None else None
            change["regression"] = any(v is not None and v < -WORSE_BY for k, v in change.items() if k != "config" and not isinstance(v, dict))
            newer["change"] = change
        return rows[:limit]

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
