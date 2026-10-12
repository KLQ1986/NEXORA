"""Publishing to a folder: the package is put, whole, into a place of the operator's choosing (a synced drive, a shared
folder, a card for another machine). It is the one destination that needs no account.

It is idempotent: every publication carries a key, the key is written beside the files, and asking again with the same
key finds what is already there instead of writing a second copy. `reconcile` answers, for a request whose outcome is
not known, whether it arrived.
"""
import json
import re
import shutil
import time
import unicodedata
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

MARKER = ".nexora-publication.json"


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:60] or "video"


class FolderPublisher(Adapter):
    def __init__(self, destination: str | Path):
        self._root = Path(destination).expanduser()

    def describe(self) -> Capability:
        return Capability(name="publish.folder", operations=("publish",), runs="local", supports_reconcile=True)

    def environment(self) -> dict:
        return {"destination": str(self._root), "writable": self._root.is_dir() or self._root.parent.is_dir()}

    def _find(self, key: str) -> Path | None:
        if not self._root.is_dir():
            return None
        for marker in self._root.glob(f"*/{MARKER}"):
            try:
                if json.loads(marker.read_text(encoding="utf-8")).get("key") == key:
                    return marker.parent
            except (OSError, ValueError):
                continue
        return None

    def reconcile(self, request: Request) -> Result | None:
        found = self._find(request.idempotency_key or "")
        return Result(outputs={"url": found.as_uri()}, external_ref=str(found)) if found else None

    def submit(self, request: Request) -> Result:
        if not request.idempotency_key:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "a publication needs an idempotency key")
        already = self._find(request.idempotency_key)
        if already:
            return Result(outputs={"url": already.as_uri(), "existing": True}, external_ref=str(already))
        source = Path(request.inputs["folder"])
        files = [f for f in request.inputs["files"] if (source / f).is_file()]
        if not files:
            raise AdapterError(ErrorCode.MISSING_INPUT, "the package has no files to publish")
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            target = self._root / f"{time.strftime('%Y-%m-%d')}-{slug(request.inputs.get('title', ''))}"
            n = 1
            while target.exists():
                n += 1
                target = target.with_name(f"{target.name.rsplit('--', 1)[0]}--{n}")
            staging = target.with_name(target.name + ".partial")
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir()
            for name in files:
                shutil.copyfile(source / name, staging / name)
            (staging / "README.txt").write_text(f"{request.inputs.get('title', '')}\n\n{request.inputs.get('description', '')}\n", encoding="utf-8")
            (staging / MARKER).write_text(json.dumps({"key": request.idempotency_key, "at": time.time(), "files": files}), encoding="utf-8")
            staging.rename(target)                       # the folder appears complete or not at all
        except OSError as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"the destination cannot be written: {err}") from None
        return Result(outputs={"url": target.as_uri()}, external_ref=str(target), files=tuple(str(target / f) for f in files))
