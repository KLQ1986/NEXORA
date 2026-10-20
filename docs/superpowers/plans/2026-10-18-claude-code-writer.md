# Claude Code as NEXORA's writer: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code (`claude -p`, on the operator's plan, Opus) writes NEXORA's scripts. It is a routable text model
for every writing task, and it is a researching writer that turns a topic into a sourced script, which NEXORA checks
and writes into the production and the video.

**Architecture:**
- A new adapter `model.claude_code` runs one stateless `claude -p` per request.
- A planning unit `modules/planning/topic.py` builds the prompt and schema, checks the package, and runs the pipeline
  `planning.topic_script` on its own lane `claude_code`.
- The composition root (`app.py`) applies a finished package: sources into the production and video, script lines with
  their notes.
- The Producer and Missions gain the kind `topic`. The script editor gains "Từ chủ đề…".

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL), pytest; React 19 + TypeScript + Vite; Claude Code CLI 2.1.302.

**Spec:** `docs/superpowers/specs/2026-10-18-claude-code-writer-design.md`

## Global Constraints

- `claude -p` always runs with `--output-format json --setting-sources "" --strict-mcp-config --no-session-persistence`,
  `--system-prompt <NEXORA's>`, and the prompt on stdin.
- `ANTHROPIC_API_KEY` is removed from the child's environment.
- Tools: `--tools ""` for `chat`; `--tools WebSearch,WebFetch` for `research`.
- Defaults: model `opus`, effort `high`, `chat` timeout 180 s, `research` timeout 900 s.
- Budgets record 0 USD for Claude Code. `total_cost_usd` is kept as `api_equivalent` in the outputs.
- At most one Claude Code pipeline stage runs at a time, on the lane `claude_code` with its own worker.
- Layers: core < modules < adapters < agents < api, enforced by import-linter. `modules/planning/topic.py` may import
  core only.
- Every UI string is Vietnamese with its English in `web/src/en.ts`. `npm run i18n:check` must report 0 missing.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `nexora.toml` or `data/`.

## Review Focus

1. **A `claude` run that hangs past its timeout** must be killed, not left running, and must raise `TIMEOUT`.
   Covered in Task 1 (fake binary that sleeps).
2. **The operator's own `ANTHROPIC_API_KEY`** must never reach the child process. Covered in Task 1 (the fake records
   its environment).
3. **A package whose fact line cites a source id that is not in the package** must be kept and marked "chưa có nguồn",
   never saved as sourced. Covered in Task 3.
4. **Saving the editor's script after a topic draft writes the sources once.** Saving again must not duplicate them,
   and a script saved with no topic draft must write none. Covered in Task 5.
5. **A topic mission on a machine without Claude Code** cannot be confirmed, and says why. Covered in Task 6.

---

### Task 1: The adapter `model.claude_code`

**Files:**
- Create: `src/nexora/adapters/claude_code.py`
- Create: `tests/adapters/test_claude_code.py`

**Interfaces:**
- Produces:
  - `ClaudeCode(binary: str = "claude", *, model: str = "opus", effort: str = "high", chat_seconds: float = 180, research_seconds: float = 900, workdir: str | Path | None = None)`
  - `describe()` returns `Capability(name="model.claude_code", operations=("chat", "research"), runs="cloud")`.
  - `submit(Request("chat", params={"prompt", "json"?, "system"?, "schema"?}))` returns `Result(outputs={"text"|"json", "provider": "claude_code", "model", "api_equivalent"})`.
  - `submit(Request("research", params={"prompt", "system", "schema"}))` returns `Result(outputs={"json", "provider", "model", "api_equivalent"})`.
  - `usage.cost == 0`; `usage.units` = input + output tokens.
  - `find_claude() -> str | None` returns the binary on PATH.

- [ ] **Step 1: Write the failing tests.** They use a fake `claude`: a Python script that records argv, stdin and env
  to `call.json`, then prints `$FAKE_ANSWER` (or sleeps when `FAKE_SLEEP` is set).

