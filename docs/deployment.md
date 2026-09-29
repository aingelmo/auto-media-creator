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

Ensure the install dir precedes any brew/apt ffmpeg in `PATH` —
a brew-first login shell will otherwise keep shadowing the full
build (this bit us: the web server kept resolving linuxbrew's
ffmpeg). On this dev machine `~/.zshrc.local` (sourced last from
`~/.zshrc`, outside chezmoi) prepends `~/.local/bin`, so every new
shell defaults to the static build.

### PATH pitfalls and the `EDL_AGENT_FFMPEG` override

Every stage resolves the binary through a shared helper
(`edl_agent.ffmpeg`), but it still starts from the **server
process's** `PATH` — which can differ from your shell (e.g. a
brew-first login shell), silently picking the minimal build. Two
guardrails cover this:

- Set `EDL_AGENT_FFMPEG=/path/to/ffmpeg` to pin the binary
  explicitly (`ffprobe` is resolved as its sibling when present,
  else via `PATH`). Recommended whenever `which ffmpeg` disagrees
  between shells.
- Every job (web pipeline and `scripts/run_e2e.py`) runs a
  preflight first: if the resolved binary lacks a filter the
  graphs need (`drawtext`, `ass`, `tonemap`, `colorspace` —
  `zscale` is exempt, the fallback chain covers it), the job fails
  immediately naming the binary and the missing filters instead of
  dying with `exit 8` mid-render.

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

## 5. Cloud (Docker, linux/arm64)

The repo-root `Dockerfile` is the single build definition: node stage
builds the web UI, `python:3.14-slim` runtime stage installs deps via
`uv sync --frozen --no-dev` and fetches the BtbN `linuxarm64-gpl`
static ffmpeg (§2) with checksum verification plus a build-time assert
that `--enable-gpl` and all five filters (`zscale`, `drawtext`, `ass`,
`tonemap`, `colorspace`) are present. CI
(`.github/workflows/docker-arm64.yml`, native `ubuntu-24.04-arm`
runner, no qemu) builds `linux/arm64` and pushes to GHCR on every
`main` push touching the image inputs:

- `ghcr.io/aingelmo/auto-media-creator:latest-linuxarm64-gpl` (moving)
- `ghcr.io/aingelmo/auto-media-creator:<shortsha>-linuxarm64-gpl`
  (pinned — use this in deploy manifests)

Reproduce from a clean checkout:

```bash
docker buildx build --platform linux/arm64 -t edl-agent:dev .
```

An amd64 build also works (it embeds the `linux64-gpl` asset instead)
for Dockerfile smoke tests on x86 hosts; only arm64 is published.
Pin ffmpeg to a dated release with
`--build-arg FFMPEG_TAG=<date>` instead of tracking `latest`.

Container contract (what the homelab wrapper relies on):

| Item | Value |
|---|---|
| Port | 8000; `scripts/run_web.py` honors `PORT` when set |
| Health | `GET /health` → 200 `{"status": "ok"}`, dependency-free so it answers mid-job; allow a 120s start window (also the image `HEALTHCHECK` start period) |
| Data dir | `EDL_AGENT_VAR`, image default `/data/edl-agent` (bind mount, survives restarts); local default `./var` |
| User | UID 1000 (`appuser`, rootless). Explicit deviation: the bind mount must be writable by UID 1000 (`chown -R 1000:1000 /host/path`); any-other-UID mounts fail writes |
| TZ | Honored for log timestamps (tzdata installed; OS-level, no code support needed) |
| Secrets | None baked in (`.env` is `.dockerignore`d); enter keys once in web Settings (persisted in the data volume) or pass `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` / `GEMINI_API_KEY` with `-e` — env always wins (full list in `.env.example`) |
| Networking | No host-port assumptions; Traefik routes to :8000 internally |
| torch | CPU-only on linux/aarch64 (`torch==<lock>+cpu` from the PyTorch CPU index, forked in `uv.lock` via `[tool.uv.sources]`; every other platform keeps PyPI) — the target has no NVIDIA GPU, so the PyPI CUDA userspace never enters the ARM image |
| opencv | `opencv-python-headless` only; the GUI `opencv-python` that `ultralytics`/`scenedetect` pull in is evicted at build time (it was the `libxcb.so.1` crash-loop). The `libgl1`/`libglib2.0-0`/`libxcb1` apt libs stay as belt-and-braces |

