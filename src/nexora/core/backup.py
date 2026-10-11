"""Backups of the database: the one file that cannot be rebuilt from the footage."""
import sqlite3
import time
from pathlib import Path


def backup(db_path: str | Path, dest_dir: str | Path, *, keep: int = 7, now: float | None = None) -> Path:
    """Copy the live database with SQLite's online backup, which is safe while workers write. Keeps the newest `keep` copies."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    out = dest_dir / f"nexora-{stamp}.db"
    source, target = sqlite3.connect(db_path), sqlite3.connect(out)
    try:
        source.backup(target)
    finally:
        source.close(); target.close()
    for old in sorted(dest_dir.glob("nexora-*.db"), reverse=True)[keep:]:
        old.unlink()
    return out


def backups(dest_dir: str | Path) -> list[dict]:
    return [{"name": p.name, "size": p.stat().st_size, "created_at": p.stat().st_mtime} for p in sorted(Path(dest_dir).glob("nexora-*.db"), reverse=True)]


def restore(backup_file: str | Path, db_path: str | Path) -> Path:
    """Put a backup in place of the database. The database it replaces is kept beside it, never deleted. Run with the server stopped."""
    backup_file, db_path = Path(backup_file), Path(db_path)
    check = sqlite3.connect(backup_file)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(f"{backup_file} is damaged")
    finally:
        check.close()
    kept = db_path.with_name(f"{db_path.name}.before-restore-{time.strftime('%Y%m%d-%H%M%S')}")
    if db_path.is_file():
        db_path.replace(kept)
    for side in ("-wal", "-shm"):                      # leftovers of the replaced database must not be applied to the restored one
        Path(str(db_path) + side).unlink(missing_ok=True)
    source, target = sqlite3.connect(backup_file), sqlite3.connect(db_path)
    try:
        source.backup(target)
    finally:
        source.close(); target.close()
    return kept
