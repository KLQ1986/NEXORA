"""The writing side of Visual Quality (see `nexora.core.visual_quality`). Only the Visual Quality domain may import this
module; the import contracts in pyproject.toml forbid it to every other domain."""
import json
import time
from pathlib import Path
from typing import Iterable

from nexora.core import db
from nexora.core.ids import new_id
from nexora.core.visual_quality import STATUSES, ensure_schema


class VisualQualityStore:
    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        ensure_schema(db_path)

    @property
    def _conn(self):
        return self._db.get()

    def subject(self, subject: str, *, kind: str, path: str | Path, checksum: str | None = None) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO vq_subjects (subject, kind, path, checksum, created_at) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(subject) DO UPDATE SET path = excluded.path, checksum = COALESCE(excluded.checksum, vq_subjects.checksum)",
                      (subject, kind, str(path), checksum, time.time()))

    def new_job(self, path: str | Path) -> str:
        job = new_id("vqj")
        self.subject(job, kind="file", path=path)
        return job

    def profile(self, subject: str, data: dict, *, analyzer: str) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT OR REPLACE INTO vq_profiles (subject, data, analyzer, at) VALUES (?,?,?,?)",
                      (subject, json.dumps(data, ensure_ascii=False), analyzer, time.time()))

    def defects(self, subject: str, rows: Iterable[dict], *, analyzer: str) -> None:
        """Put the defects of a subject in place of the ones before."""
        with db.write(self._conn) as c:
            c.execute("DELETE FROM vq_defects WHERE subject = ?", (subject,))
            for d in rows:
                extra = {k: v for k, v in d.items() if k not in ("t_start", "t_end", "kind", "severity")}
                c.execute("INSERT OR REPLACE INTO vq_defects (subject, t_start, t_end, kind, severity, data, analyzer) VALUES (?,?,?,?,?,?,?)",
                          (subject, float(d["t_start"]), float(d["t_end"]), d["kind"], float(d["severity"]), json.dumps(extra, ensure_ascii=False), analyzer))

    def recipe(self, subject: str, data: dict, *, status: str = "proposed", decided_by: str | None = None) -> str:
        """A new version of a subject's recipe."""
        assert status in STATUSES
        with db.write(self._conn) as c:
            version = (c.execute("SELECT MAX(version) FROM vq_recipes WHERE subject = ?", (subject,)).fetchone()[0] or 0) + 1
            recipe_id = new_id("rcp")
            c.execute("INSERT INTO vq_recipes (recipe_id, subject, version, data, status, decided_by, at) VALUES (?,?,?,?,?,?,?)",
                      (recipe_id, subject, version, json.dumps(data, ensure_ascii=False), status, decided_by, time.time()))
        return recipe_id

    def update_recipe(self, recipe_id: str, data: dict) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE vq_recipes SET data = ? WHERE recipe_id = ?", (json.dumps(data, ensure_ascii=False), recipe_id))

    def decide(self, recipe_id: str, status: str, *, decided_by: str) -> None:
        """Approve or reject a recipe. Approving one sets aside any other approved recipe of the same subject."""
        assert status in STATUSES
        with db.write(self._conn) as c:
            subject = c.execute("SELECT subject FROM vq_recipes WHERE recipe_id = ?", (recipe_id,)).fetchone()[0]
            if status == "approved":
                c.execute("UPDATE vq_recipes SET status = 'proposed' WHERE subject = ? AND status = 'approved' AND recipe_id != ?", (subject, recipe_id))
            c.execute("UPDATE vq_recipes SET status = ?, decided_by = ? WHERE recipe_id = ?", (status, decided_by, recipe_id))

    def metrics(self, recipe_id: str, rows: Iterable[tuple[float, float, str, float | None, float | None]]) -> None:
        with db.write(self._conn) as c:
            for t0, t1, metric, before, after in rows:
                c.execute("INSERT OR REPLACE INTO vq_metrics (recipe_id, t_start, t_end, metric, before, after) VALUES (?,?,?,?,?,?)",
                          (recipe_id, float(t0), float(t1), metric, before, after))

    def preview(self, recipe_id: str, t: float, seconds: float, data: dict) -> str:
        preview_id = new_id("vqp")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO vq_previews (preview_id, recipe_id, t, seconds, data, at) VALUES (?,?,?,?,?,?)",
                      (preview_id, recipe_id, float(t), float(seconds), json.dumps(data, ensure_ascii=False), time.time()))
        return preview_id

    def prepared(self, recipe_id: str, t_start: float, t_end: float, path: str | Path) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT OR REPLACE INTO vq_prepared (recipe_id, t_start, t_end, path, at) VALUES (?,?,?,?,?)",
                      (recipe_id, float(t_start), float(t_end), str(path), time.time()))

    def request(self, subject: str, kind: str, params: dict | None = None) -> str:
        request_id = new_id("vqr")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO vq_requests (request_id, subject, kind, params, status, at) VALUES (?,?,?,?,?,?)",
                      (request_id, subject, kind, json.dumps(params or {}, ensure_ascii=False), "pending", time.time()))
        return request_id

    def finish_request(self, request_id: str, status: str, result: dict | None = None) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE vq_requests SET status = ?, result = ? WHERE request_id = ?", (status, json.dumps(result or {}, ensure_ascii=False), request_id))

    def forget_previews(self, preview_ids: list[str]) -> None:
        with db.write(self._conn) as c:
            c.executemany("DELETE FROM vq_previews WHERE preview_id = ?", [(i,) for i in preview_ids])

    def forget_prepared(self, recipe_ids: list[str]) -> None:
        with db.write(self._conn) as c:
            c.executemany("DELETE FROM vq_prepared WHERE recipe_id = ?", [(i,) for i in recipe_ids])

    def forget(self, subject: str) -> None:
        with db.write(self._conn) as c:
            ids = [r[0] for r in c.execute("SELECT recipe_id FROM vq_recipes WHERE subject = ?", (subject,))]
            for t in ("vq_metrics", "vq_previews", "vq_prepared"):
                c.executemany(f"DELETE FROM {t} WHERE recipe_id = ?", [(i,) for i in ids])
            for t in ("vq_recipes", "vq_defects", "vq_profiles", "vq_requests", "vq_subjects"):
                c.execute(f"DELETE FROM {t} WHERE subject = ?", (subject,))