```python
"""Claude Code as a writer: one stateless `claude -p` per request, on the operator's plan, with the operator's own setup and
API key kept out. Tested against a fake `claude` that records how it was called."""
import json
import os
import stat
import sys

import pytest

from nexora.adapters.claude_code import ClaudeCode
from nexora.core.adapter import AdapterError, ErrorCode, Request

FAKE = """#!{python}
import json, os, sys, time
record = {{"argv": sys.argv[1:], "stdin": sys.stdin.read(), "env": dict(os.environ), "cwd": os.getcwd()}}
open(os.environ["FAKE_RECORD"], "w").write(json.dumps(record))
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
sys.stdout.write(os.environ.get("FAKE_ANSWER", ""))
sys.stderr.write(os.environ.get("FAKE_ERR", ""))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def answer(**over):
    base = {"type": "result", "subtype": "success", "is_error": False, "result": "xin chào", "stop_reason": "end_turn",
            "total_cost_usd": 0.0421, "usage": {"input_tokens": 1200, "output_tokens": 300}, "modelUsage": {"claude-opus-5-5": {}}}
    return json.dumps({**base, **over})


@pytest.fixture
def fake(tmp_path, monkeypatch):
    path = tmp_path / "claude"
    path.write_text(FAKE.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_RECORD", str(tmp_path / "call.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-reach-claude")
    recorded = lambda: json.loads((tmp_path / "call.json").read_text())
    return ClaudeCode(str(path), workdir=tmp_path / "runs"), recorded, monkeypatch


def test_a_chat_runs_without_tools_or_the_operators_setup_and_on_the_plan(fake):
    adapter, recorded, env = fake
    env.setenv("FAKE_ANSWER", answer(result='Đây: {"cau": ["Bữa nay trời đẹp."]}'))
    out = adapter.submit(Request("chat", params={"prompt": "Viết một câu.", "json": True, "system": "Bạn là người viết."}))
    call = recorded()
    argv = call["argv"]
    assert argv[0] == "-p" and argv[argv.index("--output-format") + 1] == "json" and argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv and argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--system-prompt") + 1] == "Bạn là người viết."
    assert "Viết một câu." in call["stdin"] and "Viết một câu." not in " ".join(argv)       # the prompt on stdin only
    assert "ANTHROPIC_API_KEY" not in call["env"]                                           # the plan, never the API key
    assert out.outputs["json"] == {"cau": ["Bữa nay trời đẹp."]} and out.outputs["api_equivalent"] == 0.0421
    assert out.usage.cost == 0 and out.usage.units == 1500


def test_research_may_only_read_the_web_and_answers_in_the_schema(fake):
    adapter, recorded, env = fake
    env.setenv("FAKE_ANSWER", answer(result="", structured_output={"title": "Rừng"}))
    schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
    out = adapter.submit(Request("research", params={"prompt": "Tìm hiểu.", "system": "S", "schema": schema}))
    argv = recorded()["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch" and json.loads(argv[argv.index("--json-schema") + 1]) == schema
    assert out.outputs["json"] == {"title": "Rừng"}


@pytest.mark.parametrize("over, code", [
    ({"is_error": True, "subtype": "error_during_execution", "result": "Claude AI usage limit reached|1760000000"}, ErrorCode.RATE_LIMITED),
    ({"is_error": True, "result": "Invalid API key · Please run /login", "subtype": "success"}, ErrorCode.AUTH),
    ({"is_error": True, "result": "Overloaded", "api_error_status": 529}, ErrorCode.RATE_LIMITED),
    ({"is_error": True, "result": "server error", "api_error_status": 500}, ErrorCode.UNAVAILABLE),
    ({"stop_reason": "refusal"}, ErrorCode.CONTENT_REJECTED),
])
def test_each_failure_says_what_it_is(fake, over, code):
    adapter, recorded, env = fake
    env.setenv("FAKE_ANSWER", answer(**over))
    with pytest.raises(AdapterError) as err:
        adapter.submit(Request("chat", params={"prompt": "x"}))
    assert err.value.code == code


def test_no_json_no_schema_answer_and_no_binary(fake, tmp_path):
    adapter, recorded, env = fake
    env.setenv("FAKE_ANSWER", "not json at all")
    with pytest.raises(AdapterError) as err:
        adapter.submit(Request("chat", params={"prompt": "x"}))
    assert err.value.code == ErrorCode.OUTPUT_INVALID
    env.setenv("FAKE_ANSWER", answer(result="no structured output"))
    with pytest.raises(AdapterError) as err:
        adapter.submit(Request("research", params={"prompt": "x", "system": "s", "schema": {"type": "object"}}))
    assert err.value.code == ErrorCode.OUTPUT_INVALID
    with pytest.raises(AdapterError) as err:
        ClaudeCode(str(tmp_path / "nowhere" / "claude")).submit(Request("chat", params={"prompt": "x"}))
    assert err.value.code == ErrorCode.UNAVAILABLE


def test_a_run_that_hangs_is_killed_at_its_timeout(fake, tmp_path):
    adapter, recorded, env = fake
    env.setenv("FAKE_SLEEP", "30")
    slow = ClaudeCode(adapter._binary, chat_seconds=1, workdir=tmp_path / "runs")
    with pytest.raises(AdapterError) as err:
        slow.submit(Request("chat", params={"prompt": "x"}))
    assert err.value.code == ErrorCode.TIMEOUT
    assert not any((tmp_path / "runs").iterdir())                 # its directory is gone
```

- [ ] **Step 2: Run them to see them fail.**
  Run `uv run pytest tests/adapters/test_claude_code.py -q`. Expected: an ImportError on `nexora.adapters.claude_code`.

- [ ] **Step 3: Implement the adapter.**

```python
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
                            retry_after=None if not reset.isdigit() else max(60.0, float(reset) - __import__("time").time()))
    if status in (401, 403) or any(h in lowered for h in AUTH_HINTS):
        return AdapterError(ErrorCode.AUTH, "Claude Code is not logged in: run `claude` once in a terminal and log in", retryable=False)
    if status is not None and status >= 500:
        return AdapterError(ErrorCode.UNAVAILABLE, f"Claude Code HTTP {status}: {message}")
    return AdapterError(ErrorCode.OUTPUT_INVALID, f"Claude Code: {message or 'no answer'}")
```

- [ ] **Step 4: Run the tests to see them pass.** Run `uv run pytest tests/adapters/test_claude_code.py -q`.
  Expected: all pass.
- [ ] **Step 5: Commit.**
  `git add src/nexora/adapters/claude_code.py tests/adapters/test_claude_code.py && git commit` with a message saying what
  the adapter does.

### Task 2: Script lines carry their facts, sources and on-screen words

**Files:**
- Modify: `src/nexora/core/projects.py`, in `save_script` (the `given` handling) and `keep_draft` (the kept keys).
- Test: `tests/production/test_topic_script.py` (new; this task adds its first test).

**Interfaces:**
- Produces: a dict line given to `ProjectStore.save_script` may carry `screen_text: str`, `is_fact: bool`,
  `source: str` and `fact_check: dict`, beside `brief`, `illustration` and `quote`. `keep_draft` keeps the same keys, so a
  draft line saved word for word brings them.

- [ ] **Step 1: Write the failing test.**

