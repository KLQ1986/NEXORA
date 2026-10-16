"""The catalogue: one code for every video and still the library holds, and the name it is shown by.

A code reads as KIND-YYMMDD-NNN:
  FT footage video · AN still image · AM sound or music · BN quick preview (bản nháp) · BD finished cut (bản dựng)
  YYMMDD is the day it was shot (footage, when the camera says so) or made (everything else),
  NNN counts the items of that kind on that day, from 001.
A code is given once and never changes, so it can be written on a slate, in a note or in a file name and always lead back.
Looking a code up returns everything known about it: the item, where it was used, what was published from it, the notes on it.
"""
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException

KINDS = {"FT": "footage", "AN": "image", "AM": "audio", "BN": "preview", "BD": "render"}
CODE = re.compile(r"^(FT|AN|AM|BN|BD)-\d{6}-\d{3,}$")


def _day(value) -> str:
    """YYMMDD from a timestamp or an ISO date; today when neither can be read."""
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).strftime("%y%m%d")
        if value:
            return datetime.fromisoformat(str(value)[:19].replace("Z", "")).strftime("%y%m%d")
    except (ValueError, OSError):
        pass
    return datetime.now().strftime("%y%m%d")


def add_catalog(app: FastAPI, system) -> None:
    path = Path(system.data_dir) / "catalog.db"
    lock = threading.Lock()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS catalog (code TEXT PRIMARY KEY, subject TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, title TEXT, made REAL NOT NULL)")
    conn.commit()

    def ai_title(asset_id: str) -> str | None:
        try:
            video = next((m for m in system.index.moments(asset_id) if m.level == "video"), None)
            return (video.data.get("detail", {}).get("tieu_de") or None) if video else None
        except Exception:
            return None

    def subjects() -> list[tuple[str, str, str, str]]:
        """(subject id, kind prefix, YYMMDD, default name) for everything the library holds now."""
        out = []
        for a in system.assets.assets(include_trashed=True):
            original = next((v for v in system.assets.versions(a["asset_id"]) if v.role == "original"), None)
            probe = original.metadata.get("probe", {}) if original else {}
            kind = "AM" if a.get("kind") == "audio" else "AN" if probe.get("still") or a.get("kind") == "image" else "FT"
            name = a.get("title") or (ai_title(a["asset_id"]) if kind == "FT" else None) or (Path(system.assets.path_of(original)).stem if original else a["asset_id"])
            out.append((a["asset_id"], kind, _day(probe.get("created") or a.get("created_at")), name))
        for p in system.projects.projects(include_trashed=True):
            for previews, kind in ((False, "BD"), (True, "BN")):
                cuts = sorted(system.projects.renders(p["project_id"], previews=previews), key=lambda r: r["created_at"])
                for k, r in enumerate(cuts, 1):
                    out.append((r["render_id"], kind, _day(r["created_at"]), f"{p['title']} v{k}" if kind == "BD" else f"{p['title']} (xem trước)"))
        return out

    def sync() -> None:
        with lock:
            known = {r[0] for r in conn.execute("SELECT subject FROM catalog")}
            fresh = [s for s in subjects() if s[0] not in known]
            for subject, kind, day, name in sorted(fresh, key=lambda s: (s[2], s[0])):
                prefix = f"{kind}-{day}-"
                last = conn.execute("SELECT code FROM catalog WHERE code LIKE ? ORDER BY code DESC LIMIT 1", (prefix + "%",)).fetchone()
                n = int(last[0].rsplit("-", 1)[1]) + 1 if last else 1
                conn.execute("INSERT INTO catalog (code, subject, kind, title, made) VALUES (?, ?, ?, ?, ?)", (f"{prefix}{n:03d}", subject, KINDS[kind], name, time.time()))
            conn.commit()

    def entry(code_or_subject: str) -> dict:
        row = conn.execute("SELECT * FROM catalog WHERE code = ? OR subject = ?", (code_or_subject.upper(), code_or_subject)).fetchone()
        if row is None:
            sync()
            row = conn.execute("SELECT * FROM catalog WHERE code = ? OR subject = ?", (code_or_subject.upper(), code_or_subject)).fetchone()
        if row is None:
            raise HTTPException(404, f"Không có mã {code_or_subject}")
        return dict(row)

    @app.get("/api/v1/catalog")
    def list_catalog():
        sync()
        return {"items": [dict(r) for r in conn.execute("SELECT code, subject, kind, title FROM catalog ORDER BY code")],
                "convention": "KIND-YYMMDD-NNN · FT footage · AN ảnh · AM âm thanh · BN bản nháp · BD bản dựng"}

    @app.patch("/api/v1/catalog/{code}")
    def rename(code: str, body: dict):
        item, title = entry(code), str(body.get("title", "")).strip()[:200]
        if not title:
            raise HTTPException(422, "Tên video không được để trống")
        with lock:
            conn.execute("UPDATE catalog SET title = ? WHERE code = ?", (title, item["code"]))
            conn.commit()
        if item["kind"] in ("footage", "image", "audio") and system.assets.asset(item["subject"]) is not None:
            system.library.annotate(item["subject"], title=title)       # the rest of the system shows the same name
        return entry(item["code"])

    @app.get("/api/v1/catalog/{code}")
    def look_up(code: str):
        """Everything related to one code, in one answer."""
        from nexora.api.app import asset_view
        item = entry(code)
        subject, out = item["subject"], {"entry": item}
        if item["kind"] in ("footage", "image", "audio"):
            asset = system.assets.asset(subject)
            out["asset"] = asset_view(system, asset) if asset else None
            video = next((m for m in system.index.moments(subject) if m.level == "video"), None) if asset else None
            out["summary"] = video.text if video else None
            used = system.projects.used_assets().get(subject, [])
            out["projects"] = [{"project_id": pid, "title": (system.projects.project(pid) or {}).get("title", "")} for pid in used]
            pubs = [x for pid in used for x in system.publishing.publications(project_id=pid)]
        else:
            render = system.projects.render(subject)
            out["render"] = {k: render[k] for k in ("render_id", "project_id", "created_at", "qc", "review") if k in render} if render else None
            project = system.projects.project(render["project_id"]) if render else None
            out["projects"] = [{"project_id": project["project_id"], "title": project["title"]}] if project else []
            pubs = [x for x in system.publishing.publications() if x.get("render_id") == subject]
        out["publications"] = [{k: x.get(k) for k in ("publication_id", "target", "status", "url", "title", "published_at")} for x in pubs]
        try:
            notes = json.loads((Path(system.data_dir) / "notes.json").read_text("utf-8"))
        except (FileNotFoundError, ValueError):
            notes = []
        out["notes"] = [n for n in notes if n.get("subject") == subject]
        cuts = [r["render_id"] for p in out["projects"] for r in system.projects.renders(p["project_id"])]      # the cuts made in the same projects
        related = [r[0] for r in conn.execute("SELECT code FROM catalog WHERE subject IN (SELECT value FROM json_each(?))", (json.dumps(cuts),))]
        out["related_codes"] = sorted(set(related) - {item["code"]})
        return out
