"""Assemble full candidate entries (video + image), per #4.3."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edl_agent.candidates.calm import find_calm_windows
from edl_agent.candidates.frames import build_contact_sheet, extract_peak_frames
from edl_agent.candidates.peaks import find_peak_windows
from edl_agent.candidates.scoring import admits_slots, score_cv

if TYPE_CHECKING:
    from pathlib import Path


def build_video_candidates(
    src: str,
    id_start: int,
    features: dict,
    clip_duration_s: float,
    scene_cuts_s: list[float],
    slots: list[dict],
    proxy_path: str,
    peaks_dir: Path,
    speed: float = 1.0,
) -> list[dict]:
    """Assemble the `peak`+`calm` candidates for one video source, per #4.3.

    Finds peak and calm windows, then for each one extracts peak frames, a
    contact sheet, and computes the derived scoring/admission fields that
    make up a full candidate entry. Ids are global `c{NN}` strings starting
    at `id_start`.

    Args:
        src: Source path (relative to the session dir), used as the
            candidate's `src` field.
        id_start: First numeric id to assign (candidates are numbered
            `id_start`, `id_start + 1`, ... as `c{NN}`).
        features: Feature series for this clip, as returned by
            `features.extract_features` (see `peaks.find_peak_windows` for
            the keys read here; also uses `subject_bbox` and
            `multi_subject`).
        clip_duration_s: Total duration of the source clip, in seconds.
        scene_cuts_s: Timestamps (seconds) of scene cuts detected in the
            clip.
        slots: Slot definitions, as in `slots.json["slots"]` (see
            `scoring.admits_slots`).
        proxy_path: Path to the proxy video to extract peak frames from.
        peaks_dir: Directory to write peak-frame JPEGs and contact sheets
            to.
        speed: Playback speed multiplier for slot-admission purposes.
            Defaults to 1.0.

    Returns:
        List of candidate dicts (as stored in `candidates.json`), each with
        keys:
        - `id` (str): candidate id, e.g. `"c01"`.
        - `src` (str): source path.
        - `kind` (str): `"peak"` or `"calm"`.
        - `t_peak` (float): peak/representative timestamp, in seconds.
        - `window` (list[float]): `[start_s, end_s]` bounds.
        - `kp_speed` (float): normalized action speed at `t_peak`.
        - `kp_speed_abs` (float): un-normalized action speed at `t_peak`, in
          bbox-heights per second (see `features.extract_features`); 0.0 if
          the feature file predates the column.
        - `motion_bg` (float): normalized background motion at `t_peak`.
        - `sharpness` (float): normalized sharpness at `t_peak`.
        - `subject_bbox` (list[float]): `[x0, y0, x1, y1]`, normalized;
          defaults to the full frame if no subject was tracked.
        - `multi_subject` (bool): whether >=2 large detections coexist at
          that sample.
        - `score_cv` (float): see `scoring.score_cv`.
        - `admits_slots` (list[int]): see `scoring.admits_slots`.
        - `peak_frames` (list[str]): paths to the 3 extracted JPEGs.
        - `peak_frames_sha256` (list[str]): their SHA-256 hex digests.
    """
    windows = find_peak_windows(
        features, clip_duration_s, scene_cuts_s
    ) + find_calm_windows(features)
    out = []
    for n, w in enumerate(windows):
        cand_id = f"c{id_start + n:02d}"
        i = w.get("index")
        bbox = (
            features["subject_bbox"][i]
            if i is not None
            else _bbox_at(features, w["t_peak"])
        )
        kp_speed = (
            features["kp_speed"][i]
            if i is not None
            else _value_at(features, "kp_speed", w["t_peak"])
        )
        kp_speed_abs = (
            features.get("kp_speed_abs", [0.0] * len(features["t_s"]))[
                i if i is not None else _nearest_index(features, w["t_peak"])
            ]
        )
        sharpness = (
            features["sharpness"][i]
            if i is not None
            else _value_at(features, "sharpness", w["t_peak"])
        )
        motion_bg = (
            features["motion_bg"][i]
            if i is not None
            else _value_at(features, "motion_bg", w["t_peak"])
        )
        multi_subject = features["multi_subject"][i] if i is not None else False

        peak_frames, peak_frames_sha256 = extract_peak_frames(
            proxy_path,
            w["t_peak"],
            tuple(w["window"]),
            peaks_dir,
            cand_id,
        )
        build_contact_sheet(peak_frames, peaks_dir / f"{cand_id}_contact.jpg")

        out.append(
            {
                "id": cand_id,
                "src": src,
                "kind": w["kind"],
                "t_peak": w["t_peak"],
                "window": w["window"],
                "kp_speed": kp_speed,
                "kp_speed_abs": round(float(kp_speed_abs), 3),
                "motion_bg": motion_bg,
                "sharpness": sharpness,
                "subject_bbox": list(bbox) if bbox else [0.0, 0.0, 1.0, 1.0],
                "multi_subject": bool(multi_subject),
                "score_cv": score_cv(kp_speed, sharpness, bbox, w["kind"]),
                "admits_slots": admits_slots(tuple(w["window"]), slots, speed),
                "peak_frames": peak_frames,
                "peak_frames_sha256": peak_frames_sha256,
            }
        )
    return out


def _nearest_index(features: dict, t: float) -> int:
    t_s = features["t_s"]
    return min(range(len(t_s)), key=lambda i: abs(t_s[i] - t))


def _bbox_at(features: dict, t: float) -> tuple | None:
    return features["subject_bbox"][_nearest_index(features, t)]


def _value_at(features: dict, key: str, t: float) -> float:
    return features[key][_nearest_index(features, t)]


def build_image_candidate(
    src: str, cand_id: str, slots: list[dict], peak_frame: str
) -> dict:
    """Build an `image` candidate, per #4.3.

    Image candidates have no time axis: `t_peak` is 0, the window is
    effectively unbounded (`[0, 1e9]`), and the candidate is admitted in
    every slot.

    Args:
        src: Source path (relative to the session dir).
        cand_id: Candidate id to assign, e.g. `"c07"`.
        slots: Slot definitions, as in `slots.json["slots"]`; only their
            `slot` index is used, since an image candidate admits all of
            them.
        peak_frame: Path to the normalized image to use as the candidate's
            single "peak frame" (shown to the LLM selector).

    Returns:
        Candidate dict with the same shape as those from
        `build_video_candidates`, except `kind="image"`, `t_peak=0.0`,
        `window=[0.0, 1e9]`, a fixed centered `subject_bbox`, and a single
        entry in `peak_frames`/`peak_frames_sha256`. If `peak_frame` does
        not exist on disk, `peak_frames_sha256` falls back to the SHA-256 of
        an empty byte string rather than raising.
    """
    import hashlib
    from pathlib import Path

    from edl_agent.ingest import sha256_file

    return {
        "id": cand_id,
        "src": src,
        "kind": "image",
        "t_peak": 0.0,
        "window": [0.0, 1e9],
        "kp_speed": 0.0,
        "motion_bg": 0.0,
        "sharpness": 0.85,
        "subject_bbox": [0.25, 0.10, 0.75, 0.90],
        "multi_subject": False,
        "score_cv": score_cv(0.0, 0.85, (0.25, 0.10, 0.75, 0.90), "image"),
        "admits_slots": [s["slot"] for s in slots],
        "peak_frames": [peak_frame],
        "peak_frames_sha256": [sha256_file(Path(peak_frame))]
        if Path(peak_frame).exists()
        else [hashlib.sha256(b"").hexdigest()],
    }


def readmit_candidates(
    candidates: list[dict], slots: list[dict], speed: float = 1.0
) -> None:
    """Recompute `admits_slots` for candidates against a new slot list, in place.

    Cheap alternative to rebuilding candidates from scratch when only the
    slot layout changed (e.g. music re-cut to a shorter duration):
    peak/calm windows don't depend on `slots`, only `admits_slots` does.

    Args:
        candidates: Candidate dicts (as in `candidates.json["candidates"]`),
            mutated in place.
        slots: New slot definitions, as in `slots.json["slots"]`.
        speed: Playback speed multiplier, as in `build_video_candidates`.
    """
    for c in candidates:
        if c["kind"] == "image":
            c["admits_slots"] = [s["slot"] for s in slots]
        else:
            c["admits_slots"] = admits_slots(tuple(c["window"]), slots, speed)
