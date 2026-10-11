"""OpenMontage tools, called in a separate process (design v4.0, section 14.7).

OpenMontage is AGPL software with heavy dependencies. It is never imported here: each call starts a
child process in OpenMontage's own environment, sends the request as JSON and reads the result as
JSON. All code that touches OpenMontage lives in this one module, so it can be replaced as a unit.
"""
import json
import os
import sys
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.process import run_process

PINNED_COMMIT = "a2652b4"            # upgraded deliberately, never automatically
RUNNER = """
import json, sys
sys.path.insert(0, '.')
from tools.tool_registry import registry
registry.discover()
request = json.load(sys.stdin)
result = registry.get(request['tool']).execute(request['inputs'])
print('\\n@@NEXORA@@' + json.dumps({'success': result.success, 'data': result.data, 'artifacts': [str(a) for a in (result.artifacts or [])],
                                     'error': result.error, 'cost_usd': result.cost_usd}, default=str))
"""
DEPENDENCIES = ["requests", "pyyaml", "pydantic", "jsonschema", "python-dotenv", "numpy", "pillow"]
KEYLESS_SOURCES = ["archive_org", "nasa", "wikimedia"]


class OpenMontageStock(Adapter):
    """Free stock footage through OpenMontage's stock sources that need no API key."""

    def __init__(self, repo: str | Path = "~/openmontage"):
        self._repo = Path(repo).expanduser()

    def describe(self) -> Capability:
        return Capability(name="stock", operations=("search",), runs="cloud")

    def environment(self) -> dict:
        if not (self._repo / "tools" / "tool_registry.py").is_file():
            return {"installed": False}
        head = run_process(["git", "-C", str(self._repo), "rev-parse", "--short", "HEAD"], timeout=10).stdout.strip()
        return {"installed": True, "commit": head, "pinned": PINNED_COMMIT, "matches_pin": head.startswith(PINNED_COMMIT)}

    def submit(self, request: Request) -> Result:
        if not self._repo.is_dir():
            raise AdapterError(ErrorCode.UNAVAILABLE, f"OpenMontage is not installed at {self._repo}", retryable=False)
        out_dir = Path(request.params["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {"tool": "direct_clip_search", "inputs": {
            "output_dir": str(out_dir), "queries": [{"query": q, "kind": "video"} for q in request.inputs["queries"]], "sources": request.params.get("sources", KEYLESS_SOURCES),
            "clips_per_query": int(request.params.get("clips_per_query", 1)), "extract_thumbnails": False,
            "timeout_seconds": int(request.params.get("search_seconds", 90))}}
        cmd = ["uv", "run", "-q", "--no-project", *[a for dep in DEPENDENCIES for a in ("--with", dep)], "python", "-I", "-c", RUNNER]
        done = run_process(cmd, timeout=request.deadline_seconds or 240, cwd=str(self._repo), stdin=json.dumps(payload))
        marker = done.stdout.rfind("@@NEXORA@@")
        if done.returncode != 0 or marker < 0:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"the OpenMontage tool did not answer: {done.stderr.strip()[-200:]}")
        answer = json.loads(done.stdout[marker + len("@@NEXORA@@"):])
        if not answer["success"]:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"OpenMontage: {answer['error']}")
        clips = [c for c in (answer["data"] or {}).get("clips", []) if c.get("local_path") or c.get("path")]
        return Result(outputs={"clips": clips, "raw": {k: v for k, v in (answer["data"] or {}).items() if k != "clips"}},
                      files=tuple(str(c.get("local_path") or c.get("path")) for c in clips))
