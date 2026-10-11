"""Shared production records: projects, versioned scripts with shots, selections and renders (design v4.0, section 8).

Planning writes scripts, Sourcing writes selections, Edit reads both and writes renders; they meet here, not in each other.
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id


@dataclass(frozen=True)
class Shot:
    shot_id: str
    script_id: str
    position: int
    text: str


@dataclass(frozen=True)
class Selection:
    shot_id: str
    status: str                 # proposed, accepted or gap
    asset_id: str | None
    moment_id: str | None
    t_in: float | None
    t_out: float | None
    score: float | None
    reason: str | None
    alternates: list
    decided_by: str


class ProjectStore:
    def __init__(self, path: str | Path):
        self._db = db.LocalConnections(path)

    @property
    def _conn(self):
        return self._db.get()

    def create_project(self, title: str, *, format: str = "landscape") -> str:
        project_id = new_id("prj")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO projects (project_id, title, format, created_at) VALUES (?,?,?,?)", (project_id, title, format, time.time()))
        return project_id

    def update_project(self, project_id: str, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("title", "format", "music_path")}
        with db.write(self._conn) as c:
            for key, value in allowed.items():
                c.execute(f"UPDATE projects SET {key} = ? WHERE project_id = ?", (value, project_id))

    def projects(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM projects ORDER BY created_at DESC, project_id DESC")]

    def project(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def save_script(self, project_id: str, lines: list[str]) -> str:
        """A script is never edited in place: saving creates the next version."""
        script_id = new_id("scr")
        with db.write(self._conn) as c:
            version = c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE project_id = ?", (project_id,)).fetchone()[0]
            c.execute("INSERT INTO scripts (script_id, project_id, version, created_at) VALUES (?,?,?,?)", (script_id, project_id, version, time.time()))
            for position, text in enumerate(line.strip() for line in lines if line.strip()):
                c.execute("INSERT INTO shots (shot_id, script_id, position, text) VALUES (?,?,?,?)", (new_id("sht"), script_id, position, text))
        return script_id

    def script(self, script_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM scripts WHERE script_id = ?", (script_id,)).fetchone()
        if row is None:
            return None
        shots = [Shot(r["shot_id"], r["script_id"], r["position"], r["text"])
                 for r in self._conn.execute("SELECT * FROM shots WHERE script_id = ? ORDER BY position", (script_id,))]
        return {**dict(row), "match_approved": bool(row["match_approved"]), "shots": shots}

    def current_script(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT script_id FROM scripts WHERE project_id = ? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
        return self.script(row[0]) if row else None

    def set_match_approved(self, script_id: str, approved: bool) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE scripts SET match_approved = ? WHERE script_id = ?", (int(approved), script_id))

    def set_selection(self, shot_id: str, *, status: str, asset_id=None, moment_id=None, t_in=None, t_out=None, score=None,
                      reason=None, alternates=None, decided_by: str = "system") -> None:
        with db.write(self._conn) as c:
            c.execute("INSERT INTO selections (shot_id, status, asset_id, moment_id, t_in, t_out, score, reason, alternates, decided_by) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(shot_id) DO UPDATE SET status=excluded.status, asset_id=excluded.asset_id, "
                      "moment_id=excluded.moment_id, t_in=excluded.t_in, t_out=excluded.t_out, score=excluded.score, reason=excluded.reason, "
                      "alternates=excluded.alternates, decided_by=excluded.decided_by",
                      (shot_id, status, asset_id, moment_id, t_in, t_out, score, reason, json.dumps(alternates or []), decided_by))

    def selection(self, shot_id: str) -> Selection | None:
        row = self._conn.execute("SELECT * FROM selections WHERE shot_id = ?", (shot_id,)).fetchone()
        return Selection(row["shot_id"], row["status"], row["asset_id"], row["moment_id"], row["t_in"], row["t_out"], row["score"],
                         row["reason"], json.loads(row["alternates"]), row["decided_by"]) if row else None

    def selections(self, script_id: str) -> list[Selection]:
        shots = self.script(script_id)["shots"]
        return [s for s in (self.selection(shot.shot_id) for shot in shots) if s is not None]

    def add_render(self, project_id: str, script_id: str, path: str, qc: dict) -> str:
        render_id = new_id("rnd")
        with db.write(self._conn) as c:
            c.execute("INSERT INTO renders (render_id, project_id, script_id, path, qc, created_at) VALUES (?,?,?,?,?,?)",
                      (render_id, project_id, script_id, path, json.dumps(qc), time.time()))
        return render_id

    def renders(self, project_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM renders WHERE project_id = ? ORDER BY created_at DESC, render_id DESC", (project_id,))
        return [{**dict(r), "qc": json.loads(r["qc"])} for r in rows]

    def render(self, render_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM renders WHERE render_id = ?", (render_id,)).fetchone()
        return {**dict(row), "qc": json.loads(row["qc"])} if row else None