Every push that rebuilds the image also cold-boots the pinned tag
on native ARM (`verify` job) and asserts the contract above —
`/health` within 120s, `PORT` honored, `id -u` == 1000,
`EDL_AGENT_VAR` honored, `TZ` honored, `import cv2`, CPU-only
torch, GPL/`aarch64` ffmpeg buildconf — and prints the
uncompressed image size plus PID 1 `VmHWM`/`VmRSS`. Use the pinned
`<shortsha>-linuxarm64-gpl` tag from a green run in deploy
manifests, and copy its reported size/RSS into the homelab notes.

Measured 2026-09-29 (`428d7d6-linuxarm64-gpl`, native ARM verify):
uncompressed **2.40 GB**; cold-boot `/health` 200 on the first
probe seconds after start; idle PID 1 `VmHWM`/`VmRSS` **~163 MB**
(`cv2` 5.0.0, `torch` 2.14.0+cpu, `ffmpeg` `--enable-gpl`
`aarch64`). Render-time peak is workload-dependent — see the
~4.6 GB process-tree figure in the notes below; the 8 GB cap still
fits a single flight, don't run concurrent sessions.

Acceptance (run on ARM, not x86 emulation):

```bash
REF=ghcr.io/aingelmo/auto-media-creator:<shortsha>-linuxarm64-gpl
docker run -d --platform linux/arm64 --name edl \
  -e EDL_AGENT_VAR=/tmp/x -v /tmp/x:/tmp/x "$REF"
sleep 120; curl -sf localhost:8000/health
docker exec edl python -c "import cv2"
docker exec edl ffmpeg -hide_banner -buildconf | grep -i -E "gpl|aarch64"
docker image inspect --format '{{.Size}}' "$REF"  # uncompressed bytes
docker exec edl cat /proc/1/status | grep -E 'VmHWM|VmRSS'
```

Notes:

- First run downloads the pose model into `$EDL_AGENT_VAR`; keep the
  bind mount persistent or it re-downloads every deploy.
- No Ollama in the image; use API providers.
- Sizing: measured no-cache run peaks at **~4.6 GB** process-tree RSS
  (render-only ~1.4 GB), so the homelab's 8 GB cap fits a single
  flight — don't run concurrent sessions. 2 vCPUs work but slowly
  (baseline ~13 min on 8 cores); `THREADS` defaults to 4
  (`web/jobs.py`), which oversubscribes 2 vCPUs without breaking.
  See `docs/light-device-optimizations.md` for the full analysis.

### Updating the static build

BtbN rebuilds `latest` regularly (monthly or better). Updating is
just overwriting the two files — each pipeline stage spawns a fresh
process, so even a running server picks the new binary up on the
next job (restart it anyway so the cached filter probe refreshes):

```bash
ffmpeg -version 2>&1 | head -1  # current build date
cd /tmp/ffdl
curl -sLO https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
curl -sL https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256 \
  | grep "linux64-gpl.tar.xz" | sha256sum -c -
tar xf ffmpeg-master-latest-linux64-gpl.tar.xz
cp ffmpeg-master-latest-linux64-gpl/bin/{ffmpeg,ffprobe} ~/.local/bin/
ffmpeg -hide_banner -filters | awk \
  '$2=="zscale"||$2=="drawtext"||$2=="ass"||$2=="tonemap"||$2=="colorspace"{print $2}'
```
