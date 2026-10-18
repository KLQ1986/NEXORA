"""A project's storyboard: its scenes, its shots as versioned specs, the conversation with the Director (design 2026-10-17).

A shot's spec is a contract: what it must show, how long, how it is framed and where the camera stands, where its picture
comes from, how it is made when it is made, what it must stay consistent with, and how it is accepted. Every change makes a
new version; the old ones are kept and can be returned to. The writing is done by the planning domain and the Director
(agents); everything else reads.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS sb_boards (project_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sb_scenes (scene_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, position REAL NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sb_scenes_project ON sb_scenes (project_id, position);
CREATE TABLE IF NOT EXISTS sb_shots (shot_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, scene_id TEXT NOT NULL, position REAL NOT NULL,
  version INTEGER NOT NULL, spec TEXT NOT NULL, state TEXT NOT NULL, assignment TEXT, checks TEXT, script_shot TEXT, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS sb_shots_project ON sb_shots (project_id, position);
CREATE TABLE IF NOT EXISTS sb_versions (shot_id TEXT NOT NULL, version INTEGER NOT NULL, spec TEXT NOT NULL, made_by TEXT NOT NULL, note TEXT,
  at REAL NOT NULL, PRIMARY KEY (shot_id, version));
CREATE TABLE IF NOT EXISTS sb_messages (message_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
  proposal TEXT, status TEXT, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS sb_messages_project ON sb_messages (project_id, at)
"""

STATES = ("planned", "running", "accepted", "needs", "stale")


def ensure_schema(db_path: str | Path) -> None:
    conn = db.LocalConnections(db_path).get()
    with db.write(conn) as c:
        for statement in SCHEMA.strip().split(";\n"):
            if statement.strip():
                c.execute(statement)


@dataclass(frozen=True)
class Scene:
    scene_id: str
    project_id: str
    position: float
    data: dict

    @property
    def title(self) -> str:
        return self.data.get("title", "")


@dataclass(frozen=True)
class Shot:
    shot_id: str
    project_id: str
    scene_id: str
    position: float
    version: int
    spec: dict
    state: str
    assignment: dict | None = None
    checks: list = field(default_factory=list)
    script_shot: str | None = None         # the project script's shot this one was written to (planning sync)
    updated_at: float = 0.0


