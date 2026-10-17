"""Faces in stills, found and recovered, for Visual Quality (design 2026-10-16, wave 3).

- `find`: Apple Vision, through the frame helper (`apple_frames faces`): each face's box, its five points and Vision's
  capture quality.
- `restore`: the faces of a picture found again on that very picture (so a step after an enlargement has points that fit),
  then CodeFormer in its own environment (`faces_helper.py`, set up by `scripts/setup-faces.sh`), at a fidelity `weight`.

CodeFormer redraws a face: Visual Quality marks the step as generative and keeps it only where it measures better.
Measured on an M4 (2026-10-17): one face of a 640×360 frame in about 9 s on the CPU.
"""
import json
import subprocess
from pathlib import Path

from nexora.adapters.pinned import offline_env, verify
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

HELPER = Path(__file__).with_name("faces_helper.py")
MIN_FACE = 32                   # pixels: a face smaller than this has too little to align on


class Faces(Adapter):
    def __init__(self, env: str | Path, frames_binary: str | Path):
        self._env, self._frames = Path(env), Path(frames_binary)
        self._python, self._model = self._env / "bin" / "python", self._env / "models" / "codeformer.onnx"

    def describe(self) -> Capability:
        return Capability(name="restore_faces", operations=("find", "restore"), runs="local")

    def available(self) -> bool:
        return self._frames.is_file()

    def environment(self) -> dict:
        restore = self._python.is_file() and self._model.is_file()
        if not self.available():
            return {"available": False, "fix": "sh scripts/setup-apple-frames.sh"}
        return {"available": True, "find": True, "restore": restore, **({} if restore else {"fix": "sh scripts/setup-faces.sh"})}

    def _find(self, path: Path) -> dict:
        try:
            done = subprocess.run([str(self._frames), "faces", str(path)], capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise AdapterError(ErrorCode.TIMEOUT, "finding faces took too long", retryable=True) from None
        line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith("{")), None)
        answer = json.loads(line) if line else {}
        if done.returncode != 0 or "error" in answer:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"faces: {answer.get('error') or done.stderr.strip()[-200:]}", retryable=False)
        answer["faces"] = [f for f in answer.get("faces", []) if min(f["box"][2], f["box"][3]) >= MIN_FACE]
        return answer

    def submit(self, request: Request) -> Result:
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "faces need the Apple frame helper (sh scripts/setup-apple-frames.sh)", retryable=False)
        src = Path(request.inputs["path"])
        if request.operation == "find":
            return Result(outputs=self._find(src))
        if request.operation != "restore":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        if not (self._python.is_file() and self._model.is_file()):
            raise AdapterError(ErrorCode.UNAVAILABLE, "face recovery is not set up (sh scripts/setup-faces.sh)", retryable=False)
        p = request.params
        out = Path(p["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        verify(self._model, fix="sh scripts/setup-faces.sh")
        found = self._find(src)["faces"]
        args = {"model": str(self._model), "faces": [f["points"] for f in found],
                "weight": max(0.0, min(1.0, float(p.get("weight", 0.7)))), "blend": max(0.0, min(1.0, float(p.get("blend", 0.8))))}
        try:
            done = subprocess.run([str(self._python), "-I", str(HELPER), str(src), str(out), json.dumps(args)], capture_output=True, text=True,
                                  timeout=120 + 60 * len(found), env=offline_env())
        except subprocess.TimeoutExpired:
            raise AdapterError(ErrorCode.TIMEOUT, "face recovery took too long", retryable=True) from None
        line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith("{")), None)
        answer = json.loads(line) if line else {}
        if done.returncode != 0 or "error" in answer or not out.is_file():
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"face recovery: {answer.get('error') or done.stderr.strip()[-300:]}", retryable=False)
        return Result(outputs={**answer, "boxes": [f["box"] for f in found], "generative": True}, files=(str(out),))
