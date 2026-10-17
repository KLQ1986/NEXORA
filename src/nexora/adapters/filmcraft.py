"""FilmCraft's command-line engine (storytold/filmcraft, MIT OR Apache-2.0), for the Edit step's final render on this Mac
(design 2026-10-17): the project's cut, relinked to the originals, rendered on every core with the hardware encoder.

Measured on the M4, "Thử ghép A-G": 22 s of 1080p from 4K HEVC 10-bit originals in 11.4 s (VideoToolbox), 19 s from the
1080p proxies in software; the browser's own export took 160 s. The binary is the one pinned (signed with a Developer ID,
notarized); a different file is refused.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from nexora.adapters.pinned import FILMCRAFT_VERSION, verify
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result


class FilmCraft(Adapter):
    def __init__(self, data_dir: str | Path):
        self._bin = Path(data_dir) / "tools" / "filmcraft-cli" / FILMCRAFT_VERSION / "filmcraft-cli"

    def describe(self) -> Capability:
        return Capability(name="filmcraft", operations=("export", "inspect"), runs="local")

    def available(self) -> bool:
        return self._bin.is_file()

    def environment(self) -> dict:
        return {"available": self.available(), "version": FILMCRAFT_VERSION,
                "fix": None if self.available() else "sh scripts/setup-filmcraft.sh"}

    def _run(self, args: list[str], timeout: float) -> dict:
        verify(self._bin, fix="sh scripts/setup-filmcraft.sh")
        try:
            done = subprocess.run([str(self._bin), "--compact", *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdapterError(ErrorCode.TIMEOUT, "FilmCraft did not finish in time") from None
        lines = [line for line in done.stdout.splitlines() if line.strip().startswith("{")]
        if done.returncode != 0:
            raise AdapterError(ErrorCode.INTERNAL, f"FilmCraft failed: {(done.stderr or done.stdout).strip()[-400:]}", retryable=False)
        try:
            return json.loads(lines[-1]) if lines else {}
        except ValueError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "FilmCraft answered with something that is not JSON") from None

    def submit(self, request: Request) -> Result:
        document = request.inputs["document"]                       # the cut, its media already pointing at files on this Mac
        with tempfile.TemporaryDirectory(prefix="nexora_cut_") as tmp:
            project = Path(tmp) / "cut.fcproj"
            project.write_text(document)
            if request.operation == "inspect":
                return Result(outputs={"sequence": self._run(["--project", str(project), "inspect", "sequence"], 120)})
            if request.operation != "export":
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}", retryable=False)
            out = Path(request.params["out"])
            out.parent.mkdir(parents=True, exist_ok=True)
            # As NEXORA's own renders: captions drawn into the picture, loudness brought to −16 LUFS, the hardware encoder when there is one.
            settings = {"hardwareEncoding": "auto", "burnCaptions": True,
                        "effects": {"loudness": {"enabled": True, "target_lufs": -16.0, "true_peak_dbtp": -1.5}}, **(request.params.get("settings") or {})}
            made = self._run(["--project", str(project), "export", str(out), "--format", request.params.get("format", "h264"),
                              "--settings", json.dumps(settings)], float(request.params.get("timeout", 3600)))
        if not out.is_file():
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "FilmCraft finished without writing the file")
        if made.get("offlineMedia"):
            raise AdapterError(ErrorCode.MISSING_INPUT, f"the cut names media this Mac cannot read: {made['offlineMedia']}", retryable=False)
        return Result(outputs={"result": made.get("result") or {}}, files=(str(out),))
