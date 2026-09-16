"""Layer 1 - Ingestion.

manifest.json, proxies, image normalization, music trimming.
See docs/architecture/03-ingest.md #3.
"""

from __future__ import annotations

from edl_agent.ingest._common import TARGET, IngestError, sha256_file
from edl_agent.ingest.cache import (
    atomic_write_text,
    cached_info,
    link_into,
    source_cache_dir,
    store_info,
    tmp_path,
)
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
    "atomic_write_text",
    "build_manifest",
    "build_proxy",
    "cached_info",
    "classify_hdr",
    "cut_music",
    "ffprobe",
    "link_into",
    "normalize_image",
    "post_rotation_dims",
    "probe_video_source",
    "sha256_file",
    "source_cache_dir",
    "store_info",
    "tmp_path",
    "write_manifest",
]
