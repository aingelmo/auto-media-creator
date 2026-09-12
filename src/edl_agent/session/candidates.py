"""Orchestration of Layer 2 (features + candidates) for a session, per #4.2-#4.3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from edl_agent.candidates import build_image_candidate, build_video_candidates
from edl_agent.features import (
    Detector,
    detect_scene_cuts,
    extract_features,
    save_features,
)
from edl_agent.ingest import sha256_file


def run_candidates(
    session_dir: Path,
    manifest: dict,
    slots: dict,
    detector: Detector,
    pose_model_path: str | None = None,
) -> dict:
    """Extract features and build `candidates.json` from the session's proxies.

    Per #4.2-#4.3. For each image source, builds a single image candidate.
    For each video source, extracts per-frame features, saves them, detects
    scene cuts, and builds peak/calm video candidates.

    Args:
        session_dir: Session directory; must contain `manifest.json`'s
            proxies/normalized images.
        manifest: Parsed `manifest.json` (see `ingest.build_manifest`).
        slots: Parsed `slots.json`, with a `slots` key (see
            `slots.build_slots`).
        detector: Pose detector callable, per `features.Detector`.
        pose_model_path: Path to the pose model weights, hashed into
            `pose_model_sha256`; `None` if not applicable.

    Returns:
        The `candidates.json` dict, with `session_id`, `manifest_sha256`,
        `features_config_sha256`, `pose_model_sha256`, and `candidates`
        (list of candidate dicts, see `candidates.build_video_candidates`
        and `candidates.build_image_candidate`). Also written to
        `session_dir / "candidates.json"`.
    """
    session_dir = Path(session_dir)
    peaks_dir = session_dir / "peaks"
    features_dir = session_dir / "features"
    slots_list = slots["slots"]

    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode(),
    ).hexdigest()
    pose_model_sha256 = sha256_file(Path(pose_model_path)) if pose_model_path else ""

    candidates: list[dict] = []
    next_id = 1
    features_config_sha256 = ""

    for src_info in manifest["sources"]:
        src = src_info["src"]
        if src_info["type"] == "image":
            image_path = session_dir / src_info.get("normalized", src)
            candidates.append(
                build_image_candidate(
                    src, f"c{next_id:02d}", slots_list, str(image_path)
                ),
            )
            next_id += 1
            continue

        proxy_path = session_dir / src_info["proxy"]
        feats = extract_features(str(proxy_path), detector)
        features_config_sha256 = feats["features_config_sha256"]
        save_features(feats, features_dir / f"{Path(src).stem}.parquet")
        scene_cuts_s = detect_scene_cuts(str(proxy_path))

        video_cands = build_video_candidates(
            src,
            next_id,
            feats,
            src_info["duration_s"],
            scene_cuts_s,
            slots_list,
            str(proxy_path),
            peaks_dir,
        )
        candidates.extend(video_cands)
        next_id += len(video_cands)

    result = {
        "session_id": manifest["session_id"],
        "manifest_sha256": manifest_sha256,
        "features_config_sha256": features_config_sha256,
        "pose_model_sha256": pose_model_sha256,
        "candidates": candidates,
    }
    with (session_dir / "candidates.json").open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return result
