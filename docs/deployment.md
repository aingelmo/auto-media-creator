# Deployment

How to run `edl-agent` outside this dev machine: required system
dependencies, why the obvious ffmpeg builds don't work, and a Docker
setup for cloud deployment.

## 1. Runtime requirements

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.14 | Via `uv` (`pyproject.toml`). |
| Node/npm | 22 (build-time only) | Only to build the web UI once; the Python server needs no node at runtime. |
| ffmpeg + ffprobe | full-featured static build (see §2) | Must provide the filters in §3. Resolved from `PATH` as bare `ffmpeg`/`ffprobe`. |
| LLM access | API keys **or** local Ollama | `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`; `ollama` provider needs a reachable Ollama server. Cloud: use API keys. |
| Disk for `var/` | SSD recommended | Sessions, feature cache, downloaded models. Override location with `EDL_AGENT_VAR` (see `src/edl_agent/paths.py`); mount it as a volume so sessions survive restarts. |

Web UI caveats (from `README.md`): single-process, no auth, job
progress lives in memory and is lost on restart. Don't expose it
beyond your own machine/LAN without a reverse proxy adding auth/TLS.

## 2. ffmpeg: use a full static build

The pipeline needs filters that distro and Homebrew builds routinely
omit. Verified 2026-09-29 on Ubuntu/WSL2 (x86_64):

| Build | `zscale` | `drawtext` | `ass`/`subtitles` | Verdict |
|---|---|---|---|---|
| linuxbrew ffmpeg 9 | no | no | no | Unusable: HDR proxy, hook text, and outro handle all fail. |
| Debian/Ubuntu `apt` ffmpeg | no | yes | yes | Partial: works only via the `TONEMAP_CHAIN_HLG_BASIC` fallback (see §4). |
| johnvansickle static | yes | **no** | yes | Do **not** use: ships `--enable-libfreetype` but no `drawtext` filter (upstream trac #10705; also dropped by Debian/Arch for the same harfbuzz reason). Site also looks stale (2024 dates). |
| [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) `linux64-gpl` | yes | yes | yes | **Recommended.** Monthly autobuilds off current master; includes `libplacebo` too. Needs the GPL variant (pipeline encodes `libx264`). |

Install (x86_64; for arm64 use the `linuxarm64-gpl` asset):

```bash
mkdir -p /tmp/ffdl ~/.local/bin && cd /tmp/ffdl
curl -sLO https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
curl -sL https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256 \
  | grep "linux64-gpl.tar.xz" | sha256sum -c -
tar xf ffmpeg-master-latest-linux64-gpl.tar.xz
cp ffmpeg-master-latest-linux64-gpl/bin/{ffmpeg,ffprobe} ~/.local/bin/
```

Ensure the install dir precedes any brew/apt ffmpeg in `PATH`.
This dev machine uses `~/.local/bin`, which already shadows linuxbrew.

## 3. Required filters (preflight)

Every stage resolves `ffmpeg` from `PATH`. After installing, assert:

```bash
ffmpeg -hide_banner -filters | awk \
  '$2=="zscale"||$2=="drawtext"||$2=="ass"||$2=="tonemap"||$2=="colorspace"{print $2}'
# must print all five; if any is missing, that stage fails with
# `No such filter` (exit 8)
```

Which stage needs what:

- ingest proxy (`ingest/proxy.py`): `zscale` + `tonemap`, or the
  fallback pair `tonemap` + `colorspace` (see §4).
- render hook text (`render/_common.py` `hook_text_filter`): `ass`
  (libass). Missing it fails fast with `RenderError`, not a
  silent drop.
- render outro/end-card text: `drawtext` (libfreetype + harfbuzz).
- render/preview/verify plumbing: `scale`, `crop`, `overlay`,
  `boxblur`, `eq`, `fade`, `format`, `fps`, `setpts` — present in
  every build met so far.

The test suite also shells out to real ffmpeg, so dev machines need
the same build (notably `test_render.py`, which renders hook text
via `ass`).

## 4. HDR tonemap fallback (no-zscale builds)

`ingest.proxy.tonemap_chain_hlg()` selects the chain at runtime:
the calibrated `zscale` chain when available, else
`tonemap=mobius:desat=0,colorspace=all=bt709:iall=bt2020`. Proxy,
verify, and render all share the selector, so stages stay
consistent within a session. Mobius (not hable): hable fed with
non-linearised HLG input crushes midtones (Y~57 vs ~110 SDR
reference; mobius ~117, checked visually 2026-09-29).
Prefer a full build anyway: the fallback is uncalibrated.

## 5. Cloud (Docker)

```dockerfile
# ---- frontend build ----
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build  # writes to ../src/edl_agent/web/static/

# ---- runtime ----
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl xz-utils ca-certificates && rm -rf /var/lib/apt/lists
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY --from=frontend /app/src/edl_agent/web/static/ ./src/edl_agent/web/static/
# full static ffmpeg (see §2); pin + verify checksum
RUN mkdir -p /tmp/ffdl /usr/local/bin && cd /tmp/ffdl \
 && curl -sLO https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz \
 && curl -sL https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256 \
  | grep "linux64-gpl.tar.xz" | sha256sum -c - \
 && tar xf ffmpeg-master-latest-linux64-gpl.tar.xz \
 && cp ffmpeg-master-latest-linux64-gpl/bin/ffmpeg* /usr/local/bin/ \
 && rm -rf /tmp/ffdl
ENV EDL_AGENT_VAR=/data
VOLUME /data
EXPOSE 8000
CMD ["uv", "run", "scripts/run_web.py", "--host", "0.0.0.0", "--port", "8000"]
```

Notes:

- First run downloads the pose model into `$EDL_AGENT_VAR`; keep
  `/data` persistent or it re-downloads every deploy.
- Pass LLM keys with `-e` (`ANTHROPIC_API_KEY`, …). No Ollama in
  the image; use API providers.
- Threads default to CPU count (`web/jobs.py` `THREADS`); size the
  container's CPU for it — preview render is `ultrafast`, final is
  `medium` preset.
- To pin ffmpeg instead of tracking `latest`, copy the dated asset
  URL and its `sha256` line from the BtbN release page.
