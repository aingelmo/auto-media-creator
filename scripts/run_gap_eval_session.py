"""Run one gap-eval session end to end; meant to be invoked as its own
process (see run_gap_eval_batch.py) so each session's memory (YOLO, ollama
client, ffmpeg buffers) is fully reclaimed by the OS on exit before the next
session starts.

Usage: uv run scripts/run_gap_eval_session.py <name> <seed>
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edl_agent.features import yolo_pose_detector
from edl_agent.ingest import (
    IngestError,
    VideoSourceInfo,
    build_manifest,
    cut_music,
    sha256_file,
    write_manifest,
)
from edl_agent.llm.ollama_client import OllamaClient
from edl_agent.planner._common import PlannerError
from edl_agent.render import (
    concat_and_audio,
    render_preview_segments,
    render_segments,
    run_render_checks,
)
from edl_agent.session import (
    run_candidates,
    run_planner,
    run_selection,
    tonemap_chain_for_manifest,
)
from edl_agent.slots import slots_from_file

VIDEOS = sorted(
    p for p in (ROOT / "data/test/videos").glob("*")
    if p.suffix.lower() in {".mov", ".mp4"} and "Zone.Identifier" not in p.name
)
SONGS = sorted(
    p for p in (ROOT / "data/test/songs").glob("*.mp4")
    if "Zone.Identifier" not in p.name
)
POSE_MODEL = "models/yolov8n-pose.pt"
THREADS = 4
CACHE_PROXIES = ROOT / "data/test/proxy_cache/proxies"
CACHE_INFO = ROOT / "data/test/proxy_cache/info.json"


def load_pool() -> dict[str, VideoSourceInfo]:
    cached_raw: dict[str, dict] = json.loads(CACHE_INFO.read_text())
    return {
        name: VideoSourceInfo(**{k: v for k, v in d.items() if k != "verified"})
        for name, d in cached_raw.items()
        if d.get("verified") and (CACHE_PROXIES / f"{Path(name).stem}.mp4").exists()
    }


def source_entry(name: str, info: VideoSourceInfo) -> dict:
    """Build a manifest video-source entry from a cached `VideoSourceInfo`.

    Mirrors `session.ingest.run_ingest`'s video branch, but skips
    `build_proxy`/`verify_source` since the shared cache already ran them
    once (see `run_gap_eval_batch.build_proxy_cache`).
    """
    return {
        "src": f"inputs/{name}",
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
        "proxy": f"proxies/{Path(name).stem}.mp4",
        "proxy_verified": True,
    }


def build_session(
    session_dir: Path, seed: int, pool: dict[str, VideoSourceInfo]
) -> dict:
    rng = random.Random(seed)
    names = list(pool)
    n_clips = rng.randint(13, 16)
    clips = rng.sample(names, min(n_clips, len(names)))
    song = rng.choice(SONGS)

    inputs = session_dir / "inputs"
    proxies = session_dir / "proxies"
    music_dir = session_dir / "music"
    inputs.mkdir(parents=True, exist_ok=True)
    proxies.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)

    sources = []
    for name in clips:
        (inputs / name).symlink_to(next(p for p in VIDEOS if p.name == name))
        proxy_src = CACHE_PROXIES / f"{Path(name).stem}.mp4"
        (proxies / f"{Path(name).stem}.mp4").symlink_to(proxy_src)
        sources.append(source_entry(name, pool[name]))
    (music_dir / "track.mp3").symlink_to(song)

    offset = round(rng.uniform(10, 30), 1)
    max_duration = 15.0
    cut_path = music_dir / "track_cut.wav"
    track = music_dir / "track.mp3"
    cut_music(track, cut_path, offset, max_duration)
    music = {
        "src": "music/track.mp3",
        "src_sha256": sha256_file(track),
        "offset_s": offset,
        "max_duration_s": max_duration,
        "cut": "music/track_cut.wav",
        "cut_sha256": sha256_file(cut_path),
    }

    manifest = build_manifest(session_dir.name, sources, music)
    write_manifest(manifest, session_dir / "manifest.json")

    print(f"  clips={clips}")
    print(f"  song={song.name} offset={offset}")
    return manifest


def run_one(name: str, seed: int, pool: dict[str, VideoSourceInfo]) -> dict:
    session = ROOT / "sessions" / name
    detector = yolo_pose_detector(POSE_MODEL)
    client = OllamaClient()

    for attempt in range(6):
        if session.exists():
            shutil.rmtree(session)
        try:
            manifest = build_session(session, seed + attempt * 1000, pool)

            slots = slots_from_file(str(session / "music" / "track_cut.wav"))
            (session / "slots.json").write_text(
                json.dumps(slots, indent=2, ensure_ascii=False)
            )

            candidates = run_candidates(
                session, manifest, slots, detector, pose_model_path=POSE_MODEL
            )
            selection, selection_meta = run_selection(
                session,
                candidates,
                slots,
                config={"model": "qwen3-vl:8b-instruct"},
                client=client,
            )
            (session / "selection.json").write_text(
                json.dumps(selection or {}, indent=2, ensure_ascii=False)
            )
            edl = run_planner(
                session,
                manifest,
                candidates,
                slots,
                selection,
                selection_meta,
                threads=THREADS,
            )
            tonemap_chain = tonemap_chain_for_manifest(manifest)
            render_preview_segments(
                edl, manifest, session, threads=THREADS, tonemap_chain=tonemap_chain
            )
            render_segments(
                edl, manifest, session, threads=THREADS, tonemap_chain=tonemap_chain
            )
            concat_and_audio(edl, session, threads=THREADS)
            checks = run_render_checks(edl, session)
            print(f"  render checks: {checks}", flush=True)
            return {
                "name": name,
                "ok": True,
                "checks": [str(c) for c in checks],
                "warnings": edl.get("provenance", {}).get("warnings", []),
                "clip_warnings": sorted(
                    {w for c in edl.get("clips", []) for w in c.get("warnings", [])}
                ),
            }
        except IngestError as e:
            print(f"  ingest failed (attempt {attempt}): {str(e)[:200]}", flush=True)
            continue
        except PlannerError as e:
            print(f"  planner failed (attempt {attempt}): {e}", flush=True)
            continue

    return {"name": name, "ok": False, "error": "gave up after retries"}


def main() -> None:
    name, seed = sys.argv[1], int(sys.argv[2])
    pool = load_pool()
    result = run_one(name, seed, pool)
    (ROOT / "sessions" / name / "_gap_eval_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
