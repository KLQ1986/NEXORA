"""What macOS can recognise by itself, on this machine and for nothing: Apple's Vision framework for pictures (people, faces,
poses, animals, text, horizon, salient regions, a classification among about 1,300 labels, an aesthetic score, a feature print)
and SoundAnalysis for sound (about 300 kinds). Both run through one small Swift program, `apple_see.swift`, compiled on first
use with the system's Swift compiler and kept beside the data. Where there is no Swift (another system), both adapters say so
and the stages that use them leave their fields unmeasured; nothing else is affected."""
import hashlib
import json
import platform
import shutil
import tempfile
import threading
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process

SOURCE = Path(__file__).with_name("apple_see.swift")
_build_lock = threading.Lock()


class AppleTool:
    """The compiled helper, built once per version of its source."""

    def __init__(self, tools_dir: str | Path):
        self._dir = Path(tools_dir)

    @property
    def binary(self) -> Path:
        digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()[:12]
        return self._dir / f"apple-see-{digest}"

    def available(self) -> bool:
        return platform.system() == "Darwin" and shutil.which("swiftc") is not None

    def ensure(self) -> Path:
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "Apple's frameworks need macOS with the Swift compiler (xcode-select --install)", retryable=False)
        target = self.binary
        with _build_lock:
            if not target.is_file():
                self._dir.mkdir(parents=True, exist_ok=True)
                partial = target.with_name(target.name + ".partial")
                done = run_process(["swiftc", "-O", str(SOURCE), "-o", str(partial)], timeout=600)
                if done.returncode != 0 or not partial.is_file():
                    raise AdapterError(ErrorCode.UNAVAILABLE, f"the helper could not be built: {done.stderr.strip()[-300:]}", retryable=False)
                partial.replace(target)
                for old in self._dir.glob("apple-see-*"):
                    if old != target:
                        old.unlink(missing_ok=True)
        return target

    def environment(self) -> dict:
        return {"available": self.available(), "built": self.binary.is_file()}


class AppleVision(Adapter):
    """`look`: one record per picture (see apple_see.swift for its fields)."""

    def __init__(self, tool: AppleTool):
        self._tool = tool

    def describe(self) -> Capability:
        return Capability(name="vision", operations=("look", "read"), runs="local")

    def environment(self) -> dict:
        return self._tool.environment()

    def submit(self, request: Request) -> Result:
        paths = [str(p) for p in request.inputs["images"]]
        missing = [p for p in paths if not Path(p).is_file()]
        if missing:
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{missing[0]} does not exist")
        if not paths:
            return Result(outputs={"pictures": []})
        binary = self._tool.ensure()
        with tempfile.TemporaryDirectory() as work:
            listing = Path(work) / "frames.json"
            listing.write_text(json.dumps(paths), encoding="utf-8")
            done = run_process([str(binary), request.operation, str(listing)], timeout=request.deadline_seconds or 60 + 5 * len(paths))
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INTERNAL, f"the picture helper failed: {done.stderr.strip()[-200:]}")
        pictures = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
        if len(pictures) != len(paths):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"{len(pictures)} answers for {len(paths)} pictures")
        return Result(outputs={"pictures": pictures})


class AppleSound(Adapter):
    """`listen`: what kind of sound each window of a recording holds, the five likeliest kinds with their confidence."""

    def __init__(self, tool: AppleTool):
        self._tool = tool

    def describe(self) -> Capability:
        return Capability(name="sound", operations=("listen",), runs="local")

    def environment(self) -> dict:
        return self._tool.environment()

    def submit(self, request: Request) -> Result:
        source = Path(request.inputs["path"])
        if not source.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, f"{source} does not exist")
        binary = self._tool.ensure()
        timeout = request.deadline_seconds or 3600
        window, hop = float(request.params.get("window", 1.0)), float(request.params.get("hop", 0.5))
        with tempfile.TemporaryDirectory() as work:
            wav = Path(work) / "sound.wav"
            made = run_process(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(wav)], timeout=timeout)
            if made.returncode != 0 or not wav.is_file():
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"no sound could be read from {source.name}")
            done = run_process([str(binary), "listen", str(wav), f"{window:g}", f"{hop:g}"], timeout=timeout)
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INTERNAL, f"the sound helper failed: {done.stderr.strip()[-200:]}")
        line = next((l for l in done.stdout.splitlines() if l.startswith("{")), None)
        if line is None:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the sound helper gave no answer")
        return Result(outputs={"windows": json.loads(line)["windows"], "window": window, "hop": hop})
