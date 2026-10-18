"""Productions (design 2026-10-18, projects of videos): what the interface calls a project, holding several videos.

A video is what the code has always called a project: its script, storyboard, cuts and publications, untouched here. A
production groups videos and holds what they share (channel, template, voice, music, characters, research, a total budget).
Shared is not locked: a video takes its production's values when it is made, a change on the production reaches the videos
still on its previous value (done by the composition root, which knows how a template is applied), and a video given its own
value keeps it.
"""
from __future__ import annotations

import time
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS productions (production_id TEXT PRIMARY KEY, title TEXT NOT NULL, channel TEXT, template TEXT, voice TEXT,
    music_path TEXT, bible TEXT, research TEXT, budget_cap REAL, notes TEXT, created_at REAL NOT NULL)
"""
SHARED = ("channel", "template", "voice", "music_path", "bible", "research")      # what a video takes from its production
FIELDS = ("title", *SHARED, "budget_cap", "notes")


class ProductionStore:
    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        with db.write(self._db.get()) as c:
            c.execute(SCHEMA)

    @property
    def _conn(self):
        return self._db.get()

    def create(self, title: str, **values) -> str:
        production_id = new_id("prd")
        given = {k: v for k, v in values.items() if k in FIELDS and k != "title"}
        with db.write(self._conn) as c:
            c.execute(f"INSERT INTO productions (production_id, title, created_at{''.join(', ' + k for k in given)}) VALUES (?,?,?{',?' * len(given)})",
                      (production_id, title.strip() or "Dự án mới", time.time(), *given.values()))
        return production_id

    def get(self, production_id: str | None) -> dict | None:
        if not production_id:
            return None
        r = self._conn.execute("SELECT * FROM productions WHERE production_id = ?", (production_id,)).fetchone()
        return dict(r) if r else None

    def productions(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM productions ORDER BY created_at DESC")]

    def update(self, production_id: str, **fields) -> dict:
        """The production's own record; what reaches its videos is the caller's to decide. Returns the values before."""
        before = self.get(production_id)
        if before is None:
            raise LookupError(production_id)
        given = {k: v for k, v in fields.items() if k in FIELDS}
        with db.write(self._conn) as c:
            for k, v in given.items():
                c.execute(f"UPDATE productions SET {k} = ? WHERE production_id = ?", (v, production_id))
        return before

    def remove(self, production_id: str) -> None:
        """A production with no video left in it (in the Trash or not) is removed."""
        with db.write(self._conn) as c:
            if c.execute("SELECT 1 FROM projects WHERE production_id = ?", (production_id,)).fetchone():
                raise ValueError("the production still has videos")
            c.execute("DELETE FROM productions WHERE production_id = ?", (production_id,))

    def adopt_loose(self) -> int:
        """Every video that belongs to no production gets one of its own, of its title, its shared values taken from it (the
        migration of projects made before productions existed; run again it finds nothing). Returns how many were adopted."""
        made = 0
        loose = self._conn.execute("SELECT project_id, title, " + ", ".join(SHARED) + ", budget_cap, created_at FROM projects WHERE production_id IS NULL").fetchall()
        for r in loose:
            production_id = new_id("prd")
            with db.write(self._conn) as c:
                c.execute("INSERT INTO productions (production_id, title, created_at, " + ", ".join(SHARED) + ") VALUES (?,?,?" + ",?" * len(SHARED) + ")",
                          (production_id, r["title"], r["created_at"], *(r[k] for k in SHARED)))
                c.execute("UPDATE projects SET production_id = ? WHERE project_id = ?", (production_id, r["project_id"]))
            made += 1
        return made