```python
def test_a_line_carries_its_fact_its_source_and_its_screen_words(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    project = system.planning.create_project("Rừng")
    unsourced = {"verdict": "not_found", "source": None, "quote": "", "note": "Người viết không dẫn nguồn cho câu này.", "checked_at": 1.0}
    system.projects.keep_draft(project, [{"text": "Năm 1950 Israel trồng rừng.", "is_fact": True, "source": "Haaretz", "screen_text": "1950"},
                                         {"text": "Không ai nhớ nổi.", "is_fact": True, "fact_check": unsourced}])
    system.planning.save_script(project, ["Năm 1950 Israel trồng rừng.", "Không ai nhớ nổi."])
    first, second = system.projects.current_script(project)["shots"]
    assert (first.is_fact, first.source, first.screen_text) == (True, "Haaretz", "1950")
    assert second.is_fact and second.fact_check["note"] == "Người viết không dẫn nguồn cho câu này."
```

- [ ] **Step 2: Run it to see it fail.** Run `uv run pytest tests/production/test_topic_script.py -q`. Expected: FAIL,
  because `source` and `screen_text` are None.
- [ ] **Step 3: Implement.**
  - In `save_script`, after `if given.get("illustration"):`, add:

```python
                if given.get("screen_text"):
                    notes[1] = str(given["screen_text"]).strip()
                if given.get("is_fact"):
                    notes[4] = 1
                if given.get("source"):
                    notes[5] = str(given["source"]).strip()
                if isinstance(given.get("fact_check"), dict):
                    notes[6] = json.dumps(given["fact_check"], ensure_ascii=False)
```

  - In `keep_draft`, widen the kept keys to
    `("brief", "illustration", "quote", "screen_text", "is_fact", "source", "fact_check")`.
- [ ] **Step 4: Run it to see it pass**, then run `uv run pytest tests/production -q` to check that nothing else broke.
- [ ] **Step 5: Commit.**

### Task 3: The topic package: prompt, schema and checks

**Files:**
- Create: `src/nexora/modules/planning/topic.py`
- Test: `tests/production/test_topic_script.py`

**Interfaces:**
- Produces:
  - `PACKAGE_SCHEMA: dict`.
  - `topic_prompt(topic: str, *, goal: str, lines: int, structure: list[dict] | None, voice: str, style: str, siblings: list[str]) -> tuple[str, str]`
    returns `(system, prompt)`.
  - `check_package(raw: dict) -> dict` returns
    `{"title", "angle", "sources": [{"id", "url", "title", "publisher", "date", "passage"}], "lines": [...], "unverified": [str], "warnings": [str]}`.
    It raises `ValueError("no lines")` when nothing usable is left.
  - `script_lines(package: dict) -> list[str | dict]`: a `# part` line for each part change, and each line as
    `{"text", "brief", "illustration", "screen_text", "is_fact", "source", "fact_check"?}`.
  - `UNSOURCED_NOTE = "Người viết không dẫn nguồn cho câu này."`

- [ ] **Step 1: Write the failing tests.**

```python
from nexora.modules.planning.topic import UNSOURCED_NOTE, check_package, script_lines, topic_prompt

PACKAGE = {"title": "Rừng bạch đàn", "angle": "Vì sao một cây ngoại lai thành bài toán",
           "sources": [{"id": "S1", "url": "https://example.org/a", "title": "Bài A", "publisher": "Haaretz", "date": "2021-05-03", "passage": "Năm 1950 KKL trồng bạch đàn."},
                       {"id": "S1", "url": "https://example.org/dup", "title": "Trùng", "publisher": "", "date": "", "passage": "x"},
                       {"id": "S2", "url": "ftp://x", "title": "Sai", "publisher": "", "date": "", "passage": "y"},
                       {"id": "S3", "url": "https://example.org/b", "title": "Bài B", "publisher": "", "date": "", "passage": ""}],
           "lines": [{"part": "Mở đầu", "text": "Năm 1950 người ta trồng bạch đàn khắp nơi.", "fact": True, "sources": ["S1"], "brief": "rừng bạch đàn",
                      "illustration": {"mode": "direct"}, "screen_text": "1950"},
                     {"part": "Mở đầu", "text": "> Có người bảo đó là sai lầm.", "fact": False, "sources": [], "brief": "", "illustration": {"mode": "associative", "evokes": "hối tiếc"}},
                     {"part": "Thân bài", "text": "Mỗi cây uống hai mươi lít nước một ngày.", "fact": True, "sources": ["S9"], "brief": "lá cây"},
                     {"part": "Thân bài", "text": "   ", "fact": False, "sources": []}],
           "unverified": ["con số chính xác diện tích"]}


def test_a_package_is_checked_before_anything_is_written():
    p = check_package(PACKAGE)
    assert [s["id"] for s in p["sources"]] == ["S1"]                        # a duplicate id, a non-web url, an empty passage: dropped
    assert [l["text"] for l in p["lines"]] == ["Năm 1950 người ta trồng bạch đàn khắp nơi.", "Có người bảo đó là sai lầm.", "Mỗi cây uống hai mươi lít nước một ngày."]
    assert p["lines"][0]["source"] == "Bài A" and p["lines"][2]["unsourced"] and p["unverified"] == ["con số chính xác diện tích"]
    lines = script_lines(p)
    assert lines[0] == "# Mở đầu" and lines[3] == "# Thân bài"
    assert lines[1]["is_fact"] and lines[1]["source"] == "Bài A" and lines[1]["screen_text"] == "1950" and "fact_check" not in lines[1]
    assert lines[4]["is_fact"] and lines[4]["fact_check"]["note"] == UNSOURCED_NOTE and "source" not in lines[4]
    assert lines[2]["illustration"] == {"mode": "associative", "evokes": "hối tiếc"}


def test_a_package_with_nothing_usable_is_refused():
    with pytest.raises(ValueError):
        check_package({"title": "x", "sources": [], "lines": [{"text": " "}]})
    with pytest.raises(ValueError):
        check_package({"oops": True})


def test_the_prompt_carries_the_voice_the_structure_and_the_siblings():
    system, prompt = topic_prompt("rừng bạch đàn Israel", goal="vì sao", lines=8, structure=[{"name": "Mở đầu", "min": 5, "max": 10}],
                                  voice="Giọng miền Nam.", style="mixed", siblings=["Bạch đàn và nước ngầm"])
    assert "Giọng miền Nam." in system and "nguồn" in system and "WebSearch" in system
    assert "rừng bạch đàn Israel" in prompt and "Mở đầu" in prompt and "Bạch đàn và nước ngầm" in prompt and "8" in prompt
```

