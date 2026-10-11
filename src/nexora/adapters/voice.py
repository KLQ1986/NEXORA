"""Narration with the voices built into macOS. Local, free, and good enough to time a cut."""
import wave
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process


class SayVoice(Adapter):
    def describe(self) -> Capability:
        return Capability(name="voice", operations=("speak",), runs="local")

    def environment(self) -> dict:
        done = run_process(["say", "-v", "?"], timeout=20)
        return {"vietnamese_voices": [line.split()[0] for line in done.stdout.splitlines() if "vi_VN" in line]}

    def submit(self, request: Request) -> Result:
        out = Path(request.params["out"])
        done = run_process(["say", "-v", request.params.get("voice", "Linh"), "-o", str(out), "--data-format=LEI16@48000", request.inputs["text"]],
                           timeout=request.deadline_seconds or 120)
        if done.returncode != 0 or not out.is_file():
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"say failed: {done.stderr.strip()[:200]}")
        with wave.open(str(out)) as w:
            return Result(outputs={"duration": w.getnframes() / w.getframerate()}, files=(str(out),))
