# Claude Code as NEXORA's writer

Date: 2026-10-18. Asked by the operator: "nhúng claude code vào khâu viết kịch bản, mỗi lần viết kịch bản thì gọi claude code
viết, rồi xuất ra kết quả insert vào hệ thống", and further, "Claude tự sinh ra toàn bộ kịch bản theo chủ đề", for example a
video about Israel's eucalyptus afforestation crisis.

Approved in conversation the same day:
- **Direction A.** Claude Code returns a structured package; NEXORA checks it and writes it in. Claude Code never writes to
  NEXORA itself.
- **The model.** Opus, effort high, on the operator's Claude plan.
- **Pictures for topic videos.** Free stock first, then AI-generated pictures within the budget. The library serves
  associative shots.

Reference: CyberX already calls Claude Code this way (`/Users/kevin/CyberX/src/cyberx/gateway/claude_code.py`).

## Why

Every text task now goes to the local `qwen3-vl:8b-instruct`. It is a general model, and its Vietnamese prose is weak: on
the script from speech it echoed the quotes instead of writing narration. The Claude API adapter exists, but it bills
the API and is configured for Haiku. Claude Code uses the operator's plan and Opus, and it can look a subject up on the
web itself.

## 1. The adapter: `model.claude_code`

`src/nexora/adapters/claude_code.py` sits beside `claude.py` and implements the same `Adapter` interface. Its capability
is `model.claude_code`, with the operations `chat` and `research`, and it runs in the cloud. It is registered only when
the `claude` binary is found.

### The call

Each call is one stateless `claude -p` run, made in its own temporary directory under `data/claude_code/` and removed
afterwards:

```
claude -p --output-format json --model <claude_code_model> --effort <claude_code_effort>
       --tools "<none | WebSearch,WebFetch>"
       --setting-sources "" --strict-mcp-config --no-session-persistence
       --system-prompt <NEXORA's instructions> [--json-schema <schema>]
```

- **The prompt goes on stdin**, never on the command line.
- **`ANTHROPIC_API_KEY` is removed from the child's environment.** With it present, Claude Code bills the API key
  instead of the plan, and NEXORA reads that key for the Claude API adapter.
- **The operator's own Claude Code setup is kept out:**
  - `--setting-sources ""` and `--strict-mcp-config` keep out their CLAUDE.md, hooks (graphify, the explanatory style),
    plugins and MCP servers;
  - `--system-prompt` replaces the coding-assistant prompt.

  Whether CLAUDE.md or a hook still reaches the run is checked on the first real run.

### The two operations

- **`chat`** takes no tools (`--tools ""`). It answers the text tasks with the prompts they already have:
  - draft, draft from speech, co-writing, revision;
  - critique, ideas, mission plan.

  With `json` asked, the answer is parsed as the Claude API adapter parses it. With a schema given, it is read from
  `structured_output`.
- **`research`** takes `WebSearch` and `WebFetch`, which only read, and a schema. Its answer is read from
  `structured_output`. The schema has no top-level `anyOf`, since Claude Code turns `--json-schema` into a tool.

### Settings in `nexora.toml`

| Setting | Default |
|---|---|
| `claude_code_binary` | found on PATH |
| `claude_code_model` | `opus` |
| `claude_code_effort` | `high` |
| `claude_code_chat_seconds` | 180 |
| `claude_code_research_seconds` | 900 |

### Cost and limits

- **Budgets record 0 USD.** The plan is not money spent through NEXORA.
- **Tokens and `total_cost_usd`**, the list-price estimate, are kept in the call record and shown in Mission Control
  as "API-equivalent".
- **One Claude Code run at a time**, on a lane of its own, so the plan's limits are not hit by NEXORA running several.

### Errors

| What happens | Code |
|---|---|
| No `claude` binary | `UNAVAILABLE` |
| Not logged in | `AUTH`, with the hint to run `claude` once to log in |
| `api_error_status` 429, or a message saying rate limit, usage limit, limit reached or overloaded | `RATE_LIMITED`, with the retry time when the CLI gives one |
| Status 5xx | `UNAVAILABLE` |
| No output in time | `TIMEOUT`; the process is killed |
| No JSON, `is_error`, or a missing `structured_output` | `OUTPUT_INVALID` |
| `stop_reason` is refusal | `CONTENT_REJECTED` |

The router's fallback is unchanged. For `chat`, a failure is answered by the local model and the operator is told once.

### Privacy

The adapter takes text only: no operation carries a picture, and the registry refuses any request with footage.
Privacy mode (local only) refuses it altogether.

### Routing

The adapter is offered on Hệ thống → Định tuyến model next to Claude API. Routing "write" to it reaches every writing
task through `TASK_GROUPS`. Nothing is routed to it by default; the operator chooses.

## 2. A script from a topic

### The package

The `research` operation returns this package:

