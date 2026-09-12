"""Layer 1 - Ingestion.

manifest.json, proxies, image normalization, music trimming.
See docs/architecture/arquitectura_edl_agent_v4.md #3.
"""

from __future__ import annotations

from edl_agent.ingest._common import TARGET, IngestError, sha256_file
from edl_agent.ingest.manifest import build_manifest, write_manifest
from edl_agent.ingest.media import cut_music, normalize_image
from edl_agent.ingest.probe import (
    VideoSourceInfo,
    _fps,
    _rotation,
    _video_stream,
    classify_hdr,
    ffprobe,
    post_rotation_dims,
    probe_video_source,
)
from edl_agent.ingest.proxy import TONEMAP_CHAIN_HLG, build_proxy

__all__ = [
    "TARGET",
    "TONEMAP_CHAIN_HLG",
    "IngestError",
    "VideoSourceInfo",
    "_fps",
    "_rotation",
    "_video_stream",
    "build_manifest",
    "build_proxy",
    "classify_hdr",
    "cut_music",
    "ffprobe",
    "normalize_image",
    "post_rotation_dims",
    "probe_video_source",
    "sha256_file",
    "write_manifest",
]