- [ ] **Step 2: Run them to see them fail** (ImportError).
- [ ] **Step 3: Implement `topic.py` (functions only in this task).**

```python
"""A script from a topic (design 2026-10-18, Claude Code as NEXORA's writer): a writer that can read the web looks the
subject up and returns a package of its sources and the lines it wrote on them. Nothing in the package is taken on trust:
a source needs a web address and a passage to rest on, a line stating a fact keeps only a source the package has, and a
package with no line is refused before anything is written."""
from __future__ import annotations

import time

UNSOURCED_NOTE = "Người viết không dẫn nguồn cho câu này."
MODES = ("direct", "associative", "contrast")
PASSAGE = 600

PACKAGE_SCHEMA = {
    "type": "object", "required": ["title", "angle", "sources", "lines", "unverified"], "additionalProperties": False,
    "properties": {
        "title": {"type": "string"}, "angle": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object", "required": ["id", "url", "title", "publisher", "date", "passage"], "additionalProperties": False,
                    "properties": {k: {"type": "string"} for k in ("id", "url", "title", "publisher", "date", "passage")}}},
        "lines": {"type": "array", "items": {"type": "object", "required": ["part", "text", "fact", "sources", "brief", "illustration"], "additionalProperties": False,
                  "properties": {"part": {"type": "string"}, "text": {"type": "string"}, "fact": {"type": "boolean"},
                                 "sources": {"type": "array", "items": {"type": "string"}}, "brief": {"type": "string"}, "screen_text": {"type": "string"},
                                 "illustration": {"type": "object", "required": ["mode"], "additionalProperties": False,
                                                  "properties": {"mode": {"type": "string", "enum": list(MODES)}, "evokes": {"type": "string"}}}}}},
        "unverified": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM = (
    "Bạn là biên kịch phim tài liệu ngắn của NEXORA, viết lời dẫn tiếng Việt để đọc thành tiếng trên hình. {voice}\n"
    "Bạn tìm hiểu chủ đề bằng WebSearch và WebFetch: đọc nguồn đáng tin (báo lớn, cơ quan nhà nước, tạp chí khoa học, tổ chức chuyên môn), "
    "ưu tiên nguồn gốc hơn bài đăng lại, và ghi lại mỗi nguồn đã dùng với một đoạn trích nguyên văn (không quá {passage} ký tự) làm chỗ dựa.\n"
    "Quy tắc dữ kiện: câu nào nêu con số, ngày tháng, tên người, tên nơi chốn hay sự kiện thì đặt fact = true và dẫn id của nguồn đã đọc có nói điều đó. "
    "Không bịa. Điều gì muốn nói mà không tìm được nguồn thì không đưa vào lời dẫn, ghi vào unverified.\n"
    "Mỗi câu kèm brief (hình cần thấy, cụ thể, quay được hoặc tìm được trong kho stock) và illustration: mode direct khi hình cho thấy đúng điều câu nói, "
    "associative khi hình gợi cảm xúc hay ý của câu (kèm evokes: điều hình gợi ra, 2 đến 5 chữ), contrast khi hình đối lập để tạo ý. {style}\n"
    "Không viết câu trích lời, không dùng dấu > ở đầu câu. Trả lời bằng đúng cấu trúc JSON được yêu cầu."
)
STYLES = {"direct": "Phần lớn các câu minh hoạ trực tiếp.", "associative": "Phần lớn các câu minh hoạ liên tưởng.",
          "mixed": "Pha trộn: câu nêu dữ kiện minh hoạ trực tiếp, câu cảm xúc hay chuyển ý minh hoạ liên tưởng."}


def topic_prompt(topic: str, *, goal: str = "", lines: int = 8, structure: list[dict] | None = None, voice: str = "", style: str = "mixed",
                 siblings: list[str] | None = None) -> tuple[str, str]:
    system = SYSTEM.format(voice=voice.strip(), passage=PASSAGE, style=STYLES.get(style, STYLES["mixed"]))
    parts = [f"Chủ đề: {topic.strip()}."]
    if goal.strip():
        parts.append(f"Mục tiêu của video: {goal.strip()}.")
    parts.append(f"Viết khoảng {lines} câu lời dẫn.")
    if structure:
        parts.append("Chia lời dẫn theo đúng các phần sau, theo thứ tự, ghi tên phần vào part: "
                     + "; ".join(f"{p['name']} ({p.get('min', 0)}–{p.get('max', 0)} giây)" for p in structure) + ". Đọc khoảng 2,6 chữ mỗi giây.")
    else:
        parts.append("Ghi part là Mở đầu, Thân bài hoặc Kết.")
    if siblings:
        parts.append("Dự án này đã có các video: " + "; ".join(siblings) + ". Chọn một góc khác các video đó.")
    return system, "\n".join(parts)


def check_package(raw: dict) -> dict:
    sources, seen_ids, seen_urls = [], set(), set()
    for s in raw.get("sources") or []:
        if not isinstance(s, dict):
            continue
        sid, url, passage = str(s.get("id") or "").strip(), str(s.get("url") or "").strip(), " ".join(str(s.get("passage") or "").split())
        if not sid or sid in seen_ids or not url.startswith(("http://", "https://")) or url in seen_urls or not passage:
            continue
        seen_ids.add(sid)
        seen_urls.add(url)
        sources.append({"id": sid, "url": url, "title": str(s.get("title") or url).strip(), "publisher": str(s.get("publisher") or "").strip() or None,
                        "date": str(s.get("date") or "").strip() or None, "passage": passage[:PASSAGE]})
    by_id = {s["id"]: s for s in sources}
    lines = []
    for l in raw.get("lines") or []:
        if not isinstance(l, dict):
            continue
        text = str(l.get("text") or "").strip().lstrip(">").strip()
        if not text:
            continue
        cited = [by_id[c] for c in (l.get("sources") or []) if c in by_id]
        art = l.get("illustration") if isinstance(l.get("illustration"), dict) else {}
        mode = art.get("mode") if art.get("mode") in MODES else "direct"
        lines.append({"part": str(l.get("part") or "").strip(), "text": text, "fact": bool(l.get("fact")), "brief": str(l.get("brief") or "").strip(),
                      "screen_text": str(l.get("screen_text") or "").strip(), "illustration": {"mode": mode, **({"evokes": str(art["evokes"]).strip()} if art.get("evokes") else {})},
                      "source": cited[0]["title"] if cited else None, "unsourced": bool(l.get("fact")) and not cited})
    if not lines:
        raise ValueError("no lines")
    warnings = [f"{sum(l['unsourced'] for l in lines)} câu nêu dữ kiện chưa có nguồn"] if any(l["unsourced"] for l in lines) else []
    return {"title": str(raw.get("title") or "").strip(), "angle": str(raw.get("angle") or "").strip(), "sources": sources, "lines": lines,
            "unverified": [str(u).strip() for u in raw.get("unverified") or [] if str(u).strip()], "warnings": warnings}


def script_lines(package: dict) -> list:
    out, part = [], None
    for l in package["lines"]:
        if l["part"] and l["part"] != part:
            part = l["part"]
            out.append(f"# {part}")
        line = {"text": l["text"], "illustration": l["illustration"], "is_fact": l["fact"]}
        for key in ("brief", "screen_text", "source"):
            if l.get(key):
                line[key] = l[key]
        if l["unsourced"]:
            line["fact_check"] = {"verdict": "not_found", "source": None, "quote": "", "note": UNSOURCED_NOTE, "checked_at": time.time()}
        out.append(line)
    return out
```

