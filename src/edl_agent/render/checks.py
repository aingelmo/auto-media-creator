"""R1-R6 checks (#10.5): validate rendered segments and the final reel."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image


@dataclass
class CheckResult:
    """Result of one R1-R6 check (#9)."""

    name: str
    ok: bool
    detail: str = ""


def _nb_read_frames(path: Path) -> int:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-print_format",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def check_r1_frame_count(segment_path: Path, n_frames: int) -> CheckResult:
    """Check R1: the rendered segment has exactly `n_frames` frames, per #9.

    Args:
        segment_path: Path to the rendered segment.
        n_frames: Expected frame count.

    Returns:
        `CheckResult` named `"R1"`, `ok=True` if the actual frame count
        (via ffprobe's `-count_frames`) matches `n_frames`.
    """
    actual = _nb_read_frames(segment_path)
    ok = actual == n_frames
    return CheckResult(
        "R1", ok, f"{segment_path.name}: expected {n_frames}, got {actual}"
    )


def _phash_frame(path: Path, frame_index: int, tmp_dir: Path) -> imagehash.ImageHash:
    out_png = tmp_dir / f"{path.stem}_{frame_index}.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-vf",
            f"select='eq(n\\,{frame_index})',scale=256:-2",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            "1",
            str(out_png),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with Image.open(out_png) as im:
        return imagehash.phash(im)


def check_r2_phash(
    final_seg: Path, preview_seg: Path, n_frames: int, threshold: int = 8
) -> CheckResult:
    """Check R2: final vs preview pHash, frame by frame, below `threshold`, per #9.

    Compares perceptual hashes at the first, middle, and last frame of each
    segment, to catch a final render that diverges visually from the
    preview the operator already reviewed.

    Args:
        final_seg: Path to the final-resolution rendered segment.
        preview_seg: Path to the preview-resolution rendered segment.
        n_frames: Segment frame count, used to pick the middle/last frame
            indices.
        threshold: Maximum allowed Hamming distance between the two
            pHashes at any compared frame. Defaults to 8.

    Returns:
        `CheckResult` named `"R2"`, `ok=False` at the first frame whose
        Hamming distance exceeds `threshold` (with the frame index and
        distance in `detail`), `ok=True` otherwise.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        indices = sorted({0, n_frames // 2, n_frames - 1})
        for idx in indices:
            d = _phash_frame(final_seg, idx, tmp_path) - _phash_frame(
                preview_seg, idx, tmp_path
            )
            if d > threshold:
                return CheckResult(
                    "R2",
                    False,
                    f"{final_seg.name} frame {idx}: hamming {d} > {threshold}",
                )
    return CheckResult("R2", True)


def check_r3_reel_duration(reel_path: Path, duration_f: int) -> CheckResult:
    """Check R3: the concatenated reel lasts exactly `duration_f` frames, per #9.

    Args:
        reel_path: Path to the final concatenated reel.
        duration_f: Expected duration, in frames (at 30fps).

    Returns:
        `CheckResult` named `"R3"`, `ok=False` if the reel's frame count
        (via ffprobe's `-count_frames`) doesn't match `duration_f`, or if
        either its video or audio stream duration falls outside
        `duration_f / 30 +- 1/30` seconds; `ok=True` otherwise.
    """
    actual_frames = _nb_read_frames(reel_path)
    if actual_frames != duration_f:
        return CheckResult(
            "R3", False, f"reel frames: expected {duration_f}, got {actual_frames}"
        )

    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(reel_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    duration_s = duration_f / 30
    streams = {s["codec_type"]: s for s in probe["streams"]}
    for kind in ("video", "audio"):
        stream = streams.get(kind)
        if stream is None:
            continue
        actual_s = float(stream.get("duration") or probe["format"]["duration"])
        if not (duration_s - 1 / 30 <= actual_s <= duration_s + 1 / 30):
            return CheckResult(
                "R3",
                False,
                f"{kind} duration {actual_s} outside "
                f"[{duration_s - 1 / 30}, {duration_s + 1 / 30}]",
            )
    return CheckResult("R3", True)


def check_r4_color(path: Path) -> CheckResult:
    """Check R4: the video stream uses the expected bt709 color space, per #9.

    Args:
        path: Path to the media file to check (a segment or the final
            reel).

    Returns:
        `CheckResult` named `"R4"`, `ok=True` if `color_primaries`,
        `color_transfer`, `color_space` are all `"bt709"` and `color_range`
        is `"tv"`; `detail` always reports the actual values.
    """
    stream = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-select_streams",
                "v:0",
                "-show_streams",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )["streams"][0]
    ok = (
        stream.get("color_primaries") == "bt709"
        and stream.get("color_transfer") == "bt709"
        and stream.get("color_space") == "bt709"
        and stream.get("color_range") == "tv"
    )
    return CheckResult(
        "R4",
        ok,
        str(
            {
                k: stream.get(k)
                for k in (
                    "color_primaries",
                    "color_transfer",
                    "color_space",
                    "color_range",
                )
            }
        ),
    )


def check_r5_loudnorm_linear(audio: dict, allow_dynamic: bool = False) -> CheckResult:
    """Check R5: loudnorm ran in linear mode, unless `allow_dynamic` permits it, per #9.

    Args:
        audio: EDL `audio` block, as built by `edl._audio_block` and
            populated by `concat.concat_and_audio`. Reads `loudnorm_applied`
            (dict with `normalization_type`, or `None` if there was no
            music track).
        allow_dynamic: If `True`, a `"dynamic"` normalization type still
            passes the check (with a warning-level detail). Defaults to
            `False`.

    Returns:
        `CheckResult` named `"R5"`. `ok=True` if there was no music track,
        or `normalization_type == "linear"`, or (`allow_dynamic` and it
        wasn't linear).
    """
    applied = audio.get("loudnorm_applied")
    if applied is None:
        return CheckResult("R5", True, "no music track")
    normalization_type = applied.get("normalization_type")
    if normalization_type == "linear":
        return CheckResult("R5", True)
    return CheckResult("R5", allow_dynamic, f"normalization_type={normalization_type}")


def check_r6_monotonic_dts(reel_path: Path) -> CheckResult:
    """Check R6: the final reel's DTS values are monotonically increasing, per #9.

    Args:
        reel_path: Path to the final concatenated reel.

    Returns:
        `CheckResult` named `"R6"`, `ok=False` at the first packet whose
        DTS is not strictly greater than the previous one (with the packet
        index and both values in `detail`); `ok=True` otherwise.
    """
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=dts,pts",
            "-print_format",
            "json",
            str(reel_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    packets = json.loads(out)["packets"]
    prev_dts = None
    for i, p in enumerate(packets):
        dts = int(p["dts"])
        if prev_dts is not None and dts <= prev_dts:
            return CheckResult(
                "R6", False, f"non-monotonic DTS at packet {i}: {dts} <= {prev_dts}"
            )
        prev_dts = dts
    return CheckResult("R6", True)


def run_render_checks(
    edl: dict,
    session_dir: Path,
    allow_dynamic_loudnorm: bool = False,
    run_r2: bool = True,
    suffix: str = "",
    preview_suffix: str | None = None,
) -> list[CheckResult]:
    """Run checks R1-R6 over already-rendered segments, per #9.

    Args:
        edl: EDL dict, as returned by `edl.build_edl`. Reads `clips` and
            `target.duration_f`, and `audio` (for R5).
        session_dir: Session root directory; final segments are expected
            under `session_dir / f"segments{suffix}"`, preview segments
            under `session_dir / f"preview_segments{preview_suffix}"`, and
            the reel at `session_dir / f"reel{suffix}.mp4"`.
        allow_dynamic_loudnorm: Passed through to `check_r5_loudnorm_linear`.
        run_r2: If `False`, skips the R2 pHash comparison (e.g. when no
            preview segments were rendered). Defaults to `True`.
        suffix: Appended to the segments/reel names, for checking an A/B
            variant alongside the default output.
        preview_suffix: Appended to the preview_segments dir name; defaults
            to `suffix` when `None` (e.g. the hook_flash/punch_in combo
            suffix, which may differ from `suffix` since final segments are
            unsuffixed).

    Returns:
        Flat list of `CheckResult`s: R1 (and R2, R4) per clip, then R3, R4,
        R5, R6 for the reel as a whole.
    """
    if preview_suffix is None:
        preview_suffix = suffix
    results: list[CheckResult] = []
    for clip in edl["clips"]:
        final_seg = session_dir / f"segments{suffix}" / f"seg_{clip['slot']:02d}.mp4"
        results.append(check_r1_frame_count(final_seg, clip["n_frames"]))
        if run_r2:
            preview_seg = (
                session_dir
                / f"preview_segments{preview_suffix}"
                / f"seg_{clip['slot']:02d}.mp4"
            )
            results.append(check_r2_phash(final_seg, preview_seg, clip["n_frames"]))
        results.append(check_r4_color(final_seg))

    reel_path = session_dir / f"reel{suffix}.mp4"
    results.append(check_r3_reel_duration(reel_path, edl["target"]["duration_f"]))
    results.append(check_r4_color(reel_path))
    results.append(
        check_r5_loudnorm_linear(edl["audio"], allow_dynamic=allow_dynamic_loudnorm)
    )
    results.append(check_r6_monotonic_dts(reel_path))
    return results
