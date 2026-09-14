"""Shared source-extension sets and helpers for session layers."""

from __future__ import annotations

from edl_agent.ingest import TONEMAP_CHAIN_HLG

VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
MUSIC_EXTS = {".mp3", ".wav", ".mp4", ".m4a"}


def tonemap_chain_for_manifest(manifest: dict) -> str:
    """Pick the HDR tonemap chain to use for this session's render step.

    Args:
        manifest: Parsed `manifest.json` (see `ingest.build_manifest`).

    Returns:
        `TONEMAP_CHAIN_HLG` if any video source is `hlg`/`dv84`, `""`
        otherwise. The same chain must be used for the proxy (#3.2), the
        planner's `render_profile` provenance, and the actual render step
        (`render.render_segments`/`render_preview_segments`) -- passing a
        different value to render than what was used/recorded elsewhere
        renders HDR sources without tonemapping (#9 R2 mismatch).
    """
    return (
        TONEMAP_CHAIN_HLG
        if any(
            s.get("hdr") in ("hlg", "dv84")
            for s in manifest["sources"]
            if s["type"] == "video"
        )
        else ""
    )