- [ ] **Step 4: Run them to see them pass.** Run `uv run pytest tests/production/test_topic_script.py -q`.
- [ ] **Step 5: Commit.**

### Task 4: The pipeline `planning.topic_script`, its lane and its wiring

**Files:**
- Modify: `src/nexora/modules/planning/topic.py` (add `TopicWriter`).
- Modify: `src/nexora/app.py`:
  - build: `cloud_models` may include ClaudeCode;
  - a third worker on the lane `claude_code`;
  - `system.topics`;
  - `apply_topic`, `merge_sources`;
  - `build_from_config` registers ClaudeCode.
- Modify: `src/nexora/config.py` (settings for `claude_code_*`).
- Modify: `tests/fakes.py` (`FakeClaudeCode`).
- Test: `tests/production/test_topic_script.py`.

**Interfaces:**
- Consumes: `check_package`, `topic_prompt`, `PACKAGE_SCHEMA` (Task 3); `ClaudeCode` (Task 1).
- Produces:
  - `TOPIC = PipelineDefinition("planning.topic_script", "1", [StageDef("write", requires=("model.claude_code",), lane="claude_code", timeout_seconds=1200, max_attempts=2)])`.
  - `TopicWriter(db_path, adapters, *, context: Callable[[str], dict])`, where `context(project_id)` returns
    `{"voice", "structure", "style", "siblings"}`.
  - `.register(registry)`.
  - `.start(project_id, topic, *, goal="", lines=8) -> run_id`.
  - `.get(run_id) -> {"run_id", "project_id", "topic", "goal", "package": dict | None, "state": "asked" | "written" | "offered" | "applied"}`.
  - `.latest(project_id) -> dict | None`.
  - `.mark(run_id, state)`.
  - In `app.py`:
    - `merge_sources(system, project_id, sources: list[dict]) -> int` merges by url into the production (through
      `update_production`) and the video;
    - `apply_topic(system, project_id, run_id) -> str` saves the script (with notes), merges the sources, puts
      `unverified` in the notes, marks the run applied, and returns the `script_id`.
  - `FakeClaudeCode(answer: dict)` in `tests/fakes.py`: `describe()` returns `model.claude_code` with
    `("chat", "research")`, and `submit` returns `Result(outputs={"json": answer, "api_equivalent": 0.1})`.

- [ ] **Step 1: Write the failing test.**

