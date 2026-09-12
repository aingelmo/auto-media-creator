"""Layer 2 - Candidates (candidates.json), #4.3.

Consumes the per-source feature series produced by `features.py` (one series
per video source) and produces the `peak`/`calm`/`image` candidates that the
planner and the LLM selector consume.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

FPS = 30
PEAK_MIN_DISTANCE_SAMPLES = 10  # >=1s between peaks at 10fps (#4.3.1)
PEAK_MIN_PROMINENCE = 0.2  # [validate]
SHARPNESS_MIN = 0.35  # [validate]
PEAK_MOTION_BG_MAX = 0.6  # [validate]
PEAK_WINDOW_MAX_S = 6.0
PEAK_WINDOW_SHARPNESS_TOLERANCE = 3
# frames of low sharpness tolerated without cutting the window (motion blur
# transient from the explosive movement that produces the peak itself); raise
# if it still cuts windows close to real peaks

CALM_MIN_DURATION_S = 2.0
CALM_KP_SPEED_MAX = 0.25
CALM_MOTION_BG_MAX = 0.25  # [validate]
CALM_SHARPNESS_MIN = 0.5
CALM_CENTER_X_TOL = 0.2
CALM_CENTER_Y_TOL = 0.25
CALM_MAX_PER_CLIP = 2

PEAK_FRAME_OFFSETS_S = (-0.3, 0.0, 0.3)
PEAK_FRAME_SIDE_PX = 512


def edge_margin_s(clip_duration_s: float) -> float:
    """Compute the edge-exclusion margin for a clip, per #4.3.2.

    Args:
        clip_duration_s: Total duration of the source clip, in seconds.

    Returns:
        0.5 seconds if the clip is at least 5 seconds long, otherwise 0.25
        seconds. Peaks and scene cuts closer than this margin to a clip edge
        are discarded, since there is not enough footage on one side to build
        a usable window.
    """
    return 0.5 if clip_duration_s >= 5.0 else 0.25


def find_peak_windows(
    features: dict, clip_duration_s: float, scene_cuts_s: list[float]
) -> list[dict]:
    """Find `peak` candidate windows: local maxima of `kp_speed`, per #4.3.

    Detects local maxima in the `kp_speed` series, discards peaks that fail
    quality gates or fall too close to a clip edge or scene cut, then grows a
    window around each surviving peak.

    Args:
        features: Feature series for one clip, as returned by
            `features.extract_features`. Keys used here:
            - `t_s` (list[float]): sample timestamps in seconds.
            - `kp_speed` (list[float]): normalized action-keypoint speed
              per sample, in [0, 1].
            - `sharpness` (list[float]): normalized Laplacian-variance
              sharpness per sample, in [0, 1].
            - `subject_visible` (list[bool]): whether the principal subject
              was tracked in that sample.
            - `motion_bg` (list[float]): normalized background motion
              (outside subject bboxes) per sample, in [0, 1].
        clip_duration_s: Total duration of the source clip, in seconds.
        scene_cuts_s: Timestamps (seconds) of scene cuts detected in the
            clip.

    Returns:
        List of peak-window dicts, one per surviving local maximum, each
        with keys:
        - `kind` (str): always `"peak"`.
        - `t_peak` (float): timestamp of the peak, in seconds.
        - `window` (list[float]): `[start_s, end_s]` bounds the peak may be
          trimmed to.
        - `index` (int): sample index of the peak within `features["t_s"]`.
    """
    kp_speed = np.asarray(features["kp_speed"])
    t_s = features["t_s"]
    sharpness = features["sharpness"]
    subject_visible = features["subject_visible"]
    motion_bg = features["motion_bg"]

    idxs, _ = find_peaks(
        kp_speed, distance=PEAK_MIN_DISTANCE_SAMPLES, prominence=PEAK_MIN_PROMINENCE
    )
    margin = edge_margin_s(clip_duration_s)

    out = []
    for i in idxs:
        t_peak = t_s[i]
        if (
            sharpness[i] < SHARPNESS_MIN
            or not subject_visible[i]
            or motion_bg[i] > PEAK_MOTION_BG_MAX
        ):
            continue
        if t_peak < margin or (clip_duration_s - t_peak) < margin:
            continue
        if any(abs(t_peak - c) < margin for c in scene_cuts_s):
            continue
        window = _peak_window(features, int(i), scene_cuts_s)
        out.append(
            {"kind": "peak", "t_peak": t_peak, "window": window, "index": int(i)}
        )
    return out


def _crosses_cut(t_a: float, t_b: float, scene_cuts_s: list[float]) -> bool:
    lo, hi = min(t_a, t_b), max(t_a, t_b)
    return any(lo < c <= hi for c in scene_cuts_s)


def _peak_window(features: dict, i: int, scene_cuts_s: list[float]) -> list[float]:
    """Grow a candidate window outward from a peak sample, in both directions.

    A scene cut or loss of subject tracking is a hard boundary and stops the
    window immediately; a short run of low sharpness (motion blur from the
    explosive movement that produced the peak itself) is tolerated without
    stopping the window, but the window boundary never advances past the
    last sharp frame.

    Args:
        features: Feature series for one clip (see `find_peak_windows` for
            the keys used).
        i: Sample index of the peak within `features["t_s"]`.
        scene_cuts_s: Timestamps (seconds) of scene cuts detected in the
            clip.

    Returns:
        `[start_s, end_s]`: the grown window bounds, in seconds.
    """
    t_s = features["t_s"]
    sharpness = features["sharpness"]
    subject_visible = features["subject_visible"]
    t_peak = t_s[i]

    def hard_ok(j: int) -> bool:
        return subject_visible[j] and not _crosses_cut(t_peak, t_s[j], scene_cuts_s)

    def extend(step: int) -> int:
        boundary = i
        j = i
        low_sharpness_streak = 0
        while True:
            nxt = j + step
            if not (0 <= nxt < len(t_s)) or abs(t_s[nxt] - t_peak) > PEAK_WINDOW_MAX_S:
                break
            if not hard_ok(nxt):
                break
            j = nxt
            if sharpness[j] >= SHARPNESS_MIN:
                low_sharpness_streak = 0
                boundary = j
            else:
                low_sharpness_streak += 1
                if low_sharpness_streak > PEAK_WINDOW_SHARPNESS_TOLERANCE:
                    break
        return boundary

    lo = extend(-1)
    hi = extend(1)
    return [t_s[lo], t_s[hi]]


def _is_centered(bbox: tuple | None) -> bool:
    if bbox is None:
        return False
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return abs(cx - 0.5) <= CALM_CENTER_X_TOL and abs(cy - 0.5) <= CALM_CENTER_Y_TOL


def find_calm_windows(features: dict) -> list[dict]:
    """Find `calm` candidate windows: stable runs, per #4.3.

    A sample is "calm" when action, background motion, sharpness, subject
    visibility, and subject centering are all within thresholds
    simultaneously. Consecutive calm samples form a run; only the
    `CALM_MAX_PER_CLIP` longest runs (at least `CALM_MIN_DURATION_S` long)
    are kept per clip.

    Args:
        features: Feature series for one clip, as returned by
            `features.extract_features`. Keys used here: `t_s`, `kp_speed`,
            `motion_bg`, `sharpness`, `subject_visible`, `subject_bbox`
            (see `find_peak_windows` and `features.extract_features` for
            their shapes).

    Returns:
        List of calm-window dicts, each with keys:
        - `kind` (str): always `"calm"`.
        - `t_peak` (float): timestamp of the run's midpoint sample, in
          seconds (kept as `t_peak` for shape parity with peak candidates).
        - `window` (list[float]): `[start_s, end_s]` of the run.
    """
    n = len(features["t_s"])
    t_s = features["t_s"]
    runs: list[tuple[int, int]] = []
    start = None
    for i in range(n):
        is_calm = (
            features["kp_speed"][i] <= CALM_KP_SPEED_MAX
            and features["motion_bg"][i] <= CALM_MOTION_BG_MAX
            and features["sharpness"][i] >= CALM_SHARPNESS_MIN
            and features["subject_visible"][i]
            and _is_centered(features["subject_bbox"][i])
        )
        if is_calm and start is None:
            start = i
        elif not is_calm and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, n - 1))

    runs = [(a, b) for a, b in runs if t_s[b] - t_s[a] >= CALM_MIN_DURATION_S]
    runs.sort(key=lambda ab: t_s[ab[1]] - t_s[ab[0]], reverse=True)
    runs = runs[:CALM_MAX_PER_CLIP]

    out = []
    for a, b in runs:
        center_i = (a + b) // 2
        out.append(
            {"kind": "calm", "t_peak": t_s[center_i], "window": [t_s[a], t_s[b]]}
        )
    return out


def admits_slots(
    window: tuple[float, float], slots: list[dict], speed: float = 1.0, fps: int = FPS
) -> list[int]:
    """List the slots a candidate window can fill, per #4.3 `admits_slots`.

    Uses the same admission calculation as #6.1. Precomputed here so that
    candidates that fit no slot at all are never sent to the LLM selector.

    Args:
        window: `(start_s, end_s)` bounds of the candidate.
        slots: Slot definitions, as in `slots.json["slots"]`. Each dict
            needs at least `slot` (int, slot index) and `start_f`/`end_f`
            (int, timeline frame bounds).
        speed: Playback speed multiplier to be applied to this candidate
            (e.g. 0.5 for slow motion). Defaults to 1.0.
        fps: Target frame rate. Defaults to `FPS` (30).

    Returns:
        List of `slot` indices (from `slots`) whose duration fits within
        `window` at the given `speed`.
    """
    out = []
    for s in slots:
        d_f = s["end_f"] - s["start_f"]
        need_s = d_f / fps * speed
        if (window[1] - window[0]) >= need_s + 2 / fps:
            out.append(s["slot"])
    return out


def score_cv(kp_speed: float, sharpness: float, bbox: tuple | None, kind: str) -> float:
    """Compute the computer-vision-only quality score `score_cv`, per #4.3.

    Used by the rules fallback (#8.6) and by the planner's relaxation path
    when no LLM selection is available for a role.

    Args:
        kp_speed: Normalized action-keypoint speed at the candidate's peak
            (or representative sample), in [0, 1].
        sharpness: Normalized sharpness at the candidate's peak (or
            representative sample), in [0, 1].
        bbox: Subject bounding box `(x0, y0, x1, y1)`, normalized to [0, 1],
            or `None` if no subject was tracked (treated as centered).
        kind: Candidate kind, one of `"peak"`, `"calm"`, `"image"`. Action is
            rewarded for `"peak"` and penalized for `"calm"` (a calm shot
            scores higher the less action it has).

    Returns:
        Weighted score combining action term (0.5), sharpness (0.3), and
        subject centrality (0.2). Not bounded to a fixed range but
        comparable across candidates of the same run.
    """
    cx = (bbox[0] + bbox[2]) / 2 if bbox else 0.5
    centrality = 1 - 2 * abs(cx - 0.5)
    action_term = 0.5 * (1 - kp_speed) if kind == "calm" else 0.5 * kp_speed
    return action_term + 0.3 * sharpness + 0.2 * centrality


def extract_peak_frames(
    proxy_path: str,
    t_peak: float,
    window: tuple[float, float],
    out_dir: Path,
    cand_id: str,
) -> tuple[list[str], list[str]]:
    """Extract the `peak_frames` JPEGs for a candidate, per #4.3.

    Extracts 3 frames at `t_peak + PEAK_FRAME_OFFSETS_S` (before/at/after the
    peak), each timestamp clamped to `window`, via ffmpeg.

    Args:
        proxy_path: Path to the proxy video to extract frames from.
        t_peak: Timestamp of the candidate's peak, in seconds.
        window: `(start_s, end_s)` bounds to clamp extraction timestamps to.
        out_dir: Directory to write the JPEGs to (created if missing).
        cand_id: Candidate id (e.g. `"c01"`), used as the output filename
            prefix.

    Returns:
        `(paths, hashes)`: parallel lists of output file paths (as `str`)
        and their SHA-256 hex digests, in the same order as
        `PEAK_FRAME_OFFSETS_S`.

    Raises:
        subprocess.CalledProcessError: If any ffmpeg invocation fails.
    """
    from .ingest import sha256_file

    out_dir.mkdir(parents=True, exist_ok=True)
    scale = (
        f"scale='if(gt(iw,ih),{PEAK_FRAME_SIDE_PX},-2)':"
        f"'if(gt(iw,ih),-2,{PEAK_FRAME_SIDE_PX})'"
    )
    paths, hashes = [], []
    for i, off in enumerate(PEAK_FRAME_OFFSETS_S):
        t = min(max(t_peak + off, window[0]), window[1])
        out_path = out_dir / f"{cand_id}_{i}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(max(t, 0.0)),
            "-i",
            str(proxy_path),
            "-frames:v",
            "1",
            "-vf",
            scale,
            "-q:v",
            "4",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        paths.append(str(out_path))
        hashes.append(sha256_file(out_path))
    return paths, hashes


def build_contact_sheet(peak_frame_paths: list[str], out_path: Path) -> Path:
    """Build a horizontal contact sheet from a candidate's peak frames.

    For human inspection only (#4.3); not consumed by the LLM selector or
    the planner.

    Args:
        peak_frame_paths: Paths to the JPEG frames to lay out side by side,
            in order.
        out_path: Path to write the JPEG contact sheet to (parent directory
            created if missing).

    Returns:
        `out_path`, unchanged, for convenient chaining.
    """
    from PIL import Image

    images = [Image.open(p) for p in peak_frame_paths]
    h = max(im.height for im in images)
    resized = [im.resize((round(im.width * h / im.height), h)) for im in images]
    sheet = Image.new("RGB", (sum(im.width for im in resized), h))
    x = 0
    for im in resized:
        sheet.paste(im, (x, 0))
        x += im.width
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "JPEG", quality=85)
    return out_path


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
            `features.extract_features` (see `find_peak_windows` for the
            keys read here; also uses `subject_bbox` and `multi_subject`).
        clip_duration_s: Total duration of the source clip, in seconds.
        scene_cuts_s: Timestamps (seconds) of scene cuts detected in the
            clip.
        slots: Slot definitions, as in `slots.json["slots"]` (see
            `admits_slots`).
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
        - `motion_bg` (float): normalized background motion at `t_peak`.
        - `sharpness` (float): normalized sharpness at `t_peak`.
        - `subject_bbox` (list[float]): `[x0, y0, x1, y1]`, normalized;
          defaults to the full frame if no subject was tracked.
        - `multi_subject` (bool): whether >=2 large detections coexist at
          that sample.
        - `score_cv` (float): see `score_cv`.
        - `admits_slots` (list[int]): see `admits_slots`.
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

    from .ingest import sha256_file

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