class Storyboard:
    """Reads and writes a project's storyboard."""

    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        ensure_schema(db_path)

    @property
    def _conn(self):
        return self._db.get()

    # ----------------------------------------------------------------------------------------------------------- board
    def board(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT data FROM sb_boards WHERE project_id = ?", (project_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def set_board(self, project_id: str, data: dict) -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO sb_boards (project_id, data, updated_at) VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET data = excluded.data, "
                      "updated_at = excluded.updated_at", (project_id, json.dumps(data, ensure_ascii=False), time.time()))

    def clear(self, project_id: str) -> None:
        """Everything of a project's storyboard but its conversation (a new one is made in its place)."""
        with db.write(self._conn) as c:
            ids = [r[0] for r in c.execute("SELECT shot_id FROM sb_shots WHERE project_id = ?", (project_id,))]
            c.executemany("DELETE FROM sb_versions WHERE shot_id = ?", [(i,) for i in ids])
            c.execute("DELETE FROM sb_shots WHERE project_id = ?", (project_id,))
            c.execute("DELETE FROM sb_scenes WHERE project_id = ?", (project_id,))

    # ---------------------------------------------------------------------------------------------------------- scenes
    def scenes(self, project_id: str) -> list[Scene]:
        return [Scene(r["scene_id"], r["project_id"], r["position"], json.loads(r["data"]))
                for r in self._conn.execute("SELECT * FROM sb_scenes WHERE project_id = ? ORDER BY position", (project_id,))]

    def add_scene(self, project_id: str, data: dict, *, position: float | None = None) -> str:
        scene_id = new_id("scn")
        with db.write(self._conn) as c:
            if position is None:
                position = (c.execute("SELECT MAX(position) FROM sb_scenes WHERE project_id = ?", (project_id,)).fetchone()[0] or 0) + 1
            c.execute("INSERT INTO sb_scenes (scene_id, project_id, position, data) VALUES (?,?,?,?)", (scene_id, project_id, position, json.dumps(data, ensure_ascii=False)))
        return scene_id

    def set_scene(self, scene_id: str, data: dict) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE sb_scenes SET data = ? WHERE scene_id = ?", (json.dumps(data, ensure_ascii=False), scene_id))

    def forget_project(self, project_id: str) -> int:
        """A project has been deleted: its storyboard goes with it (board, scenes, shots and their versions, the conversation).
        Returns how many shots were dropped."""
        with db.write(self._conn) as c:
            shots = [r[0] for r in c.execute("SELECT shot_id FROM sb_shots WHERE project_id = ?", (project_id,))]
            for i in range(0, len(shots), 500):
                part = shots[i:i + 500]
                c.execute(f"DELETE FROM sb_versions WHERE shot_id IN ({','.join('?' * len(part))})", part)
            for table in ("sb_shots", "sb_scenes", "sb_messages", "sb_boards"):
                c.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        return len(shots)

    def remove_scene(self, scene_id: str) -> None:
        with db.write(self._conn) as c:
            c.execute("DELETE FROM sb_scenes WHERE scene_id = ?", (scene_id,))

    # ----------------------------------------------------------------------------------------------------------- shots
    def _shot(self, r) -> Shot:
        return Shot(r["shot_id"], r["project_id"], r["scene_id"], r["position"], r["version"], json.loads(r["spec"]), r["state"],
                    json.loads(r["assignment"]) if r["assignment"] else None, json.loads(r["checks"]) if r["checks"] else [], r["script_shot"], r["updated_at"])

    def shots(self, project_id: str) -> list[Shot]:
        """In story order: by scene, then by position in it."""
        scenes = {s.scene_id: s.position for s in self.scenes(project_id)}
        rows = [self._shot(r) for r in self._conn.execute("SELECT * FROM sb_shots WHERE project_id = ?", (project_id,))]
        return sorted(rows, key=lambda s: (scenes.get(s.scene_id, 1e9), s.position))

    def shot(self, shot_id: str) -> Shot | None:
        r = self._conn.execute("SELECT * FROM sb_shots WHERE shot_id = ?", (shot_id,)).fetchone()
        return self._shot(r) if r else None

    def add_shot(self, project_id: str, scene_id: str, spec: dict, *, position: float, made_by: str, note: str | None = None) -> str:
        shot_id = new_id("sbs")
        now = time.time()
        with db.write(self._conn) as c:
            c.execute("INSERT INTO sb_shots (shot_id, project_id, scene_id, position, version, spec, state, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      (shot_id, project_id, scene_id, position, 1, json.dumps(spec, ensure_ascii=False), "planned", now))
            c.execute("INSERT INTO sb_versions (shot_id, version, spec, made_by, note, at) VALUES (?,?,?,?,?,?)",
                      (shot_id, 1, json.dumps(spec, ensure_ascii=False), made_by, note, now))
        return shot_id

    def revise(self, shot_id: str, spec: dict, *, made_by: str, note: str | None = None, state: str | None = None) -> int:
        """A new version of a shot's spec. An accepted or checked shot whose spec changes is stale: its picture is checked again."""
        now = time.time()
        with db.write(self._conn) as c:
            row = c.execute("SELECT version, state, assignment FROM sb_shots WHERE shot_id = ?", (shot_id,)).fetchone()
            version = row["version"] + 1
            new_state = state or ("stale" if row["assignment"] and row["state"] in ("accepted", "needs", "stale") else row["state"])
            c.execute("UPDATE sb_shots SET spec = ?, version = ?, state = ?, updated_at = ? WHERE shot_id = ?",
                      (json.dumps(spec, ensure_ascii=False), version, new_state, now, shot_id))
            c.execute("INSERT INTO sb_versions (shot_id, version, spec, made_by, note, at) VALUES (?,?,?,?,?,?)",
                      (shot_id, version, json.dumps(spec, ensure_ascii=False), made_by, note, now))
        return version

    def place(self, shot_id: str, *, scene_id: str, position: float) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE sb_shots SET scene_id = ?, position = ?, updated_at = ? WHERE shot_id = ?", (scene_id, position, time.time(), shot_id))

    def remove_shot(self, shot_id: str) -> None:
        with db.write(self._conn) as c:
            c.execute("DELETE FROM sb_shots WHERE shot_id = ?", (shot_id,))
            c.execute("DELETE FROM sb_versions WHERE shot_id = ?", (shot_id,))

    def set_state(self, shot_id: str, state: str, *, assignment: dict | None | bool = False, checks: list | None = None) -> None:
        """The Director's word on a shot: its state, and (when given) the picture it was given and how it measured."""
        assert state in STATES
        with db.write(self._conn) as c:
            parts, args = ["state = ?", "updated_at = ?"], [state, time.time()]
            if assignment is not False:
                parts.append("assignment = ?"); args.append(json.dumps(assignment, ensure_ascii=False) if assignment else None)
            if checks is not None:
                parts.append("checks = ?"); args.append(json.dumps(checks, ensure_ascii=False))
            c.execute(f"UPDATE sb_shots SET {', '.join(parts)} WHERE shot_id = ?", (*args, shot_id))

    def link_script(self, shot_id: str, script_shot: str | None) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE sb_shots SET script_shot = ? WHERE shot_id = ?", (script_shot, shot_id))

    def versions(self, shot_id: str) -> list[dict]:
        return [{"version": r["version"], "spec": json.loads(r["spec"]), "made_by": r["made_by"], "note": r["note"], "at": r["at"]}
                for r in self._conn.execute("SELECT * FROM sb_versions WHERE shot_id = ? ORDER BY version DESC", (shot_id,))]

    # -------------------------------------------------------------------------------------------------------- messages
    def say(self, project_id: str, role: str, text: str, *, proposal: dict | None = None) -> str:
        message_id = new_id("sbm")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO sb_messages (message_id, project_id, role, text, proposal, status, at) VALUES (?,?,?,?,?,?,?)",
                      (message_id, project_id, role, text, json.dumps(proposal, ensure_ascii=False) if proposal else None, "open" if proposal else None, time.time()))
        return message_id

    def messages(self, project_id: str, *, limit: int = 200) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM sb_messages WHERE project_id = ? ORDER BY at DESC LIMIT ?", (project_id, limit)).fetchall()
        return [{"message_id": r["message_id"], "role": r["role"], "text": r["text"], "proposal": json.loads(r["proposal"]) if r["proposal"] else None,
                 "status": r["status"], "at": r["at"]} for r in reversed(rows)]

    def message(self, message_id: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM sb_messages WHERE message_id = ?", (message_id,)).fetchone()
        return {"message_id": r["message_id"], "project_id": r["project_id"], "role": r["role"], "text": r["text"],
                "proposal": json.loads(r["proposal"]) if r["proposal"] else None, "status": r["status"]} if r else None

    def settle(self, message_id: str, status: str) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE sb_messages SET status = ? WHERE message_id = ?", (status, message_id))
