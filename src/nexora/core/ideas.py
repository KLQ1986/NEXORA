"""Video ideas the library can carry, kept (design v4.0, 16.1 and 16.6; design 2026-10-18).

An idea is proposed from a cluster of footage. Proposing again replaces the ideas of the same cluster that the operator has
not decided on; an accepted or dropped idea stays as history. An idea whose risk would stop the video (consent, privacy, a
claim that is wrong or unlawful) is blocked: it is taken only with the operator's reason, and the reason is kept with it.
Any other risk is shown as a note.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (idea_id TEXT PRIMARY KEY, cluster TEXT NOT NULL, title TEXT NOT NULL, angle TEXT, template TEXT, channel TEXT,
    scores TEXT NOT NULL, total INTEGER NOT NULL, coverage REAL NOT NULL, shots TEXT NOT NULL, gaps TEXT NOT NULL, seconds REAL NOT NULL,
    material TEXT NOT NULL, risk TEXT, status TEXT NOT NULL, reason TEXT, project_id TEXT, created_at REAL NOT NULL, decided_at REAL);
CREATE INDEX IF NOT EXISTS ideas_status ON ideas (status, created_at)
"""
OPEN = ("new", "blocked")
JSON_FIELDS = ("scores", "shots", "gaps", "material")


class IdeaStore:
    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        with db.write(self._db.get()) as c:
            for statement in SCHEMA.strip().split(";\n"):
                if statement.strip():
                    c.execute(statement)

    @property
    def _conn(self):
        return self._db.get()

    def propose(self, cluster: str, ideas: list[dict]) -> list[str]:
        """The cluster's new ideas, in place of the ones the operator has not decided on yet."""
        ids = []
        with db.write(self._conn) as c:
            c.execute(f"DELETE FROM ideas WHERE cluster = ? AND status IN ({','.join('?' * len(OPEN))})", (cluster, *OPEN))
            for i in ideas:
                idea_id = new_id("ide")
                c.execute("INSERT INTO ideas (idea_id, cluster, title, angle, template, channel, scores, total, coverage, shots, gaps, seconds, material, risk, status, created_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (idea_id, cluster, i["title"], i.get("angle") or None, i.get("template"), i.get("channel"), json.dumps(i["scores"], ensure_ascii=False),
                           int(i["total"]), float(i["coverage"]), json.dumps(i["shots"], ensure_ascii=False), json.dumps(i["gaps"], ensure_ascii=False), float(i["seconds"]),
                           json.dumps(i["material"], ensure_ascii=False), i.get("risk") or None, "blocked" if i.get("blocking") else "new", time.time()))
                ids.append(idea_id)
        return ids

    def clear_open(self) -> int:
        """Every undecided idea set aside before proposing again, so an idea of a group not proposed for this time does not linger."""
        with db.write(self._conn) as c:
            return c.execute(f"DELETE FROM ideas WHERE status IN ({','.join('?' * len(OPEN))})", OPEN).rowcount

    def _row(self, r) -> dict:
        out = dict(r)
        for k in JSON_FIELDS:
            out[k] = json.loads(out[k])
        return out

    def get(self, idea_id: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM ideas WHERE idea_id = ?", (idea_id,)).fetchone()
        return self._row(r) if r else None

    def ideas(self, *, status: tuple[str, ...] | None = None) -> list[dict]:
        """Open ideas first (unblocked before blocked), each by its score; then decided ones, newest first."""
        rows = [self._row(r) for r in self._conn.execute("SELECT * FROM ideas ORDER BY created_at DESC")]
        if status:
            rows = [r for r in rows if r["status"] in status]
        rank = {"new": 0, "blocked": 1, "accepted": 2, "dropped": 3}
        return sorted(rows, key=lambda r: (rank.get(r["status"], 4), -r["total"] if r["status"] in OPEN else -(r["decided_at"] or 0)))

    def accept(self, idea_id: str, project_id: str, *, reason: str | None = None) -> dict:
        """Taken into a project. A blocked idea needs the operator's reason for going ahead despite its risk."""
        self.check(idea_id, reason=reason)
        with db.write(self._conn) as c:
            c.execute("UPDATE ideas SET status = 'accepted', project_id = ?, reason = ?, decided_at = ? WHERE idea_id = ?",
                      (project_id, (reason or "").strip() or None, time.time(), idea_id))
        return self.get(idea_id)

    def check(self, idea_id: str, *, reason: str | None = None) -> dict:
        """Whether the idea can be taken: refused before anything is made from it."""
        idea = self.get(idea_id)
        if idea is None or idea["status"] not in OPEN:
            raise LookupError(idea_id)
        if idea["status"] == "blocked" and not (reason or "").strip():
            raise ValueError("a blocked idea is taken only with a reason")
        return idea

    def drop(self, idea_id: str) -> dict:
        idea = self.get(idea_id)
        if idea is None or idea["status"] not in OPEN:
            raise LookupError(idea_id)
        with db.write(self._conn) as c:
            c.execute("UPDATE ideas SET status = 'dropped', decided_at = ? WHERE idea_id = ?", (time.time(), idea_id))
        return self.get(idea_id)
