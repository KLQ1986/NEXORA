"""What NEXORA keeps on disk, and which of it can be thrown away because it is rebuilt on demand."""
from pathlib import Path

# Folders under the media directory that hold nothing but results of earlier work on the same inputs.
CACHES = {"segments": "Các cảnh đã dựng sẵn", "narration": "Lời dẫn đã đọc", "captions": "Hình phụ đề", "focus": "Khung hình dùng để tìm chủ thể"}


def _size(folder: Path) -> tuple[int, int]:
    files = [f for f in folder.rglob("*") if f.is_file()] if folder.is_dir() else []
    return sum(f.stat().st_size for f in files), len(files)


def usage(media_dir: str | Path, *, renders_in_use: set[str]) -> list[dict]:
    media = Path(media_dir)
    out = [{"key": key, "label": label, "bytes": _size(media / key)[0], "files": _size(media / key)[1], "cleanable": True} for key, label in CACHES.items()]
    renders = [f for f in (media / "renders").glob("*") if f.is_file()] if (media / "renders").is_dir() else []
    orphans = [f for f in renders if str(f) not in renders_in_use]
    out.append({"key": "orphan_renders", "label": "Bản dựng không còn thuộc dự án nào", "bytes": sum(f.stat().st_size for f in orphans), "files": len(orphans), "cleanable": True})
    kept = sum(f.stat().st_size for f in renders) - out[-1]["bytes"]
    out.append({"key": "renders", "label": "Bản dựng của các dự án", "bytes": kept, "files": len(renders) - len(orphans), "cleanable": False})
    rest = _size(media)[0] - sum(o["bytes"] for o in out)
    out.append({"key": "derived", "label": "Bản xem, ảnh đại diện và khung hình của footage", "bytes": max(0, rest), "files": 0, "cleanable": False})
    return out


def clean(media_dir: str | Path, keys: list[str], *, renders_in_use: set[str]) -> int:
    """Delete the chosen caches. Returns the number of bytes freed. Nothing a project still shows is touched."""
    media, freed = Path(media_dir), 0
    for key in keys:
        if key in CACHES:
            targets = [f for f in (media / key).rglob("*") if f.is_file()]
        elif key == "orphan_renders":
            targets = [f for f in (media / "renders").glob("*") if f.is_file() and str(f) not in renders_in_use]
        else:
            raise ValueError(f"not a cleanable store: {key}")
        for f in targets:
            freed += f.stat().st_size
            f.unlink()
    return freed
