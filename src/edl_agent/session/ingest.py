"""Orchestration of Layer 1 for a session, per #1/#3."""

from __future__ import annotations

from pathlib import Path

from edl_agent.ingest import (
    TONEMAP_CHAIN_HLG,
    IngestError,
    build_manifest,
    build_proxy,
    cached_info,
    cut_music,
    link_into,
    normalize_image,
    probe_video_source,
    sha256_file,
    store_info,
    tmp_path,
    write_manifest,
)
from edl_agent.session._common import IMAGE_EXTS, MUSIC_EXTS, VIDEO_EXTS
from edl_agent.verify import verify_source


def run_ingest(
    session_dir: Path,
    threads: int = 4,
    music_offset_s: float = 0.0,
    music_max_duration_s: float | None = None,
    cache_root: Path | None = None,
) -> dict:
    """Ingest a full session, per #1/#3.

    Probes and builds proxies for each video source, verifies each proxy
    against its original, normalizes each image source, and cuts the music
    track. Writes `manifest.json` to `session_dir`.

    Args:
        session_dir: Session directory; must already contain `inputs/` (and
            optionally a `music/track.<mp3|wav>` file).
        threads: ffmpeg thread count for proxy encoding.
        music_offset_s: Start offset into the music track, in seconds.
        music_max_duration_s: Max duration of the cut music clip, in
            seconds. Required if a music track exists.
        cache_root: If given, a content-addressed cache directory (keyed
            by source sha256) reused across sessions for `probe`+
            `build_proxy`+`verify_source`; `proxies/<stem>.mp4` becomes a
            symlink into it. `None` disables caching.

    Returns:
        The `manifest.json` dict (see `ingest.build_manifest`).

    Raises:
        IngestError: If a music track exists but `music_max_duration_s`
            was not given. A video proxy failing temporal verification
            against its original does not abort the run; it's recorded
            as `proxy_verified: false` in the manifest instead.
    """
    session_dir = Path(session_dir)
    inputs = session_dir / "inputs"
    proxies_dir = session_dir / "proxies"
    inputs_norm_dir = session_dir / "inputs_norm"
    music_dir = session_dir / "music"

    sources: list[dict] = []

    for path in sorted(inputs.iterdir()):
        ext = path.suffix.lower()
        if ext in VIDEO_EXTS:
            proxy_path = proxies_dir / f"{path.stem}.mp4"
            sha = sha256_file(path)
            hit = cached_info(cache_root, sha, path) if cache_root else None
            if cache_root and hit:
                info, verified = hit
                link_into(proxy_path, cache_root / sha / "proxy.mp4")
            else:
                info = probe_video_source(path)
                proxy_target = (
                    cache_root / sha / "proxy.mp4" if cache_root else proxy_path
                )
                build_target = tmp_path(proxy_target) if cache_root else proxy_target
                build_proxy(info, build_target, threads=threads)
                if cache_root:
                    build_target.replace(proxy_target)

                tonemap_chain = TONEMAP_CHAIN_HLG if info.hdr in ("hlg", "dv84") else ""
                verified, results = verify_source(
                    original=str(path),
                    proxy=str(proxy_target),
                    tonemap_chain=tonemap_chain,
                )
                if not verified:
                    print(
                        f"WARNING: proxy/original temporal mismatch for {path}: "
                        f"{[(r.t_s, r.distances) for r in results]}"
                    )
                if cache_root:
                    store_info(cache_root, info, verified)
                    link_into(proxy_path, proxy_target)

            entry = {
                "src": str(path.relative_to(session_dir)),
                "sha256": info.sha256,
                "type": "video",
                "raw_w": info.raw_w,
                "raw_h": info.raw_h,
                "rotation": info.rotation,
                "w": info.w,
                "h": info.h,
                "duration_s": info.duration_s,
                "start_time_s": info.start_time_s,
                "nb_frames_est": info.nb_frames_est,
                "vfr": info.vfr,
                "src_fps_nominal": info.src_fps_nominal,
                "hdr": info.hdr,
                "color": info.color,
                "has_audio": info.has_audio,
                "proxy": str(proxy_path.relative_to(session_dir)),
                "proxy_verified": verified,
            }
            sources.append(entry)
        elif ext in IMAGE_EXTS:
            norm_path = inputs_norm_dir / f"{path.stem}.jpg"
            w, h = normalize_image(path, norm_path)
            sources.append(
                {
                    "src": str(path.relative_to(session_dir)),
                    "sha256": sha256_file(path),
                    "type": "image",
                    "w": w,
                    "h": h,
                    "normalized": str(norm_path.relative_to(session_dir)),
                }
            )

    music = None
    track = None
    if music_dir.is_dir():
        track = next(
            (p for p in sorted(music_dir.iterdir()) if p.suffix.lower() in MUSIC_EXTS),
            None,
        )
    if track is not None:
        if music_max_duration_s is None:
            msg = f"{track} present but music_max_duration_s not given"
            raise IngestError(msg)
        cut_path = music_dir / "track_cut.wav"
        cut_music(track, cut_path, music_offset_s, music_max_duration_s)
        music = {
            "src": str(track.relative_to(session_dir)),
            "src_sha256": sha256_file(track),
            "offset_s": music_offset_s,
            "max_duration_s": music_max_duration_s,
            "cut": str(cut_path.relative_to(session_dir)),
            "cut_sha256": sha256_file(cut_path),
        }

    manifest = build_manifest(session_dir.name, sources, music)
    write_manifest(manifest, session_dir / "manifest.json")
    return manifest
