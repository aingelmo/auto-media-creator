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
    load_features,
    save_features,
)
from edl_agent.features import features_config_sha256 as compute_features_config_sha256
from edl_agent.ingest import atomic_write_text, link_into, sha256_file, tmp_path


def run_candidates(
    session_dir: Path,
    manifest: dict,
    slots: dict,
    detector: Detector,
    pose_model_path: str | None = None,
    cache_root: Path | None = None,
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
        cache_root: If given, a content-addressed cache directory (keyed
            by source sha256) reused across sessions for `extract_features`
            + `detect_scene_cuts`; `features/<stem>.parquet` becomes a
            symlink into it. `None` disables caching.

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
    cur_features_config_sha256 = compute_features_config_sha256()

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
        feat_path = features_dir / f"{Path(src).stem}.parquet"
        cache_entry = cache_root / src_info["sha256"] if cache_root else None
        feat_name = (
            f"features.{cur_features_config_sha256[:12]}.{pose_model_sha256[:12]}.parquet"
        )
        cached_feat_path = cache_entry / feat_name if cache_entry else None
        cached_cuts_path = cache_entry / "scene_cuts.json" if cache_entry else None

        if (
            cached_feat_path
            and cached_cuts_path
            and cached_feat_path.exists()
            and cached_cuts_path.exists()
        ):
            feats = load_features(cached_feat_path)
            feats["features_config_sha256"] = cur_features_config_sha256
            link_into(feat_path, cached_feat_path)
            scene_cuts_s = json.loads(cached_cuts_path.read_text())
        else:
            feats = extract_features(str(proxy_path), detector)
            scene_cuts_s = detect_scene_cuts(str(proxy_path))
            if cached_feat_path and cached_cuts_path:
                tmp_feat_path = tmp_path(cached_feat_path)
                save_features(feats, tmp_feat_path)
                tmp_feat_path.replace(cached_feat_path)
                atomic_write_text(cached_cuts_path, json.dumps(scene_cuts_s))
                link_into(feat_path, cached_feat_path)
            else:
                save_features(feats, feat_path)

        features_config_sha256 = feats["features_config_sha256"]

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
