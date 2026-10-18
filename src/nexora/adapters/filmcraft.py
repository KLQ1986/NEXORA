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
        return Capability(name="filmcraft", operations=("export", "inspect", "build"), runs="local")

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
            said = (done.stderr or done.stdout).strip()[-400:] or f"exit code {done.returncode}, nothing said"      # a crash says nothing; its code still does
            raise AdapterError(ErrorCode.INTERNAL, f"FilmCraft failed: {said}", retryable=False)
        try:
            return json.loads(lines[-1]) if lines else {}
        except ValueError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "FilmCraft answered with something that is not JSON") from None

    def _build(self, request: Request) -> Result:
        """A sequence built without a browser: FilmCraft's engine headless over MCP (stdio), one command at a time so each
        can name what an earlier one made ("$item:<name>" an imported file, "$clip" the clips just placed, "$tag:<t>" every
        clip placed under that tag), as the Edit step's page does. The media are imported from their files here and the
        saved document names them `/files/<name>`, as the browser editor does, so it opens there as it is."""
        verify(self._bin, fix="sh scripts/setup-filmcraft.sh")
        media = request.inputs["media"]                             # [{name, path}]
        commands = request.inputs["commands"]
        proc = subprocess.Popen([str(self._bin), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        n = 0

        def call(method: str, params: dict | None = None) -> dict:
            nonlocal n
            n += 1
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n")
            proc.stdin.flush()
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise AdapterError(ErrorCode.INTERNAL, "FilmCraft stopped while building", retryable=False)
                reply = json.loads(line)
                if reply.get("id") == n:
                    break
            if "error" in reply:
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"FilmCraft refused {params.get('arguments', {}).get('id') if params else method}: {reply['error'].get('message')}", retryable=False)
            content = (reply.get("result") or {}).get("content") or [{}]
            text = content[0].get("text") or "null"
            if (reply.get("result") or {}).get("isError"):
                raise AdapterError(ErrorCode.INVALID_REQUEST, f"FilmCraft refused {params['arguments']['id']}: {text[:300]}", retryable=False)
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}

        def run(cid: str, params: dict) -> dict:
            return call("tools/call", {"name": "command_run", "arguments": {"id": cid, "params": params}})

        try:
            call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "nexora", "version": "1"}})
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            run("file.newProject", {"name": "cut"})
            items = {}
            for m in media:
                made = run("file.import", {"paths": [str(m["path"])]})
                if made.get("errors"):
                    raise AdapterError(ErrorCode.MISSING_INPUT, f"FilmCraft could not import {m['name']}: {made['errors']}", retryable=False)
                items[m["name"]] = items[m["name"].split(".")[0]] = made["items"][0]
            clips, tags, refs = [], {}, {}

            def resolve(v):
                if isinstance(v, str) and v.startswith("$item:"):
                    return items[v[6:]]
                if isinstance(v, str) and v.startswith("$ref:"):
                    return refs[v[5:]]
                if isinstance(v, str) and v.startswith("$tag:"):
                    return tags.get(v[5:], [])
                if v == "$clip" or v == ["$clip"]:
                    return clips
                if isinstance(v, list):
                    return [resolve(x) for x in v]
                return v

            for c in commands:
                out = run(c["id"], {k: resolve(v) for k, v in c["params"].items()})
                if c["id"] == "timeline.place":
                    clips = list((out or {}).get("clips") or [])
                if c.get("tag"):
                    tags[c["tag"]] = tags.get(c["tag"], []) + clips
                if c.get("as"):                                      # what this command made, for later commands to name
                    refs[c["as"]] = (out or {}).get("bin") or (out or {}).get("item") or out
            with tempfile.TemporaryDirectory(prefix="nexora_cut_") as tmp:
                path = Path(tmp) / "cut.fcproj"
                run("file.saveAs", {"path": str(path)})
                document = path.read_text()
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.terminate()
            proc.wait(timeout=10)
        for m in media:                                             # the names the browser editor uses for these files
            document = document.replace(json.dumps(str(m["path"])), json.dumps(f"/files/{m['name']}"))
        return Result(outputs={"document": document, "commands": len(commands)})

    def submit(self, request: Request) -> Result:
        if request.operation == "build":
            return self._build(request)
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
