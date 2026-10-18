"""Text work on Claude through the operator's Claude Code login (`claude -p`): writing on the operator's plan, with Opus, and
looking a subject up on the web for a script from a topic.

Each request is one stateless `claude -p` run in a directory of its own. The operator's own Claude Code setup (CLAUDE.md, hooks,
plugins, MCP servers) is kept out, and so is ANTHROPIC_API_KEY: with it in the environment the run would bill the API, not the
plan. A writing request has no tools at all; research may only read the web. NEXORA writes nothing on Claude Code's word: it
gets an answer back and checks it. Budgets record no cost, since the plan is not money spent through NEXORA; the CLI's list-price
estimate is kept as the API-equivalent.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from nexora.adapters.claude import _json_from
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result, Usage

LIMIT_HINTS = ("rate limit", "usage limit", "limit reached", "overloaded", "429")
AUTH_HINTS = ("/login", "not logged in", "invalid api key", "authentication", "oauth")
JSON_ONLY = "\n\nChỉ trả về một đối tượng JSON, không kèm lời giải thích."


def find_claude() -> str | None:
    return shutil.which("claude")


class ClaudeCode(Adapter):
    def __init__(self, binary: str = "claude", *, model: str = "opus", effort: str = "high", chat_seconds: float = 180.0,
                 research_seconds: float = 900.0, workdir: str | Path | None = None):
        self._binary, self._model, self._effort = binary, model, effort
        self._seconds = {"chat": chat_seconds, "research": research_seconds}
        self._workdir = Path(workdir) if workdir else Path(tempfile.gettempdir()) / "nexora_claude_code"

    def describe(self) -> Capability:
        return Capability(name="model.claude_code", operations=("chat", "research"), runs="cloud")

    def environment(self) -> dict:
        return {"binary": self._binary, "model": self._model, "effort": self._effort}

    def check(self) -> dict:
        try:
            out = subprocess.run([self._binary, "--version"], capture_output=True, text=True, timeout=20)
            return {"ok": out.returncode == 0, "detail": out.stdout.strip() or out.stderr.strip()[:120]}
        except (OSError, subprocess.TimeoutExpired) as err:
            return {"ok": False, "detail": f"không chạy được {self._binary}: {err}"}

    def submit(self, request: Request) -> Result:
        op, params = request.operation, request.params
        schema = params.get("schema")
        if op == "research" and not schema:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "research needs a schema", retryable=False)
        prompt = params["prompt"] + (JSON_ONLY if params.get("json") and not schema else "")
        argv = [self._binary, "-p", "--output-format", "json", "--model", self._model, "--effort", self._effort,
                "--tools", "WebSearch,WebFetch" if op == "research" else "",
                "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
                "--system-prompt", params.get("system") or "Bạn là người viết kịch bản video tiếng Việt cho NEXORA."]
        if op == "research":
            argv += ["--allowedTools", "WebSearch,WebFetch"]
        if schema:
            argv += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        self._workdir.mkdir(parents=True, exist_ok=True)
        cwd = Path(tempfile.mkdtemp(prefix="run_", dir=self._workdir))
        try:
            done = subprocess.run(argv, input=prompt, capture_output=True, text=True, cwd=cwd, env=env,
                                  timeout=request.deadline_seconds or self._seconds.get(op, 180.0))
        except FileNotFoundError:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"Claude Code is not installed here ({self._binary})", retryable=False) from None
        except subprocess.TimeoutExpired:             # subprocess.run kills the child before raising
            raise AdapterError(ErrorCode.TIMEOUT, f"claude -p did not finish within {self._seconds.get(op, 180.0):.0f} s") from None
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        return self._read(done, op, bool(schema), bool(params.get("json")))

    def _read(self, done: subprocess.CompletedProcess, op: str, structured: bool, wants_json: bool) -> Result:
        try:
            data = json.loads(done.stdout)
        except json.JSONDecodeError:
            raise _failure((done.stderr or done.stdout or "").strip()[:300] or "claude -p ended with no answer") from None
        if data.get("is_error") or data.get("subtype") != "success":
            raise _failure(str(data.get("result") or data.get("subtype") or ""), data.get("api_error_status"))
        if data.get("stop_reason") == "refusal":
            raise AdapterError(ErrorCode.CONTENT_REJECTED, "Claude declined this request")
        used = data.get("usage") or {}
        usage = Usage(units=int(used.get("input_tokens", 0)) + int(used.get("output_tokens", 0)), cost=0.0, measured=bool(used))
        model = next(iter(data.get("modelUsage") or {}), self._model)
        base = {"provider": "claude_code", "model": model, "api_equivalent": float(data.get("total_cost_usd") or 0.0)}
        if structured:
            out = data.get("structured_output")
            if not isinstance(out, dict):
                raise AdapterError(ErrorCode.OUTPUT_INVALID, "Claude Code returned no structured output")
            return Result(outputs={**base, "json": out}, usage=usage)
        text = str(data.get("result") or "").strip()
        if not wants_json:
            return Result(outputs={**base, "text": text}, usage=usage)
        try:
            return Result(outputs={**base, "json": _json_from(text)}, usage=usage)
        except ValueError:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"the model did not return JSON: {text[:120]}") from None


def _failure(message: str, status: int | None = None) -> AdapterError:
    lowered = message.lower()
    if status == 429 or status == 529 or any(h in lowered for h in LIMIT_HINTS):
        reset = message.rsplit("|", 1)[-1]
        return AdapterError(ErrorCode.RATE_LIMITED, f"Claude Code: {message.split('|')[0]}",
                            retry_after=None if not reset.isdigit() else max(60.0, float(reset) - time.time()))
    if status in (401, 403) or any(h in lowered for h in AUTH_HINTS):
        return AdapterError(ErrorCode.AUTH, "Claude Code is not logged in: run `claude` once in a terminal and log in", retryable=False)
    if status is not None and status >= 500:
        return AdapterError(ErrorCode.UNAVAILABLE, f"Claude Code HTTP {status}: {message}")
    return AdapterError(ErrorCode.OUTPUT_INVALID, f"Claude Code: {message or 'no answer'}")
