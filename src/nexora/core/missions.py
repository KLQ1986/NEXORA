"""Missions (Mission Control spec; design 2026-10-18): what the operator asked for, the plan made of it, and what it started.

A mission is a record of intent, not a second copy of the work: the runs, tasks and projects it starts keep their own state,
and a mission's status is read from them (agents/missions.py). What is kept here is only what nothing else knows: the
words, the plan, the operator's own choices about the mission (confirmed, paused, cancelled) and its events.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (mission_id TEXT PRIMARY KEY, text TEXT NOT NULL, plan TEXT NOT NULL, problems TEXT NOT NULL,
    state TEXT NOT NULL, links TEXT NOT NULL, events TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, production_id TEXT);
CREATE INDEX IF NOT EXISTS missions_created ON missions (created_at)
"""
STATES = ("draft", "planned", "confirmed", "paused", "cancelled")
LINKS = ("projects", "tasks", "runs")


class MissionStore:
    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        with db.write(self._db.get()) as c:
            for statement in SCHEMA.strip().split(";\n"):
                if statement.strip():
                    c.execute(statement)
            if "production_id" not in {r[1] for r in c.execute("PRAGMA table_info(missions)")}:
                c.execute("ALTER TABLE missions ADD COLUMN production_id TEXT")
            # The production a mission works for (projects of videos, 2026-10-18): the one it was given from, else the one its
            # videos went into. Missions made before it was kept take it from their plan (when that production is still there) or their first video.
            c.execute("UPDATE missions SET production_id = COALESCE("
                      "(SELECT d.production_id FROM productions d WHERE d.production_id = json_extract(missions.plan, '$.production_id')), "
                      "(SELECT p.production_id FROM projects p WHERE p.project_id = json_extract(missions.links, '$.projects[0]'))) "
                      "WHERE production_id IS NULL")

    @property
    def _conn(self):
        return self._db.get()

    def _row(self, r) -> dict:
        return {**dict(r), "plan": json.loads(r["plan"]), "problems": json.loads(r["problems"]), "links": json.loads(r["links"]), "events": json.loads(r["events"])}

    def create(self, text: str, plan: dict, problems: list[str]) -> str:
        mission_id, now = new_id("msn"), time.time()
        events = [{"at": now, "kind": "created", "text": text}, {"at": now, "kind": "planned", "text": "; ".join(problems) or None}]
        with db.write(self._conn) as c:
            c.execute("INSERT INTO missions (mission_id, text, plan, problems, state, links, events, created_at, updated_at, production_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (mission_id, text, json.dumps(plan, ensure_ascii=False), json.dumps(problems, ensure_ascii=False), "draft" if problems else "planned",
                       json.dumps({k: [] for k in LINKS}), json.dumps(events, ensure_ascii=False), now, now, plan.get("production_id")))
        return mission_id

    def get(self, mission_id: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,)).fetchone()
        return self._row(r) if r else None

    def missions(self, *, limit: int = 200, production_id: str | None = None) -> list[dict]:
        if production_id:
            rows = self._conn.execute("SELECT * FROM missions WHERE production_id = ? ORDER BY created_at DESC LIMIT ?", (production_id, limit))
        else:
            rows = self._conn.execute("SELECT * FROM missions ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def set_production(self, mission_id: str, production_id: str | None) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE missions SET production_id = ? WHERE mission_id = ?", (production_id, mission_id))

    def _event(self, c, mission_id: str, kind: str, text: str | None) -> None:
        events = json.loads(c.execute("SELECT events FROM missions WHERE mission_id = ?", (mission_id,)).fetchone()[0])
        events.append({"at": time.time(), "kind": kind, "text": text})
        c.execute("UPDATE missions SET events = ?, updated_at = ? WHERE mission_id = ?", (json.dumps(events, ensure_ascii=False), time.time(), mission_id))

    def replan(self, mission_id: str, plan: dict, problems: list[str]) -> dict:
        """The plan as the operator edited it, checked again. Only a mission not yet confirmed can be replanned."""
        with db.write(self._conn) as c:
            c.execute("UPDATE missions SET plan = ?, problems = ?, state = ? WHERE mission_id = ? AND state IN ('draft', 'planned')",
                      (json.dumps(plan, ensure_ascii=False), json.dumps(problems, ensure_ascii=False), "draft" if problems else "planned", mission_id))
            self._event(c, mission_id, "edited", "; ".join(problems) or None)
        return self.get(mission_id)

    def set_state(self, mission_id: str, state: str, *, note: str | None = None) -> dict:
        assert state in STATES
        with db.write(self._conn) as c:
            c.execute("UPDATE missions SET state = ? WHERE mission_id = ?", (state, mission_id))
            self._event(c, mission_id, {"confirmed": "confirmed", "paused": "paused", "cancelled": "cancelled"}.get(state, state), note)
        return self.get(mission_id)

    def event(self, mission_id: str, kind: str, text: str | None = None) -> None:
        with db.write(self._conn) as c:
            self._event(c, mission_id, kind, text)

    def link(self, mission_id: str, **started: list[str]) -> dict:
        """What the mission started, added to what it had."""
        with db.write(self._conn) as c:
            links = json.loads(c.execute("SELECT links FROM missions WHERE mission_id = ?", (mission_id,)).fetchone()[0])
            for key, ids in started.items():
                assert key in LINKS
                links[key] = list(dict.fromkeys([*links.get(key, []), *ids]))
            c.execute("UPDATE missions SET links = ?, updated_at = ? WHERE mission_id = ?", (json.dumps(links), time.time(), mission_id))
        return self.get(mission_id)

    def owner(self) -> dict[str, str]:
        """Each project, task and run started by a mission, with the mission that started it."""
        out = {}
        for m in self.missions(limit=1000):
            for key in LINKS:
                for ref in m["links"].get(key, []):
                    out[ref] = m["mission_id"]
        return out