```python
def _topic_system(tmp_path, answer=PACKAGE):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), cloud_models=[FakeClaudeCode(answer)])
    return system, TestClient(create_app(system))


def test_a_topic_is_written_by_the_researching_writer_and_applied_with_its_sources(tmp_path):
    system, client = _topic_system(tmp_path)
    project = system.planning.create_project("Rừng")
    run_id = system.topics.start(project, "rừng bạch đàn Israel", goal="vì sao", lines=6)
    assert system.orch.stages(run_id)[0].lane == "claude_code"
    drain(system)
    got = system.topics.get(run_id)
    assert got["state"] == "written" and got["package"]["title"] == "Rừng bạch đàn"
    asked = system.adapters._adapters["model.claude_code"].asked[-1]
    assert asked.operation == "research" and "rừng bạch đàn Israel" in asked.params["prompt"] and asked.params["schema"]
    script_id = apply_topic(system, project, run_id)
    shots = system.projects.script(script_id)["shots"]
    assert [s.text for s in shots][0] == "Năm 1950 người ta trồng bạch đàn khắp nơi." and shots[0].scene == "Mở đầu"
    research = system.planning.research(project)
    assert [s["url"] for s in research] == ["https://example.org/a"] and research[0]["passage"].startswith("Năm 1950")
    production = system.productions.get(system.projects.project(project)["production_id"])
    assert "https://example.org/a" in production["research"]
    assert "con số chính xác diện tích" in (system.projects.project(project).get("notes") or "")
    assert system.topics.get(run_id)["state"] == "applied"
    assert merge_sources(system, project, research) == 0          # merged by url: nothing twice


def test_a_package_that_fails_its_checks_fails_the_run_and_writes_nothing(tmp_path):
    system, client = _topic_system(tmp_path, answer={"title": "x", "sources": [], "lines": []})
    project = system.planning.create_project("Rừng")
    run_id = system.topics.start(project, "x")
    drain(system)
    assert system.orch.run_status(run_id).value in ("failed", "blocked") and system.projects.current_script(project) is None
```

- [ ] **Step 2: Run it to see it fail.**
- [ ] **Step 3: Implement.**
  - **`TopicWriter` in `topic.py`.**
    - Schema: `CREATE TABLE IF NOT EXISTS topic_scripts (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, topic TEXT NOT NULL, goal TEXT, lines INTEGER, package TEXT, state TEXT NOT NULL, created_at REAL NOT NULL)`.
    - `start` submits `TOPIC` with `subject_ref=project_id` and inserts the row in state `asked`.
    - The stage handler `_write(ctx)` reads the row by `ctx.claim.run_id`, builds the prompt from
      `context(project_id)`, and calls
      `adapters.submit("model.claude_code", Request("research", params={"prompt", "system", "schema": PACKAGE_SCHEMA}, privacy_class=PrivacyClass.CLOUD_ALLOWED))`.
      It runs `check_package` on `outputs["json"]`; a `ValueError` becomes
      `AdapterError(ErrorCode.OUTPUT_INVALID, ..., retryable=False)`. It stores the package with state `written`, and
      returns `{"lines": n, "sources": m, "api_equivalent": x}`.
  - **`app.py`.**
    - `system.topics = TopicWriter(db_path, adapters, context=lambda pid: topic_context(system, pid))`, then
      `system.topics.register(registry)`.
    - `topic_context` gives:
      - `voice`: the `writing_voice` setting or `HOUSE_VOICE`;
      - `structure`: the project's template structure;
      - `style`: `illustration_style(system, project)`;
      - `siblings`: the titles of the other videos in its production.
    - Add `Worker(orch, registry, worker_id=f"claude-code-{os.getpid()}", lanes=frozenset({"claude_code"}), log=log)`
      to `workers`.
  - **`merge_sources`** turns each source into `{"title", "publisher", "date", "url", "passage", "retrieved_at"}`. It
    writes the production's research with `update_production(system, pid, {"research": json})`, which reaches videos
    still on the old value, then the video's own research if it still lacks one. It returns how many were new.
  - **`apply_topic`**:
    - `system.planning.save_script(project_id, script_lines(pkg))` (dict lines);
    - `merge_sources`;
    - notes: append `"Chưa kiểm chứng được: " + "; ".join(unverified)` to the project's `notes`;
    - `system.topics.mark(run_id, "applied")`.
  - **`config.py`.** Fields:

    ```python
    claude_code_binary: str = ""
    claude_code_model: str = "opus"
    claude_code_effort: str = "high"
    claude_code_chat_seconds: float = 180.0
    claude_code_research_seconds: float = 900.0
    ```

    Also add matching commented lines to the template.
  - **`build_from_config`.** When `config.claude_code_binary or find_claude()` is found, append
    `ClaudeCode(binary, model=..., effort=..., chat_seconds=..., research_seconds=..., workdir=data_dir / "claude_code")`
    to `cloud_models`.
- [ ] **Step 4: Run** `uv run pytest tests/production/test_topic_script.py -q` **and** `uv run lint-imports`.
- [ ] **Step 5: Commit.**

### Task 5: The script editor: "Từ chủ đề…"

**Files:**
- Modify: `src/nexora/api/app.py`:
  - `POST /api/v1/projects/{id}/draft-from-topic` returns `{run_id}`;
  - `GET /api/v1/projects/{id}/draft-from-topic` returns `{state, status, lines, sources, unverified, warnings}`;
  - the `PUT /api/v1/projects/{id}/script` handler applies an offered draft's sources once.
- Modify: `web/src/Projects.tsx` (a `TopicDraft` component beside `SpeechDraft`), `web/src/en.ts`.
- Test: `tests/production/test_topic_script.py`.

**Interfaces:**
- Consumes: `system.topics`, `merge_sources`, `script_lines`.
- Produces: the endpoints above.
  - On GET, a `written` run turns `offered`; its lines are given to `keep_draft` and returned as text (`# part` lines
    included).
  - On PUT script, if `system.topics.latest(project)` is `offered`, `merge_sources` runs and the state turns `applied`.

- [ ] **Step 1: Write the failing test.**

