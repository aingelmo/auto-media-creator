"""Concat + audio, two loudnorm passes (#10.4)."""

from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

from ._common import RenderError

if TYPE_CHECKING:
    from pathlib import Path

_LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}")


def _parse_loudnorm_json(stderr: str) -> dict:
    match = _LOUDNORM_JSON_RE.search(stderr)
    if not match:
        msg = f"no loudnorm JSON found in ffmpeg output:\n{stderr}"
        raise RenderError(msg)
    return json.loads(match.group(0))


def concat_and_audio(edl: dict, session_dir: Path, threads: int) -> Path:
    """Concatenate rendered segments and apply loudnorm in two passes, per #10.4.

    If no music track is set, segments are concatenated stream-copied with
    no audio. Otherwise, ffmpeg's `loudnorm` filter is run once in
    measurement mode and once in linear-correction mode using the measured
    values, per ffmpeg's two-pass loudnorm recipe.

    Args:
        edl: EDL dict, as returned by `edl.build_edl`. Reads `audio`
            (mutated in place: `loudnorm_measured` and `loudnorm_applied`
            are filled in) and `target.duration_f`, `clips` (for segment
            filenames).
        session_dir: Session root directory; segments are expected under
            `session_dir / "segments"`.
        threads: ffmpeg thread count.

    Returns:
        Path to the rendered reel, `session_dir / "reel.mp4"`.

    Raises:
        RenderError: If the render or measurement ffmpeg invocation fails,
            or its stderr does not contain the expected loudnorm JSON
            block.
    """
    audio = edl["audio"]
    duration_s = edl["target"]["duration_f"] / 30
    segments_txt = session_dir / "segments.txt"
    segments_txt.write_text(
        "".join(f"file 'segments/seg_{c['slot']:02d}.mp4'\n" for c in edl["clips"]),
    )
    reel_path = session_dir / "reel.mp4"

    if audio["music_cut_path"] is None:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(segments_txt),
            "-c:v",
            "copy",
            "-an",
            "-movflags",
            "+faststart",
            str(reel_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return reel_path

    music_path = session_dir / audio["music_cut_path"]

    measure_cmd = [
        "ffmpeg",
        "-t",
        str(duration_s),
        "-i",
        str(music_path),
        "-af",
        f"loudnorm=I={audio['target_lufs']}:TP={audio['target_tp']}:LRA={audio['target_lra']}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    measured = _parse_loudnorm_json(
        subprocess.run(measure_cmd, capture_output=True, text=True, check=False).stderr,
    )
    audio["loudnorm_measured"] = measured

    render_af = (
        f"loudnorm=I={audio['target_lufs']}:TP={audio['target_tp']}:LRA={audio['target_lra']}:linear=true:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:print_format=json,"
        f"aresample=48000,aformat=channel_layouts=stereo,"
        f"afade=t=out:st={duration_s - audio['fade_out_s']}:d={audio['fade_out_s']}"
    )
    render_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(segments_txt),
        "-t",
        str(duration_s),
        "-i",
        str(music_path),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "copy",
        "-af",
        render_af,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-threads",
        str(threads),
        "-movflags",
        "+faststart",
        str(reel_path),
    ]
    result = subprocess.run(render_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        msg = f"concat/audio render failed:\n{result.stderr}"
        raise RenderError(msg)
    audio["loudnorm_applied"] = _parse_loudnorm_json(result.stderr)
    return reel_path
