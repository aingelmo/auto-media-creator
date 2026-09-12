"""Layer 1 - Ingestion.

manifest.json, proxies, image normalization, music trimming.
See docs/architecture/arquitectura_edl_agent_v4.md #3.
"""

from __future__ import annotations

from ._common import TARGET, IngestError, sha256_file
from .manifest import build_manifest, write_manifest
from .media import cut_music, normalize_image
from .probe import (
    VideoSourceInfo,
    _rotation,
    _video_stream,
    classify_hdr,
    ffprobe,
    post_rotation_dims,
    probe_video_source,
)
from .proxy import TONEMAP_CHAIN_HLG, build_proxy

__all__ = [
    "TARGET",
    "TONEMAP_CHAIN_HLG",
    "IngestError",
    "VideoSourceInfo",
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