```python
def test_the_editor_gets_the_topic_draft_unsaved_and_its_sources_on_save_only(tmp_path):
    system, client = _topic_system(tmp_path)
    project = system.planning.create_project("Rừng")
    assert client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": " "}).status_code == 422
    run = client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": "rừng bạch đàn Israel", "lines": 6}).json()
    assert client.get(f"/api/v1/projects/{project}/draft-from-topic").json()["state"] == "asked"
    drain(system)
    got = client.get(f"/api/v1/projects/{project}/draft-from-topic").json()
    assert got["state"] == "offered" and got["lines"][0] == "# Mở đầu" and got["sources"][0]["url"] == "https://example.org/a"
    assert system.projects.current_script(project) is None and system.planning.research(project) == []       # nothing saved yet
    client.put(f"/api/v1/projects/{project}/script", json={"lines": got["lines"]})
    first = system.projects.current_script(project)["shots"][0]
    assert first.is_fact and first.source == "Bài A" and len(system.planning.research(project)) == 1
    client.put(f"/api/v1/projects/{project}/script", json={"lines": got["lines"]})
    assert len(system.planning.research(project)) == 1                                                      # applied once
    other = system.planning.create_project("Khác")
    client.put(f"/api/v1/projects/{other}/script", json={"lines": ["Một câu."]})
    assert system.planning.research(other) == []
```

- [ ] **Step 2: Run it to see it fail** (404 on the route).
- [ ] **Step 3: Implement the endpoints** (in `api/app.py`, next to `draft-from-speech`):

```python
    @app.post("/api/v1/projects/{project_id}/draft-from-topic", status_code=202)
    def draft_from_topic(project_id: str, body: dict):
        """A script from a topic, written by Claude Code from what it reads on the web; it runs in the background, and the
        editor asks for it when it is done. Nothing is saved until the operator saves the script."""
        need_project(project_id)
        topic = str(body.get("topic") or "").strip()
        if not topic:
            raise HTTPException(422, "Hãy nói chủ đề của video")
        if "model.claude_code" not in {c.name for c in system.adapters.describe()}:
            raise HTTPException(503, "Máy này chưa có Claude Code. Cài Claude Code và đăng nhập một lần bằng lệnh claude.")
        return {"run_id": system.topics.start(project_id, topic, goal=str(body.get("goal") or ""), lines=max(3, min(30, int(body.get("lines") or 8))))}

    @app.get("/api/v1/projects/{project_id}/draft-from-topic")
    def topic_draft(project_id: str):
        need_project(project_id)
        got = system.topics.latest(project_id)
        if got is None:
            return {"state": None}
        status = system.orch.run_status(got["run_id"]).value
        if got["state"] == "written":
            system.topics.mark(got["run_id"], "offered")
            got["state"] = "offered"
        if got["state"] != "offered" or not got["package"]:
            return {"state": got["state"], "status": status}
        lines = script_lines(got["package"])
        system.projects.keep_draft(project_id, [l for l in lines if isinstance(l, dict)])
        return {"state": "offered", "status": status, "lines": [l if isinstance(l, str) else l["text"] for l in lines], "title": got["package"]["title"],
                "sources": got["package"]["sources"], "unverified": got["package"]["unverified"], "warnings": got["package"]["warnings"]}
```

  - In the existing `PUT .../script` handler, after the save, add:

