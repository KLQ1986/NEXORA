"""Pictures and words in one space (SigLIP 2): a frame and a sentence that says what is in it come out close. Lets a search find
what is in the picture even when the description never mentioned it (measured on 0050 and 0038, design 2026-10-15 §7).

The model runs in an environment of its own, made by `scripts/setup-pictures.sh`, through `siglip_helper.py`, started once
and kept running so that a search does not wait for the model to load. Without that environment the adapter says so, and
search goes on by the descriptions alone."""
import json
import select
import subprocess
import threading
import time
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

HELPER = Path(__file__).with_name("siglip_helper.py")


class PictureText(Adapter):
    """`images`: one unit vector a picture. `texts`: one unit vector a text, comparable with the pictures' by a dot product."""

    def __init__(self, python: str | Path, model: str, *, load_seconds: float = 300.0):
        self._python, self.model, self._load_seconds = Path(python), model, load_seconds
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def describe(self) -> Capability:
        return Capability(name="picture_text", operations=("images", "texts"), runs="local")

    def available(self) -> bool:
        return self._python.is_file()

    def environment(self) -> dict:
        return {"available": self.available(), "model": self.model, "running": self._proc is not None and self._proc.poll() is None}

    def submit(self, request: Request) -> Result:
        if request.operation == "images":
            paths = [str(p) for p in request.inputs["images"]]
            missing = [p for p in paths if not Path(p).is_file()]
            if missing:
                raise AdapterError(ErrorCode.MISSING_INPUT, f"{missing[0]} does not exist")
            if not paths:
                return Result(outputs={"vectors": [], "model": self.model})
            asked = {"op": "images", "paths": paths}
        elif request.operation == "texts":
            asked = {"op": "texts", "texts": list(request.inputs["texts"])}
        else:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        answer = self._ask(asked, timeout=request.deadline_seconds or 60 + 0.5 * len(asked.get("paths", ())))
        if "error" in answer:
            raise AdapterError(ErrorCode.INTERNAL, f"the picture model failed: {answer['error'][-200:]}")
        return Result(outputs={"vectors": answer["vectors"], "model": self.model})

    def _ask(self, asked: dict, *, timeout: float) -> dict:
        with self._lock:
            proc = self._start()
            try:
                proc.stdin.write(json.dumps(asked) + "\n")
                proc.stdin.flush()
                line = _read_line(proc, timeout)
            except (OSError, AdapterError):
                self._stop()                          # a helper that stopped answering is started afresh next time
                raise
            if line is None:
                self._stop()
                raise AdapterError(ErrorCode.UNAVAILABLE, "the picture model stopped", retryable=True)
            return json.loads(line)

    def _start(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "the picture model is not set up (scripts/setup-pictures.sh)", retryable=False)
        self._proc = subprocess.Popen([str(self._python), "-I", str(HELPER), self.model], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1)
        ready = _read_line(self._proc, self._load_seconds)
        if ready is None or "ready" not in ready:
            self._stop()
            raise AdapterError(ErrorCode.UNAVAILABLE, "the picture model could not be loaded", retryable=True)
        return self._proc

    def _stop(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait()
            self._proc = None

    def close(self) -> None:
        with self._lock:
            self._stop()


def _read_line(proc: subprocess.Popen, timeout: float) -> str | None:
    """The helper's next line, skipping anything that is not a JSON answer; None if it ended or did not answer in time."""
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AdapterError(ErrorCode.TIMEOUT, "the picture model did not answer in time", retryable=True)
        ready, _, _ = select.select([proc.stdout], [], [], left)
        if not ready:
            continue
        line = proc.stdout.readline()
        if not line:
            return None
        if line.startswith("{"):
            return line
