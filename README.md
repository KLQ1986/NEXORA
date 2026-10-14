# NEXORA

A local-first video factory for one operator on a Mac. It turns a script into a finished video from your own footage
(and, later, from generated footage): it watches and describes what you shot, finds the range inside each clip that fits each
line, and cuts, narrates, captions and checks the result. Everything runs on this machine; the Web UI is at `http://127.0.0.1:8600`.

The design is in `NEXORA_System_Design_v4.0.docx` (with an `.html` twin). The build plan and its current state are in `docs/PLAN.md` (Vietnamese).

## Requirements

- macOS on Apple Silicon, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20 or newer
- FFmpeg and FFprobe (`brew install ffmpeg`)
- [Ollama](https://ollama.com) with the two models: `ollama pull qwen3-vl:8b-instruct` and `ollama pull bge-m3`
- A Vietnamese voice for the `say` command (System Settings > Accessibility > Spoken Content)
- Optional: OpenMontage at `~/openmontage`, for free stock clips when the library has no picture for a line
- Optional: whisper.cpp (`brew install whisper-cpp`) and a ggml model at `data/models/ggml-large-v3-turbo-q5_0.bin`, for speech with a time for every word and the rough cut built on it
- Optional: a RunPod serverless endpoint running a video model (`runpod_api_key` and `runpod_video_endpoint` in `nexora.toml`), for real generated video from approved stills
- Optional: an Anthropic API key in `ANTHROPIC_API_KEY`, to let Claude do text work (never footage) for the tasks you choose in System

## Run

```sh
uv sync                                  # Python dependencies
(cd web && npm install && npm run build) # the Web UI
uv run python -m nexora doctor           # checks every requirement and says what to do about each missing one
uv run python -m nexora serve            # API, Web UI and workers; open http://127.0.0.1:8600
```

## Settings

`uv run python -m nexora init-config` writes `nexora.toml` with every setting and its default (models, voice, port, data folder,
match threshold). The file is optional; a misspelt setting is refused at start rather than ignored.

## Commands

| Command | What it does |
|---|---|
| `serve [--port N]` | Starts the API, the Web UI and one worker per lane. Backs up the database first. |
| `doctor` | Checks tools, models, voice, disk and database. Exit code 1 if something required is missing. |
| `ingest PATH...` | Registers files or folders (video, photographs, music) without the UI. |
| `worker [--drain]` | Runs stages without the server; `--drain` exits when nothing is left. |
| `backup` / `restore FILE` | Copies the database to `data/backups`, or puts a copy back (stop the server first; the replaced database is kept). |
| `runs`, `assets`, `env` | Plain listings for the terminal. |

## What lives where

```
src/nexora/core       platform core: runs, stages and attempts, adapters contract, assets, index, projects, backup, storage
src/nexora/modules    domain modules: planning, library, sourcing, edit, quality, distribution (they may not import each other)
src/nexora/adapters   one file per outside tool: FFmpeg, Ollama, say, captions, OpenMontage, macOS notifications
src/nexora/api        the HTTP API the Web UI talks to
src/nexora/app.py     composition root: the only place that knows every layer
web/                  the Web UI (React, Vite, Tailwind)
data/                 database, derived media, backups, logs (not in git)
```

`uv run lint-imports` enforces the layer and module boundaries; `uv run pytest` runs the tests (no model needed: they use stand-ins).

## What leaves this machine

Nothing, unless one of these is used, and privacy mode (System) turns all of them off at once:

- Stock search: the search words go to the stock libraries.
- Reading a source: the address of the page you name is fetched. Only public web addresses are read.
- Pollinations stills: the prompt and seed. Without an account it gives a few stills, then refuses for a while.
- Claude: the text of the tasks you routed to it, which includes the script and descriptions of your footage. Frames are never sent.

Footage, frames, proxies and audio are only ever read by tools on this machine.

## Data and safety

- Publishing to a folder writes packages to `~/Movies/NEXORA` (the `publish_folder` setting). With the three `youtube_*` settings filled in, cuts can be uploaded to your channel (private by default) and their figures are fetched at each mark; other platforms are uploaded by hand and recorded.

- Your footage is never copied or modified; the library records where it is. If a disk moves, point the library at its new place in System > Nơi chứa footage.
- `data/nexora.db` is the one file that cannot be rebuilt. It is backed up at every start; the newest seven copies are kept.
- Derived files (proxies, frames, cached shots) can be cleaned in System; they are rebuilt on demand.
- `data/logs/stages.jsonl` has one line per stage that ran: what, how long, how it ended.

## Start with the Mac (optional)

Save as `~/Library/LaunchAgents/local.nexora.plist`, adjust the two paths, then `launchctl load ~/Library/LaunchAgents/local.nexora.plist`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.nexora</string>
  <key>WorkingDirectory</key><string>/Users/YOU/NEXORA</string>
  <key>ProgramArguments</key><array><string>/Users/YOU/NEXORA/.venv/bin/python</string><string>-m</string><string>nexora</string><string>serve</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>/tmp/nexora.err.log</string>
</dict></plist>
```
