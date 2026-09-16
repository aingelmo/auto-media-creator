"""Concat + audio, two loudnorm passes (#10.4)."""

from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

from edl_agent.render._common import SFX_FILTER_TEMPLATE, RenderError

if TYPE_CHECKING:
    from pathlib import Path

_LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}")


def _parse_loudnorm_json(stderr: str) -> dict:
    match = _LOUDNORM_JSON_RE.search(stderr)
    if not match:
        msg = f"no loudnorm JSON found in ffmpeg output:\n{stderr}"
        raise RenderError(msg)
    return json.loads(match.group(0))


def _sfx_chain(entry: dict) -> str:
    """ffmpeg audio filter chain for one `audio.sfx[]` entry (#10.4, idea #5).

    `{ramp}` is empty for a plain entry, or a 3-way split/concat that slows
    only the middle piece (the hook's speed ramp, #6.3) so the diegetic
    sound pitch-drops in sync with the video's slow window.
    """
    ramp = entry["ramp"]
    ramp_chain = ""
    if ramp:
        t_a = ramp["start_f"] / 30
        t_b = t_a + ramp["frames"] / 30 * ramp["speed"]
        ramp_chain = (
            f"asplit=3[p0][p1][p2];"
            f"[p0]atrim=0:{t_a}[q0];"
            f"[p1]atrim={t_a}:{t_b},asetrate=48000*{ramp['speed']},aresample=48000[q1];"
            f"[p2]atrim={t_b}[q2];"
            f"[q0][q1][q2]concat=n=3:v=0:a=1,"
        )
    return SFX_FILTER_TEMPLATE.format(
        ramp=ramp_chain, gain_db=entry["gain_db"], delay_ms=entry["delay_ms"]
    )


def concat_and_audio(
    edl: dict, session_dir: Path, threads: int, suffix: str = ""
) -> Path:
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
            `session_dir / f"segments{suffix}"`.
        threads: ffmpeg thread count.
        suffix: Appended to the segment list, segments dir, and output reel
            name, for rendering an A/B variant alongside the default output.

    Returns:
        Path to the rendered reel, `session_dir / f"reel{suffix}.mp4"`.

    Raises:
        RenderError: If the render or measurement ffmpeg invocation fails,
            or its stderr does not contain the expected loudnorm JSON
            block.
    """
    audio = edl["audio"]
    duration_s = edl["target"]["duration_f"] / 30
    segments_txt = session_dir / f"segments{suffix}.txt"
    segments_txt.write_text(
        "".join(
            f"file 'segments{suffix}/seg_{c['slot']:02d}.mp4'\n" for c in edl["clips"]
        ),
    )
    reel_path = session_dir / f"reel{suffix}.mp4"

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

    sfx = audio["sfx"]
    music_chain = (
        f"loudnorm=I={audio['target_lufs']}:TP={audio['target_tp']}:LRA={audio['target_lra']}:linear=true:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:print_format=json,"
        f"aresample=48000,aformat=channel_layouts=stereo"
    )
    # Duck the music under each sfx window so the diegetic sound isn't
    # masked by the (much louder, broadband) music bed.
    for entry in sfx:
        start_s = entry["delay_ms"] / 1000
        end_s = start_s + entry["dur_s"]
        music_chain += f",volume=0.3:enable='between(t,{start_s:.3f},{end_s:.3f})'"
    sfx_inputs = []
    sfx_labels = []
    graph = f"[1:a]{music_chain}[m];"
    for i, entry in enumerate(sfx):
        sfx_inputs += ["-ss", str(entry["in_s"]), "-t", str(entry["dur_s"]), "-i", str(session_dir / entry["src"])]
        label = f"s{i}"
        sfx_labels.append(label)
        graph += f"[{i + 2}:a]{_sfx_chain(entry)}[{label}];"
    mix_inputs = "".join(f"[{label}]" for label in sfx_labels)
    graph += (
        f"[m]{mix_inputs}amix=inputs={len(sfx) + 1}:duration=first:normalize=0,"
        f"afade=t=out:st={duration_s - audio['fade_out_s']}:d={audio['fade_out_s']}[a]"
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
        *sfx_inputs,
        "-filter_complex",
        graph,
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
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
