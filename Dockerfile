# edl-agent deploy image for linux/arm64 (OCI Ampere A1 homelab host).
#
# Satisfies docs/deployment.md #2 (BtbN linuxarm64-gpl static ffmpeg) and #5.
# Reproducible from a clean checkout:
#   docker buildx build --platform linux/arm64 -t <ref> .
# The ffmpeg asset follows TARGETARCH, so an amd64 build also works
# (linux64-gpl) for local smoke tests; the published image is arm64-only.
#
# Build-speed design (slow, stable layers first; fast, volatile last):
# ffmpeg (depends only on build args) -> locked deps (only on
# pyproject/uv.lock change, via bind mounts + uv cache mount) ->
# project install (on every src change, but seconds: deps already
# satisfied, `uv pip --no-deps` never reconciles siblings).

# ---- frontend build (node lives only here; the runtime needs no node) ----
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.14-slim

# tzdata: TZ env honored for log timestamps. libgomp1: torch/numpy
# runtime. libgl1/libglib2.0-0/libxcb1: belt-and-braces for
# opencv/scipy native libs (the image ships headless opencv only,
# see below, but a GUI-linked .so anywhere in the tree must still
# find these at import instead of crash-looping the server).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl libgl1 libglib2.0-0 libgomp1 libxcb1 tzdata \
      xz-utils \
    && rm -rf /var/lib/apt/lists

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# UV_LINK_MODE=copy: the uv cache is a mount (different filesystem
# from the venv), so hardlinking would warn/fail. VIRTUAL_ENV+PATH:
# every `uv`/`python` below targets the venv (also fixes bare
# `docker exec <c> python` hitting the system interpreter).
ENV UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Created early so the dependency layer below can hand ownership
# over in the same RUN (a later `chown -R` would duplicate the
# ~2 GB venv in a second layer) and COPY --chown works.
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Full static ffmpeg with every filter the pipeline needs (see
# docs/deployment.md #2-3). First on purpose: it depends only on
# the build args, so code/dependency changes never re-fetch it.
# Pin a dated release with --build-arg FFMPEG_TAG=<date> instead
# of tracking latest.
ARG FFMPEG_TAG=latest
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH}" in \
      arm64) FFARCH=linuxarm64 ;; \
      amd64) FFARCH=linux64 ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    ASSET="ffmpeg-master-${FFMPEG_TAG}-${FFARCH}-gpl.tar.xz"; \
    mkdir -p /tmp/ffdl && cd /tmp/ffdl; \
    curl -fsSL --retry 8 --retry-all-errors --retry-delay 10 \
      -o "${ASSET}" "https://github.com/BtbN/FFmpeg-Builds/releases/download/${FFMPEG_TAG}/${ASSET}"; \
    curl -fsSL --retry 8 --retry-all-errors --retry-delay 10 \
      "https://github.com/BtbN/FFmpeg-Builds/releases/download/${FFMPEG_TAG}/checksums.sha256" \
      | grep "master-${FFMPEG_TAG}-${FFARCH}-gpl.tar.xz" | sha256sum -c -; \
    tar xf "${ASSET}"; \
    cp "${ASSET%.tar.xz}/bin/ffmpeg" "${ASSET%.tar.xz}/bin/ffprobe" /usr/local/bin/; \
    rm -rf /tmp/ffdl; \
    ffmpeg -hide_banner -buildconf; \
    ffmpeg -hide_banner -buildconf | grep -q -- "--enable-gpl"; \
    for f in zscale drawtext ass tonemap colorspace; do \
      ffmpeg -hide_banner -filters \
        | awk -v want="$f" '$2==want{found=1} END{exit !found}'; \
    done

# Locked dependencies. Bind mounts (not COPY) so only the venv lands
# in the layer — src edits never invalidate it. The uv cache mount
# means re-runs only fetch deltas (and it never lands in the image,
# so no prune step). Single RUN so deleted bytes never persist:
# `uv sync` pulls a GUI `opencv-python` via ultralytics/scenedetect
# (it was the `libxcb.so.1` crash-loop), which is evicted here while
# headless is reinstalled to restore the shared cv2/ files.
# torch needs no surgery: the lock forks `torch/torchvision` to the
# PyTorch CPU index on linux/aarch64 (see pyproject `[tool.uv.sources]`).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    set -eux; \
    uv sync --frozen --no-dev --no-install-project; \
    CV_VER="$(python3 -c "import tomllib;print(next(p['version'] for p in tomllib.load(open('uv.lock','rb'))['package'] if p['name']=='opencv-python-headless'))")"; \
    uv pip uninstall -y opencv-python; \
    uv pip install --force-reinstall --no-deps \
      "opencv-python-headless==${CV_VER}"; \
    python -c "import cv2; print(cv2.__version__)"; \
    python -c "import torch; assert not torch.cuda.is_available(), torch.__version__; print(torch.__version__)"; \
    # Only the venv: the bind-mounted manifests are read-only and
    # aren't part of the image anyway.
    chown -R appuser:appuser /app/.venv

# Project install. Rebuilds on every src change, but stays at
# seconds: all deps are satisfied above, and `uv pip --no-deps`
# installs only edl-agent itself without reconciling siblings
# (a plain `uv sync` here would reinstall the evicted GUI opencv
# and, on arm64, the PyPI CUDA torch).
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser --from=frontend /app/src/edl_agent/web/static/ ./src/edl_agent/web/static/
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eux; \
    uv pip install --no-deps .; \
    python -c "import edl_agent.web.app; print('app import ok')"

# Container contract: EDL_AGENT_VAR defaults to /data/edl-agent (bind
# mount, survives restarts); PORT honored by scripts/run_web.py.
ENV EDL_AGENT_VAR=/data/edl-agent \
    PORT=8000 \
    PYTHONUNBUFFERED=1
VOLUME /data/edl-agent
EXPOSE 8000

# Rootless: the server runs as UID 1000 (`appuser`; /app already
# handed over in the build layer). The `EDL_AGENT_VAR` bind mount
# must therefore be writable by UID 1000 on the host — e.g.
# `chown -R 1000:1000 /host/path` (preferred) or a group-write bit
# with GID 1000. A root-owned mount fails writes; that is a host
# permission issue, not an image bug. There is one explicit
# deviation from "any non-root UID works": only UID 1000 (or
# equivalent write access) works, because the image can't chown a
# host mount from inside as a non-root user.
RUN mkdir -p /data/edl-agent && chown -R appuser:appuser /data/edl-agent
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD /app/.venv/bin/python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'))"

CMD ["/app/.venv/bin/python", "scripts/run_web.py", "--host", "0.0.0.0", "--no-reload"]
