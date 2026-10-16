"""Notes pinned to a moment of a recording or a cut: a remark, or a fault to be put right.

Kept beside the database as one small JSON file. A note names its subject (an asset or a render id), the second it is
about (or the stretch from one second to another), what it says, whether it is a remark or a fault, and whether the fault has since been put right.
"""
import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException

KINDS = ("note", "issue")


def add_notes(app: FastAPI, data_dir: Path) -> None:
    path = Path(data_dir) / "notes.json"
    lock = threading.Lock()

    def load() -> list[dict]:
        try:
            return json.loads(path.read_text("utf-8"))
        except (FileNotFoundError, ValueError):
            return []

    def save(notes: list[dict]) -> None:
        part = path.with_suffix(".json.part")
        part.write_text(json.dumps(notes, ensure_ascii=False, indent=1), "utf-8")
        part.replace(path)

    def second(value) -> float | None:
        if value is None or value == "":
            return None
        try:
            return max(0.0, round(float(value), 2))
        except (TypeError, ValueError):
            raise HTTPException(422, "Thời điểm phải là số giây")

    @app.get("/api/v1/notes")
    def list_notes(subject: str | None = None):
        notes = [n for n in load() if subject is None or n["subject"] == subject]
        return {"notes": sorted(notes, key=lambda n: (n["t"] is None, n["t"] or 0.0, n["at"]))}

    @app.post("/api/v1/notes", status_code=201)
    def add_note(body: dict):
        subject, text = str(body.get("subject", "")).strip(), str(body.get("text", "")).strip()
        if not subject or not text:
            raise HTTPException(422, "Ghi chú cần nói về cái gì và ghi điều gì")
        t, end = second(body.get("t")), second(body.get("t_end"))
        note = {"note_id": uuid.uuid4().hex[:12], "subject": subject, "t": t, "t_end": end if t is not None and end is not None and end > t else None, "text": text[:2000],
                "kind": body.get("kind") if body.get("kind") in KINDS else "note", "resolved": False, "at": time.time()}
        with lock:
            notes = load()
            notes.append(note)
            save(notes)
        return note

    @app.patch("/api/v1/notes/{note_id}")
    def change_note(note_id: str, body: dict):
        with lock:
            notes = load()
            note = next((n for n in notes if n["note_id"] == note_id), None)
            if note is None:
                raise HTTPException(404, "Không có ghi chú này")
            if "resolved" in body:
                note["resolved"] = bool(body["resolved"])
            if str(body.get("text", "")).strip():
                note["text"] = str(body["text"]).strip()[:2000]
            if body.get("kind") in KINDS:
                note["kind"] = body["kind"]
            save(notes)
        return note

    @app.delete("/api/v1/notes/{note_id}")
    def drop_note(note_id: str):
        with lock:
            notes = load()
            kept = [n for n in notes if n["note_id"] != note_id]
            if len(kept) == len(notes):
                raise HTTPException(404, "Không có ghi chú này")
            save(kept)
        return {"deleted": note_id}
