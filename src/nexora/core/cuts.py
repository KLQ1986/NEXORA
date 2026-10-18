"""A project's cut, as the Edit step's editor (FilmCraft) saves it: every save a version, kept whole, listed and restorable
(design 2026-10-17, the Edit step on FilmCraft).

The cut is the `.fcproj` document: the storyboard is the plan it was built from, and nothing else holds the cut. A version is
never changed; restoring an old one saves it again as the newest. The media it names are NEXORA's own versions, as
`/files/<version id>.<ext>` (the editor's view of them in the browser), so the same document opens in the browser on proxies
and is rendered on this Mac on the originals.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS edit_cuts (cut_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, document TEXT NOT NULL,
    made_by TEXT NOT NULL, note TEXT, source TEXT, stats TEXT NOT NULL, created_at REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS edit_cuts_version ON edit_cuts (project_id, version)
"""
MEDIA = re.compile(r'"/files/(ver_[0-9a-zA-Z]+)[^"/]*"')
NAMES = re.compile(r'"/files/([^"/]+)"')


def media_of(document: str) -> list[str]:
    """The NEXORA versions a cut names, in the order it first names them."""
    return list(dict.fromkeys(MEDIA.findall(document)))


def files_of(document: str) -> list[str]:
    """Every file a cut names (`/files/<name>`): NEXORA versions, narration lines, the project's music."""
    return list(dict.fromkeys(NAMES.findall(document)))


def summary(document: str) -> dict:
    """What a cut holds, read from the document itself: its sequences, their length, clips and captions."""
    try:
        doc = json.loads(document)
    except ValueError as err:
        raise ValueError(f"not a FilmCraft project: {err}") from None
    if doc.get("format") is None or "project" not in doc:
        raise ValueError("not a FilmCraft project")
    items = (doc["project"].get("items") or {}).values()
    sequences = []
    for it in items:
        seq = (it.get("kind") or {}).get("Sequence")
        if not seq:
            continue
        clips = sum(len(t.get("items") or []) for t in seq.get("video_tracks") or [])
        captions = sum(len(t.get("captions") or t.get("items") or []) for t in seq.get("caption_tracks") or [])
        sequences.append({"name": it.get("name"), "video_clips": clips, "captions": captions})
    return {"schema": doc.get("schema_version"), "sequences": sequences, "media": len(media_of(document))}


class CutStore:
    def __init__(self, db_path: str | Path):
        self._db = db.LocalConnections(db_path)
        conn = self._db.get()
        with db.write(conn) as c:
            for statement in SCHEMA.strip().split(";\n"):
                if statement.strip():
                    c.execute(statement)

    @property
    def _conn(self):
        return self._db.get()

    def save(self, project_id: str, document: str, *, made_by: str, note: str | None = None, source: str | None = None) -> dict:
        """The cut as it now stands, as the project's next version. Refused when it is not a FilmCraft project."""
        stats = summary(document)
        with db.write(self._conn) as c:
            version = c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM edit_cuts WHERE project_id = ?", (project_id,)).fetchone()[0]
            cut_id = new_id("cut")
            c.execute("INSERT INTO edit_cuts (cut_id, project_id, version, document, made_by, note, source, stats, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (cut_id, project_id, version, document, made_by, (note or "").strip() or None, source, json.dumps(stats, ensure_ascii=False), time.time()))
        return self.get(cut_id)

    def _row(self, r) -> dict:
        return {"cut_id": r["cut_id"], "project_id": r["project_id"], "version": r["version"], "made_by": r["made_by"], "note": r["note"],
                "source": r["source"], "stats": json.loads(r["stats"]), "created_at": r["created_at"]}

    def get(self, cut_id: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM edit_cuts WHERE cut_id = ?", (cut_id,)).fetchone()
        return self._row(r) if r else None

    def document(self, cut_id: str) -> str | None:
        r = self._conn.execute("SELECT document FROM edit_cuts WHERE cut_id = ?", (cut_id,)).fetchone()
        return r[0] if r else None

    def versions(self, project_id: str) -> list[dict]:
        """The project's cuts, newest first."""
        return [self._row(r) for r in self._conn.execute("SELECT * FROM edit_cuts WHERE project_id = ? ORDER BY version DESC", (project_id,))]

    def latest(self, project_id: str) -> dict | None:
        return next(iter(self.versions(project_id)), None)

    def forget_project(self, project_id: str) -> int:
        """A project has been deleted: every version of its cut goes with it. Returns how many versions were dropped."""
        with db.write(self._conn) as c:
            return c.execute("DELETE FROM edit_cuts WHERE project_id = ?", (project_id,)).rowcount

    def restore(self, project_id: str, version: int, *, made_by: str) -> dict:
        """An earlier version saved again as the newest; nothing is overwritten."""
        r = self._conn.execute("SELECT document FROM edit_cuts WHERE project_id = ? AND version = ?", (project_id, int(version))).fetchone()
        if r is None:
            raise LookupError(version)
        return self.save(project_id, r[0], made_by=made_by, note=f"quay lại v{int(version)}", source="restore")
