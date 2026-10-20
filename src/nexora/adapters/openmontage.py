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
# Stock without downloading: the candidates every source finds (each with its direct file, preview picture and terms), and
# the one file asked for, later. OpenMontage's own tools always download what they find; NEXORA judges previews first.
STOCK_RUNNER = """
import json, sys
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, '.')
from tools.video.stock_sources import all_sources, get_source, Candidate, SearchFilters
req = json.load(sys.stdin)
if req['op'] == 'candidates':
    found, errors = [], {}
    for source in all_sources():
        if source.name not in req['sources'] or not source.is_available():
            continue
        for query in req['queries']:
            try:
                found += [dict(asdict(c), query=query) for c in source.search(query, SearchFilters(kind='video', per_page=req['per_query']))]
            except Exception as err:
                errors[source.name] = str(err)[:200]
    out = {'candidates': found, 'errors': errors}
else:
    c = Candidate(**{k: v for k, v in req['candidate'].items() if k in Candidate.__dataclass_fields__})
    out = {'path': str(get_source(c.source).download(c, Path(req['out_path'])))}
print('\\n@@NEXORA@@' + json.dumps(out, default=str))
"""
DEPENDENCIES = ["requests", "pyyaml", "pydantic", "jsonschema", "python-dotenv", "numpy", "pillow"]
KEYLESS_SOURCES = ["archive_org", "nasa", "wikimedia"]
KEYED_SOURCES = {"pexels": "PEXELS_API_KEY", "pixabay_video": "PIXABAY_API_KEY"}     # free sign-up keys; a source joins when its key is set


class OpenMontageStock(Adapter):
    """Free stock footage through OpenMontage's stock sources: those that need no key, and Pexels and Pixabay once their keys are given."""

    def __init__(self, repo: str | Path = "~/openmontage", *, keys: dict[str, str] | None = None):
        self._repo = Path(repo).expanduser()
        self._keys = {source: key for source, key in (keys or {}).items() if key}

    def sources(self) -> list[str]:
        return [*self._keys, *KEYLESS_SOURCES]

    def describe(self) -> Capability:
        return Capability(name="stock", operations=("search", "candidates", "download"), runs="cloud")

    def environment(self) -> dict:
        if not (self._repo / "tools" / "tool_registry.py").is_file():
            return {"installed": False}
        head = run_process(["git", "-C", str(self._repo), "rev-parse", "--short", "HEAD"], timeout=10).stdout.strip()
        return {"installed": True, "commit": head, "pinned": PINNED_COMMIT, "matches_pin": head.startswith(PINNED_COMMIT)}

    def _run(self, runner: str, payload: dict, timeout: float) -> dict:
        cmd = ["uv", "run", "-q", "--no-project", *[a for dep in DEPENDENCIES for a in ("--with", dep)], "python", "-I", "-c", runner]
        env = {**os.environ, **{KEYED_SOURCES[source]: key for source, key in self._keys.items()}}
        env.pop("ANTHROPIC_API_KEY", None)
        done = run_process(cmd, timeout=timeout, cwd=str(self._repo), stdin=json.dumps(payload), env=env)
        marker = done.stdout.rfind("@@NEXORA@@")
        if done.returncode != 0 or marker < 0:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"the OpenMontage tool did not answer: {done.stderr.strip()[-200:]}")
        return json.loads(done.stdout[marker + len("@@NEXORA@@"):])

    def submit(self, request: Request) -> Result:
        if not self._repo.is_dir():
            raise AdapterError(ErrorCode.UNAVAILABLE, f"OpenMontage is not installed at {self._repo}", retryable=False)
        if request.operation == "candidates":
            # Pexels and Pixabay are asked by NEXORA itself (stock_api), in the operator's language; here the keyless libraries.
            answer = self._run(STOCK_RUNNER, {"op": "candidates", "queries": list(request.inputs["queries"]), "sources": request.params.get("sources") or KEYLESS_SOURCES,
                                              "per_query": int(request.params.get("per_query", 8))}, request.deadline_seconds or 120)
            return Result(outputs={"candidates": [candidate(c) for c in answer["candidates"]], "errors": answer.get("errors", {})})
        if request.operation == "download":
            c = request.inputs["candidate"]
            out_dir = Path(request.params["out_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            raw = {**(c.get("raw") or {}), "source": c["source"], "source_id": c["source_id"], "source_url": c["source_url"], "download_url": c["download_url"], "kind": "video"}
            answer = self._run(STOCK_RUNNER, {"op": "download", "candidate": raw, "out_path": str(out_dir / file_name(c))}, request.deadline_seconds or 600)
            return Result(outputs={"path": answer["path"]}, files=(answer["path"],))
        out_dir = Path(request.params["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {"tool": "direct_clip_search", "inputs": {
            "output_dir": str(out_dir), "queries": [{"query": q, "kind": "video"} for q in request.inputs["queries"]], "sources": request.params.get("sources") or self.sources(),
            "clips_per_query": int(request.params.get("clips_per_query", 1)), "extract_thumbnails": False,
            "timeout_seconds": int(request.params.get("search_seconds", 90))}}
        answer = self._run(RUNNER, payload, request.deadline_seconds or 240)
        if not answer["success"]:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"OpenMontage: {answer['error']}")
        clips = [c for c in (answer["data"] or {}).get("clips", []) if c.get("local_path") or c.get("path")]
        return Result(outputs={"clips": clips, "raw": {k: v for k, v in (answer["data"] or {}).items() if k != "clips"}},
                      files=tuple(str(c.get("local_path") or c.get("path")) for c in clips))


def candidate(c: dict) -> dict:
    """One OpenMontage `Candidate`, in the shape every stock source of NEXORA gives: what is needed to judge it, watch it from
    its source and fetch it later. The source's own fields are kept under `raw` for the download."""
    return {"source": c.get("source", ""), "source_id": str(c.get("source_id", "")), "source_url": c.get("source_url", ""),
            "download_url": c.get("download_url", ""), "preview_url": c.get("download_url", ""), "thumbnail_url": c.get("thumbnail_url", ""),
            "width": int(c.get("width") or 0), "height": int(c.get("height") or 0), "duration": float(c.get("duration") or 0.0),
            "creator": c.get("creator", ""), "license": c.get("license", ""), "tags": c.get("source_tags", ""), "query": c.get("query", ""),
            "raw": {k: v for k, v in c.items() if k not in ("query",)}}


def file_name(c: dict) -> str:
    """Where a fetched candidate is kept: its source and id, with the extension of its file."""
    ext = Path(c.get("download_url", "").split("?")[0]).suffix.lower()
    return f"{c['source']}_{c['source_id']}{ext if ext in ('.mp4', '.mov', '.webm', '.ogv', '.mkv', '.m4v') else '.mp4'}"
