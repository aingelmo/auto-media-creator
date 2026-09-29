# edl-agent deploy image for linux/arm64 (OCI Ampere A1 homelab host).
#
# Satisfies docs/deployment.md #2 (BtbN linuxarm64-gpl static ffmpeg) and #5.
# Reproducible from a clean checkout:
#   docker buildx build --platform linux/arm64 -t <ref> .
# The ffmpeg asset follows TARGETARCH, so an amd64 build also works
# (linux64-gpl) for local smoke tests; the published image is arm64-only.

# ---- frontend build (node lives only here; the runtime needs no node) ----
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.14-slim

# tzdata: TZ env honored for log timestamps. libgomp1: torch/opencv
# runtime. curl/xz-utils/ca-certificates: ffmpeg fetch below.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl libgomp1 tzdata xz-utils \
    && rm -rf /var/lib/apt/lists

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
COPY scripts/ ./scripts/
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/src/edl_agent/web/static/ ./src/edl_agent/web/static/

# Full static ffmpeg with every filter the pipeline needs (see
# docs/deployment.md #2-3). Pin a dated release with
# --build-arg FFMPEG_TAG=<date> instead of tracking latest.
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

# Container contract: EDL_AGENT_VAR defaults to /data/edl-agent (bind
# mount, survives restarts); PORT honored by scripts/run_web.py.
ENV EDL_AGENT_VAR=/data/edl-agent \
    PORT=8000 \
    PYTHONUNBUFFERED=1
VOLUME /data/edl-agent
EXPOSE 8000

# Rootless: the server runs as UID 1000, so the bind mount must be owned
# by (or writable for) UID 1000 on the host.
RUN useradd -m -u 1000 appuser \
  && mkdir -p /data/edl-agent \
  && chown -R appuser:appuser /app /data/edl-agent
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD /app/.venv/bin/python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'))"

CMD ["/app/.venv/bin/python", "scripts/run_web.py", "--host", "0.0.0.0", "--no-reload"]
