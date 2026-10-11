"""The asset store: logical assets, immutable versions, storage volumes and lineage (design v4.0, section 8).

Media-agnostic: it knows files, checksums and parents, not what a video is. A location is a volume
plus a relative path, never an absolute path, so that a drive mounted elsewhere can be relinked.
"""
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from nexora.core import db
from nexora.core.ids import new_id


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class AssetVersion:
    version_id: str
    asset_id: str
    role: str
    volume_id: str
    relative_path: str
    checksum: str | None
    size: int
    metadata: dict
    parents: tuple[str, ...]
    created_by_attempt_id: str | None


def _version(row) -> AssetVersion:
    return AssetVersion(row["version_id"], row["asset_id"], row["role"], row["volume_id"], row["relative_path"], row["checksum"],
                        row["size"], json.loads(row["metadata"]), tuple(json.loads(row["parents"])), row["created_by_attempt_id"])


def _abs(path: str | Path) -> Path:
    return Path(os.path.abspath(path))


class AssetStore:
    def __init__(self, path: str | Path):
        self._db = db.LocalConnections(path)

    @property
    def _conn(self):
        return self._db.get()

    # ------------------------------------------------------------------ volumes
    def add_volume(self, name: str, mount_path: str | Path, *, kind: str = "internal") -> str:
        mount = str(_abs(mount_path))
        with db.write(self._conn) as c:
            row = c.execute("SELECT volume_id FROM volumes WHERE mount_path = ?", (mount,)).fetchone()
            if row:
                return row[0]
            volume_id = new_id("vol")
            c.execute("INSERT INTO volumes (volume_id, name, kind, mount_path, created_at) VALUES (?,?,?,?,?)",
                      (volume_id, name, kind, mount, time.time()))
            return volume_id

    def volume_online(self, volume_id: str) -> bool:
        return Path(self._mount(volume_id)).is_dir()

    def relink_volume(self, volume_id: str, mount_path: str | Path) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE volumes SET mount_path = ? WHERE volume_id = ?", (str(_abs(mount_path)), volume_id))

    def _mount(self, volume_id: str) -> str:
        return self._conn.execute("SELECT mount_path FROM volumes WHERE volume_id = ?", (volume_id,)).fetchone()[0]

    def _locate(self, path: Path) -> tuple[str, str]:
        """The volume that contains `path` and the path relative to it; a new volume for its folder if none does."""
        rows = self._conn.execute("SELECT volume_id, mount_path FROM volumes ORDER BY LENGTH(mount_path) DESC").fetchall()
        for row in rows:
            if path.is_relative_to(row["mount_path"]):
                return row["volume_id"], path.relative_to(row["mount_path"]).as_posix()
        return self.add_volume(path.parent.name or "root", path.parent, kind="auto"), path.name

    # ------------------------------------------------------------------ assets and versions
    def create_asset(self, path: str | Path, *, kind: str, origin: str, privacy_class: str = "local_only") -> tuple[str, str]:
        """Register a file as the original of a new asset. The same location is never registered twice."""
        path = _abs(path)
        volume_id, rel = self._locate(path)
        with db.write(self._conn) as c:
            row = c.execute("SELECT asset_id, version_id FROM asset_versions WHERE volume_id = ? AND relative_path = ?",
                            (volume_id, rel)).fetchone()
            if row:
                return row["asset_id"], row["version_id"]
            now = time.time()
            asset_id, version_id = new_id("ast", now), new_id("ver", now)
            c.execute("INSERT INTO assets (asset_id, kind, origin, privacy_class, created_at) VALUES (?,?,?,?,?)",
                      (asset_id, kind, origin, privacy_class, now))
            c.execute("INSERT INTO asset_versions (version_id, asset_id, role, volume_id, relative_path, size, created_at) "
                      "VALUES (?,?,?,?,?,?,?)", (version_id, asset_id, "original", volume_id, rel, path.stat().st_size, now))
            return asset_id, version_id

    def add_version(self, asset_id: str, path: str | Path, *, role: str, parents: list[str], attempt_id: str | None = None,
                    metadata: dict | None = None) -> str:
        """Register a derived file. Its checksum is computed here; registering the same location again is a no-op."""
        path = _abs(path)
        volume_id, rel = self._locate(path)
        checksum = sha256_file(path)
        with db.write(self._conn) as c:
            row = c.execute("SELECT version_id FROM asset_versions WHERE volume_id = ? AND relative_path = ?", (volume_id, rel)).fetchone()
            if row:
                return row[0]
            version_id = new_id("ver")
            c.execute("INSERT INTO asset_versions (version_id, asset_id, role, volume_id, relative_path, checksum, size, metadata, "
                      "parents, created_by_attempt_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (version_id, asset_id, role, volume_id, rel, checksum, path.stat().st_size, json.dumps(metadata or {}),
                       json.dumps(parents), attempt_id, time.time()))
            return version_id

    def set_checksum(self, version_id: str, checksum: str) -> None:
        with db.write(self._conn) as c:
            c.execute("UPDATE asset_versions SET checksum = ? WHERE version_id = ?", (checksum, version_id))

    def update_metadata(self, version_id: str, **values) -> None:
        with db.write(self._conn) as c:
            current = json.loads(c.execute("SELECT metadata FROM asset_versions WHERE version_id = ?", (version_id,)).fetchone()[0])
            current.update(values)
            c.execute("UPDATE asset_versions SET metadata = ? WHERE version_id = ?", (json.dumps(current), version_id))

    # ------------------------------------------------------------------ reads
    def version(self, version_id: str) -> AssetVersion:
        return _version(self._conn.execute("SELECT * FROM asset_versions WHERE version_id = ?", (version_id,)).fetchone())

    def versions(self, asset_id: str) -> list[AssetVersion]:
        return [_version(r) for r in self._conn.execute("SELECT * FROM asset_versions WHERE asset_id = ? ORDER BY seq", (asset_id,))]

    def original(self, asset_id: str) -> AssetVersion:
        return next(v for v in self.versions(asset_id) if v.role == "original")

    def assets(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM assets ORDER BY created_at DESC, asset_id DESC")]

    def path_of(self, version: AssetVersion) -> Path:
        return Path(self._mount(version.volume_id)) / version.relative_path

    def find_original_by_checksum(self, checksum: str, *, exclude_asset: str | None = None) -> str | None:
        row = self._conn.execute("SELECT asset_id FROM asset_versions WHERE checksum = ? AND role = 'original' AND asset_id != ? "
                                 "ORDER BY seq LIMIT 1", (checksum, exclude_asset or "")).fetchone()
        return row[0] if row else None
