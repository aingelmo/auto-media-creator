# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Solo creator cutting personal raw material into a shareable reel. They arrive
with clips/photos plus a music track, start a session via the local web UI
(`/new`), and return to preview/download the finished `reel.mp4`. A secondary
technical operator reuses the same pipeline via CLI (`scripts/run_e2e.py`) for
scripting and dev runs.

## Product Purpose

`edl-agent` builds an EDL (edit decision list) for automated video montage and
renders it: ingest → candidate selection → planning (LLM-assisted) → render,
plus proxy verification. It exists so a solo operator gets a finished,
beat-aligned montage without manual timeline editing. Success is a watchable
`reel.mp4` with passing render checks, produced hands-off from uploaded media
plus one music track.

## Positioning

Fully automatic ingest-to-`mp4` with minimal manual editing. Neighboring
editors sell timeline control; this product sells the absence of it — upload
media, pick a provider/model, confirm pauses, collect the reel.

## Operating Context

Local-only workflow on the operator's own machine/LAN: list sessions in
`var/sessions/<name>`, start a session with uploads + LLM provider/model
choice, follow background job progress on the session page, resolve
low-candidate and verification pauses, then preview/download `reel.mp4` and
inspect render checks. Runtime data (sessions, feature cache, downloaded
models) lives under `var/` (overridable via `EDL_AGENT_VAR`). LLM keys come
from the environment (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`,
`DEEPSEEK_API_KEY`); `ollama` uses a local Ollama server instead. Frontend
source lives in `frontend/`; the served SPA is the prebuilt bundle committed
under `src/edl_agent/web/static/`.

## Capabilities and Constraints

Confirmed functionality: session list/detail/status, ingest manifest review,
candidate review, hook selection, LLM selection review, planner/EDL review,
rendered reel preview + download, retry/regenerate/confirm flows, shared media
library and provider/model config.

Technical constraints: local-only, single-process, no auth. Job progress lives
in memory and is lost on restart. Not meant to be exposed beyond the
operator's machine/LAN. Terminology: manifest, candidates, selection, hooks,
EDL, slots, render checks.

Undecided: target export profiles beyond the current reel, and any multi-user
or hosted operation — future work must not assume either.

## Brand Commitments

Name: `edl-agent`. No confirmed voice, logo, palette, or identity assets to
preserve.

## Evidence on Hand

Full pipeline spec in `docs/architecture/` (v4, Spanish; section numbers map
1:1 to file prefixes). No real testimonials, customers, case studies, press,
pricing, or benchmark claims to reuse — future work must not fabricate them.

## Product Principles

1. Hands-off first: every stage must move the session forward without timeline
   craft from the user.
2. Determinism where it counts: timing, beats, crop, and render stay in code,
   never in model prose.
3. Reproducible sessions: hashes, versions, and render checks let a saved
   session re-render later.
4. Local trust: single-machine operation, explicit pauses, and inspectable
   stage artifacts over hidden magic.
