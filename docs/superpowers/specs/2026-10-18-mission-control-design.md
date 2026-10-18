# Mission Control

Date: 2026-10-18. From the Mission Control functional spec and the cyberpunk bento style prompt the operator gave; scope P0
and part of P1 (agent fleet with measured health, quality center, resources). Approved in conversation the same day.
Mission Control replaces Phòng máy at `/phong-may`; the new look applies to the whole app.

## Principle

Mission Control is a control plane. Every service keeps its own state (runs and stages in the orchestrator, tasks in the
producer, renders in projects, recipes in Visual Quality); Mission Control reads them and sends commands through their own
interfaces. A mission keeps only what was asked and planned, and what it started.

## 1. Missions

- `missions` (core/missions.py): the operator's words, the plan, the operator's state (`draft | planned | confirmed |
  paused | cancelled`), what it started (`projects`, `tasks`, `runs`), its own events (created, planned, edited, confirmed,
  paused, resumed, cancelled, retried), times.
- **The business status is derived**, never stored twice (agents/missions.py): Draft (no usable plan) → Planned (waiting for
  confirmation) → Queued → Running → Awaiting Approval → Completed, and Blocked, Failed, Cancelled, Partially Completed,
  Paused. From the children: a producer task `working | waiting_operator | done | failed | paused | cancelled`, a run's
  status. Any child waiting for the operator → Awaiting Approval; any running → Running; all finished well → Completed; some
  well, some failed → Partially Completed.
- **The execution state is said beside it**: held for the background hours, waiting for a retry, stalled (no heartbeat),
  waiting for the operator at a gate.

## 2. Composer

- The model turns the operator's words into a plan but may only choose from a catalogue of what NEXORA can really do:
  - `video`: N videos from the library, each carried by the Producer (goal, format, lines, stock fill, self-critique).
  - `understand`: describe the library footage not yet understood (library.understand per asset).
  - `transcribe`: listen to the footage with speech not yet transcribed (library.transcribe).
- A plan: goal, kind, inputs (count, format, lines, channel, template), constraints, budget (USD), permissions (paid
  services allowed or not; publishing is never part of a mission), acceptance criteria, autonomy (the current level, shown).
- **Checked by code, not by the model:** the kind's pipeline must be available on this machine (the capability matrix); the
  mission budget must fit what is left of the day's and month's budgets; a paid service needs the permission. A problem
  makes the plan a Draft with the reason; it is confirmed only when there is none.
- The operator edits the plan and confirms; only then does anything run. A video mission gives each project a budget cap of
  budget ÷ count, which generation already enforces.

## 3. Queue and live monitor

- Missions filtered by status; pause (producer tasks stop taking steps; a stage already running finishes), resume, cancel
  (tasks cancelled, runs cancelled), retry (each failed stage of its runs again).
- A mission opened: each child with its stages, attempts (start, seconds, outcome, error), cost, and the events in order.
- Work started outside missions (ingest, understanding, ideas) is listed as system work.

## 4. Approval center

Everything waiting for the operator, in one list, each with what asked, why, what it touches, the cost, and what follows:
gate stages waiting for review, blocked stages, producer tasks waiting for the operator, blocked ideas, open storyboard and
Copilot proposals, VQ recipes proposed, missions planned and not confirmed. Decided here where the decision is simple
(confirm a mission; approve or send back a cut with a comment; a gate stage); otherwise "open" goes to the screen where it is
looked at. Nothing goes ahead by itself: silence is never consent.

## 5. Budget and resources

- Spent today and this month against the budgets; by mission, project, provider and model.
- Measured on this machine: memory (vm_stat, out of 24 GB), CPU load, disk free, the queue by lane (ready, running), heavy
  stages running; the kill switch on the overview.

## 6. Agent fleet (P1)

Producer, Director, Copilot, Autonomy, idea finder, the two workers, and the engines behind them (Ollama and each model,
speech recognition, FFmpeg, the voice, connections such as RunPod, fal, ComfyUI). States from real checks:
Healthy, Busy (it is doing work now), Degraded (it runs but something it needs is missing), Offline (a required dependency
is down), Disabled (switched off: the kill switch, or an optional engine not set up).

## 7. Quality center (P1)

Every cut, mapped from its measured QC: FAIL (a check failed), PASS WITH WARNINGS (passed with findings), PASS, MANUAL REVIEW
(no measured checks, such as an imported render). Beside it, the operator's review (waiting, approved, sent back).

## 8. Artifacts, logs

- Artifacts: per project (missions' first), its lineage: source footage → script versions → cuts → renders → packages. Only
  links; nothing is copied.
- Logs: the mission events, run events, the audit of every change made through the interface, the model calls; filtered by
  kind. Keys never reach a log (the audit holds paths only).

## 9. Look, whole app

Background #0B0F19 with a slow gradient mesh (still when reduced motion is asked for); electric purple and cyber cyan as the
signal colours, glowing on hover and focus; glass cards (backdrop blur, a faint white border, semi-transparent); rounded
corners; HUD touches (thin grid, dot matrix, small data labels). State colours keep their meaning: amber waits, red stopped,
green passed, orange the machine at work. Done through the theme tokens and shared classes, not screen by screen.

## Tests

Fake model: planning a mission and its checks (unavailable kind, over budget, paid without permission), confirming into
producer tasks with a budget cap, the derived status from runs and tasks, pause, cancel and retry, the approvals list, the
fleet states, the QC verdicts. Then one real mission on the library with the local model, stopping at the clip review.