```python
        offered = system.topics.latest(project_id)
        if offered and offered["state"] == "offered" and offered["package"]:
            merge_sources(system, project_id, offered["package"]["sources"])
            system.topics.mark(offered["run_id"], "applied")
```

  - **UI.** `TopicDraft({ id, topic, done })`, modelled on `SpeechDraft`, in the panel opened by a button "Từ chủ
    đề…" (icon `globe`) next to "Từ lời nói…":
    - inputs: topic (defaulting to the video's title), goal, number of lines;
    - "Viết bằng Claude Code" posts, then polls `GET` every 3 s;
    - while it runs, it shows "Claude Code đang tìm nguồn và viết… (vài phút)";
    - when `offered`, it calls `done(lines)` (the same handler as `SpeechDraft`, which asks before replacing unsaved
      text) and lists the sources (title, publisher, link), the warnings and "Chưa kiểm chứng được";
    - a failed run shows the run status and "Thử lại".
- [ ] **Step 4: Run the test**, then `cd web && npm run i18n:check && npm run build`.
- [ ] **Step 5: Commit.**

### Task 6: Missions of kind `topic`, through the Producer

**Files:**
- Modify: `src/nexora/agents/missions.py` (KINDS, PLAN_PROMPT, normalise, check, confirm).
- Modify: `src/nexora/agents/producer.py`:
  - `start(..., topic=False, paid=False)`;
  - steps `topic` and `topic_wait`;
  - `facts` skips finding for topic;
  - `gaps` asks generation when `paid`.
- Modify: `src/nexora/modules/sourcing/generate.py`: `start(script_id, only=None)` and a table
  `generate_only(run_id, shot_id)`; `_keyframes` and `_clips` skip shots not listed.
- Modify: `src/nexora/app.py` (the Producer is given `write_topic`, `topic_state`, `apply_topic`, `generate`).
- Test: `tests/production/test_topic_script.py`.

**Interfaces:**
- Consumes: `system.topics.start/get`, `apply_topic`, `Generation.start(script_id, only=[shot_ids])`.
- Produces:
  - `KINDS["topic"] = {"name": "Làm video theo chủ đề", "pipelines": ("planning.topic_script", "sourcing.match", "edit.render")}`.
  - `Producer(..., write_topic: Callable[[str, str, int], str], topic_state: Callable[[str], str], apply_topic: Callable[[str, str], str], generate: Callable[[str, list[str]], str])`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_topic_mission_researches_then_carries_on_like_any_video(tmp_path):
    system, client = _topic_system(tmp_path)
    plan = {"loai": "topic", "muc_tieu": "khủng hoảng rừng bạch đàn Israel", "tieu_de": "Rừng bạch đàn", "so_video": 1, "dinh_dang": "landscape", "so_cau": 6}
    system.adapters._adapters["model"].answers["mission_plan"] = plan
    m = client.post("/api/v1/missions", json={"text": "sản xuất video về khủng hoảng rừng bạch đàn của Israel"}).json()
    assert m["plan"]["kind"] == "topic" and m["plan"]["critique"] is False and m["state"] == "planned"
    done = client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()
    task_id, project = done["links"]["tasks"][0], done["links"]["projects"][0]
    for _ in range(12):                                          # the producer steps; the worker runs what they start
        system.producer.advance(task_id)
        drain(system)
    task = system.producer.task(task_id)
    assert system.projects.current_script(project)["shots"][0].text == "Năm 1950 người ta trồng bạch đàn khắp nơi."
    assert any("Claude Code" in e["text"] for e in task["log"]) and task["step"] in ("review", "cut", "cutting") or task["status"] in ("waiting_operator", "done")
    assert len(system.planning.research(project)) == 1


def test_a_topic_mission_needs_claude_code(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    client = TestClient(create_app(system))
    system.adapters._adapters["model"].answers["mission_plan"] = {"loai": "topic", "muc_tieu": "rừng", "so_video": 1}
    m = client.post("/api/v1/missions", json={"text": "video về rừng"}).json()
    assert m["state"] == "draft" and any("model.claude_code" in p for p in m["problems"])


def test_generation_for_gaps_only_when_paid(tmp_path):
    system, client = _topic_system(tmp_path)
    project = system.planning.create_project("Rừng")
    system.projects.save_script(project, ["Câu một.", "Câu hai."])
    script = system.projects.current_script(project)
    run_id = system.generation.start(script["script_id"], only=[script["shots"][1].shot_id])
    assert system.generation.targets(run_id) == {script["shots"][1].shot_id}
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
  - **Missions.**
    - `PLAN_PROMPT` offers `topic (làm video theo một chủ đề ngoài kho footage: máy tự tìm nguồn trên web và viết kịch bản)`,
      and `tu_phan_bien (true cho video, false cho topic)`.
    - In `normalise`, when `kind == "topic"` and `raw.get("critique") is None`, critique is False.
    - In `check`, the video checks (goal, channel, template) apply to `("video", "topic")`.
    - In `confirm`, `if plan["kind"] in ("video", "topic")`, Producer.start is called with `topic=plan["kind"] == "topic"`,
      `paid=plan["paid"]`, `critique=plan["critique"]`.
  - **Producer.**
    - `start` sets the first step to `topic` when `topic`, and keeps `topic` and `paid` in the options.
    - Step `topic`: `run_id = self._write_topic(project_id, goal, lines)`; say (RESEARCHER) "Giao Claude Code tìm nguồn
      và viết kịch bản."; move to `topic_wait` with `options.topic_run = run_id`.
    - Step `topic_wait`:
      - if `self._topic_state(run_id)` is `"asked"` and the run is not failed, return False (still waiting);
      - if the run failed, say "Claude Code không viết được: <reason>" and fail the task;
      - else `self._apply_topic(project_id, run_id)`, then say (WRITER) "Claude Code viết {n} câu dựa trên {m} nguồn."
        and move to `critique` if critique, else `facts`.
    - Step `facts`: when `options.topic`, do not call `find_facts` (the writer already marked its facts); call
      `check_facts` only.
    - Step `gaps`: after stock, when `options.paid`, the gaps left are
      `[s.shot_id for s in selections if s.status == "gap" and s.shot_id not in quotes]`; if any, call
      `self._generate(script_id, gaps)` and say (STOCK) "Tạo hình AI cho {k} câu còn thiếu, trong ngân sách của dự án."
  - **Generation.**
    - Table `generate_only (run_id TEXT, shot_id TEXT)`.
    - `start(script_id, only=None)` inserts the rows after `submit_run`.
    - `targets(run_id) -> set[str]`.
    - In `_keyframes` and `_clips`, `wanted = self.targets(ctx.claim.run_id)` and
      `for shot in script["shots"]: if wanted and shot.shot_id not in wanted: continue`.
  - **`app.py`.** The Producer gets:

    ```python
    write_topic=lambda pid, goal, n: system.topics.start(pid, goal, lines=n)
    topic_state=lambda run_id: (system.topics.get(run_id) or {}).get("state", "asked")
    apply_topic=lambda pid, run_id: apply_topic(system, pid, run_id)
    generate=lambda script_id, shots: system.generation.start(script_id, only=shots)
    ```

    `system.topics` is built before the Producer.
- [ ] **Step 4: Run the new tests**, then `uv run pytest tests/api tests/production -q`.
- [ ] **Step 5: Commit.**

### Task 7: Finish: full suite, UI strings, graph, and one real run (with the operator's OK)

- [ ] **Step 1:** Run `uv run pytest -q` and `uv run lint-imports`. Expected: all pass, 4 contracts kept.
- [ ] **Step 2:** Run `cd web && npm run i18n:check && npm run build`. Expected: 0 strings without English.
- [ ] **Step 3:** Restart the server and check in the browser:
  - Hệ thống → Định tuyến model lists `model.claude_code`;
  - the editor shows "Từ chủ đề…";
  - Mission Control offers "Làm video theo chủ đề".
- [ ] **Step 4:** Commit, then run `graphify update .`.
- [ ] **Step 5:** Ask the operator before the real run, since it uses their plan. The run is one video on Israel's
  eucalyptus afforestation from the editor. Record:
  - the time taken and the API-equivalent cost;
  - whether any CLAUDE.md, hook or plugin text reached the answer;
  - the number of sources and lines, and the lines marked "chưa có nguồn".
