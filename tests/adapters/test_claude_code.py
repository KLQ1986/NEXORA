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
