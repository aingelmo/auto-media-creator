"""Orquestacion de Capa 1 para una sesion: sessions/<session_id>/ (ver #1)."""
from __future__ import annotations

from pathlib import Path

from .ingest import (
    TONEMAP_CHAIN_HLG, IngestError, build_manifest, build_proxy, cut_music,
    normalize_image, probe_video_source, sha256_file, write_manifest,
)
from .verify import verify_source

VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def run_ingest(
    session_dir: Path,
    threads: int = 4,
    music_offset_s: float = 0.0,
    music_max_duration_s: float | None = None,
) -> dict:
    session_dir = Path(session_dir)
    inputs = session_dir / "inputs"
    proxies_dir = session_dir / "proxies"
    inputs_norm_dir = session_dir / "inputs_norm"
    music_dir = session_dir / "music"

    sources: list[dict] = []

    for path in sorted(inputs.iterdir()):
        ext = path.suffix.lower()
        if ext in VIDEO_EXTS:
            info = probe_video_source(path)
            proxy_path = proxies_dir / f"{path.stem}.mp4"
            build_proxy(info, proxy_path, threads=threads)

            tonemap_chain = TONEMAP_CHAIN_HLG if info.hdr in ("hlg", "dv84") else ""
            verified, results = verify_source(
                original=str(path), proxy=str(proxy_path), tonemap_chain=tonemap_chain,
            )
            if not verified:
                raise IngestError(
                    f"proxy/original temporal mismatch for {path}: "
                    f"{[(r.t_s, r.distances) for r in results]}"
                )

            entry = {
                "src": str(path.relative_to(session_dir)),
                "sha256": info.sha256,
                "type": "video",
                "raw_w": info.raw_w, "raw_h": info.raw_h, "rotation": info.rotation,
                "w": info.w, "h": info.h,
                "duration_s": info.duration_s, "start_time_s": info.start_time_s,
                "nb_frames_est": info.nb_frames_est, "vfr": info.vfr,
                "src_fps_nominal": info.src_fps_nominal, "hdr": info.hdr,
                "color": info.color,
                "proxy": str(proxy_path.relative_to(session_dir)),
                "proxy_verified": True,
            }
            sources.append(entry)
        elif ext in IMAGE_EXTS:
            norm_path = inputs_norm_dir / f"{path.stem}.jpg"
            w, h = normalize_image(path, norm_path)
            sources.append({
                "src": str(path.relative_to(session_dir)),
                "sha256": sha256_file(path),
                "type": "image", "w": w, "h": h,
                "normalized": str(norm_path.relative_to(session_dir)),
            })

    music = None
    track = music_dir / "track.mp3"
    if track.exists():
        if music_max_duration_s is None:
            raise IngestError("music/track.mp3 present but music_max_duration_s not given")
        cut_path = music_dir / "track_cut.wav"
        cut_music(track, cut_path, music_offset_s, music_max_duration_s)
        music = {
            "src": str(track.relative_to(session_dir)), "src_sha256": sha256_file(track),
            "offset_s": music_offset_s, "max_duration_s": music_max_duration_s,
            "cut": str(cut_path.relative_to(session_dir)), "cut_sha256": sha256_file(cut_path),
        }

    manifest = build_manifest(session_dir.name, sources, music)
    write_manifest(manifest, session_dir / "manifest.json")
    return manifest
