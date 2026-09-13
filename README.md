# edl-agent

Builds an EDL (edit decision list) for automated video montage: ingest →
candidate selection → planning (LLM-assisted) → render.

## Setup

```bash
uv sync
```

## Web UI (recommended)

```bash
uv run scripts/run_web.py
```

Open http://127.0.0.1:8000/. From there you can:

- see existing sessions (`sessions/<name>`) and their status,
- start a new session (`/new`): upload clips/photos + a music track, pick an
  LLM provider/model, and submit — the pipeline runs in the background,
- watch a session's page for live progress, then preview/download the
  rendered `reel.mp4` and view the render checks once it's done.

Options: `--host HOST` (default `127.0.0.1`), `--port PORT` (default `8000`).

The web UI is local-only, single-process, no auth: job progress lives in
memory and is lost on restart, and it's not meant to be exposed beyond your
own machine/LAN.

LLM API keys are read from the environment (e.g. `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`/`GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`); `ollama` needs a
local Ollama server instead.

## CLI (scripting / dev)

```bash
uv run scripts/run_e2e.py sessions/<name> [--provider ollama] [--model qwen3-vl:8b-instruct]
```

A session directory needs `inputs/` (clips/photos) and `music/track.mp3`
before running; see `--help` for tuning options (threads, pose model, music
cut, tonemap chain).

## Checks

```bash
uv run ruff check .
uv run ty check
uv run pytest -q
```