```json
{
  "title": "…", "angle": "one sentence: what the video is for",
  "sources": [{"id": "S1", "url": "https://…", "title": "…", "publisher": "…", "date": "YYYY-MM-DD",
               "passage": "verbatim passage, ≤ 600 characters, that the lines rest on"}],
  "lines": [{"part": "<template part>", "text": "…", "fact": true, "sources": ["S1"], "brief": "what is seen",
             "illustration": {"mode": "direct|associative|contrast", "evokes": "…"}, "screen_text": "…"}],
  "unverified": ["what it wanted to say and found no source for"]
}
```

The system prompt carries:
- the house voice, or the operator's writing voice;
- the template's structure and lengths;
- the mixed way of illustrating;
- the titles and angles of the production's other videos, so this one takes another angle;
- the rule on facts: a line stating a figure, date, name or event cites a source it has read; nothing is invented; what
  cannot be sourced goes to `unverified`, not into the narration.

### Checks in code, before anything is written

- A source needs an `http(s)` url and a non-empty passage. A duplicate id is dropped.
- A line with `fact: true` that cites no source in the package is kept and marked "chưa có nguồn". It is not dropped.
- A leading `> ` is removed: a topic video quotes no one from the footage.
- The template's structure check (part lengths, total) is reported as a warning. It never blocks.
- A package that fails the schema or has no line is `OUTPUT_INVALID`, and nothing is written.

### What is written

- **Sources go into the production's research**, in the shape `read_source` keeps (title, publisher, date, url,
  passage, retrieved_at), merged by url. The production's later videos reuse them.
- **The script is saved as a new version.** Each line keeps `brief`, `illustration`, `is_fact`, `source` (the url) and
  `screen_text`. A part name becomes a `#` scene line.
- **`unverified` becomes the video's notes.**

### Where it runs

The pipeline `planning.topic_script` has one stage, which requires `model.claude_code`, on the `claude_code` lane.
Neither the Producer's loop nor an API request ever waits on the CLI.

Its result is kept as a draft in `script_drafts` with its sources. A mission applies it at once. The editor offers it
to the operator.

### Way in 1: a mission of kind `topic` ("Làm video theo chủ đề")

**Planning.**
- The plan prompt offers `topic` beside `video`. A subject the library does not hold is `topic`.
- The plan carries the topic, number of videos, format, template, lines and whether paid services may be used.

**Checks.** Without `model.claude_code` the plan is a draft that says so, and it cannot be confirmed. A topic video has
no local fallback, since the local model cannot look a subject up.

**Carrying it out.** Confirmed, the mission makes or uses a production, as video missions do. The Producer runs each
video through these steps:

1. **research** starts `planning.topic_script`.
2. **researching** waits on that run. When it succeeds, it applies the draft: sources and script as above. The `write`
   step is skipped.
3. **critique** is off by default for `topic`, since Opus has already revised its own work. The plan can turn it on.
4. **facts** is the existing checker. It checks every fact line against the passages, apart from the writer.
5. **source → matching** searches the library: associative lines find the operator's footage; direct lines mostly
   become gaps.
6. **gaps** fills from free stock first. When the plan allows paid services, `Generation.start` makes the rest, within
   the video's cap and the production's total budget. Otherwise gaps stay gaps.
7. **review** is unchanged: the storyboard waits for the operator.

The videos of one mission are written one after another, since only one Claude Code run happens at a time.

### Way in 2: the script editor

"Từ chủ đề…", beside "Từ lời nói…", takes a topic and an optional goal. It starts `planning.topic_script` for the video
and shows its progress.

The finished draft goes into the editor unsaved, like the other drafts, asking first over unsaved changes. Its sources
are written to the production only when the script is saved.

## Tests

### Adapter

The tests use a fake `claude`: a script that prints a canned answer and records its arguments, stdin and environment.

- The flags:
  - `--tools ""` for `chat`, `WebSearch,WebFetch` for `research`;
  - `--setting-sources ""`, `--strict-mcp-config`, `--no-session-persistence`;
  - `--system-prompt`, and `--json-schema` when there is a schema.
- The prompt arrives on stdin, and the environment has no `ANTHROPIC_API_KEY`.
- The answer is read from `structured_output`, and usage and `total_cost_usd` are recorded with budget cost 0.
- Each error maps to its code: rate limit, not logged in, timeout (the process killed), bad JSON, `is_error`, refusal.

### Package

- A fact line without a source is marked.
- A duplicate source is dropped.
- `> ` is removed.
- An invalid package writes nothing.
- Sources merge into the production by url.

### Mission `topic`

- Without the adapter, the plan cannot be confirmed.
- research → researching applies the draft and skips `write`.
- facts still runs.
- Generation starts only when paid services are allowed, and within the budget.

### Editor

- The run is started.
- The draft is returned unsaved.
- Its sources are written only on save.

### One real run

It needs the operator's OK, since it uses the plan. It writes one video on Israel's eucalyptus afforestation and checks:
- that no CLAUDE.md, hook or plugin text reaches the run;
- the time taken and the API-equivalent cost;
- the sources and the voice.

## Later, not now

- Claude Code reading the library through an MCP server, to pick quotes itself.
- Archival photos and footage fetched from the web (Wikimedia, archives).
- Falling back to Sonnet when Opus is out of quota.
- Several Claude Code runs at once.
