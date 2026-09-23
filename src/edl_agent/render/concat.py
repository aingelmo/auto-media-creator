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


def _outro_s(edl: dict) -> float:
    """Outro tail length in seconds (#6.8, #10.4).

    The C0 brand sign-off is burned into the close clip's tail, so the
    music must already be silent when it appears. Reads the last
    clip's `effect_params["outro_frames"]` (frames at 30 fps); legacy
    `effect == "end_card"` EDLs report the whole synthetic card.

    Args:
        edl: EDL dict, as returned by `edl.build_edl`. Reads
            `clips[-1]["effect_params"]["outro_frames"]` (int) or
            `clips[-1]["effect"]`/`n_frames` for the legacy card.

    Returns:
        Outro duration in seconds, or `0.0` when the reel has no
        brand sign-off.
    """
    clips = edl.get("clips") or []
    if not clips:
        return 0.0
    last = clips[-1]
    params = last.get("effect_params") or {}
    if params.get("outro_frames"):
        return float(params["outro_frames"]) / 30
    if last.get("effect") == "end_card":
        return float(last.get("n_frames", 0)) / 30
    return 0.0


def _fade_window(
    duration_s: float, fade_out_s: float, outro_s: float
) -> tuple[float, float]:
    """`(st, d)` for the closing `afade=t=out` (#10.4).

    The fade completes exactly when the outro starts (`duration_s -
    outro_s`), so the brand image appears over silence; without an
    outro it completes at the reel end, as before. Clamped so short
    reels never produce a negative start.

    Args:
        duration_s: Total reel duration in seconds
            (`target.duration_f / 30`).
        fade_out_s: Configured fade length in seconds
            (`audio.fade_out_s`).
        outro_s: Outro tail in seconds (see `_outro_s`).

    Returns:
        `(st, d)` seconds for `afade=t=out:st={st}:d={d}`; `d == 0.0`
        when there is nothing to fade (`fade_out_s <= 0` or the fade
        end is at 0).
    """
    if fade_out_s <= 0:
        return duration_s, 0.0
    fade_end = duration_s - outro_s if outro_s > 0 else duration_s
    fade_end = max(0.0, min(fade_end, duration_s))
    start = max(0.0, fade_end - fade_out_s)
    return start, fade_end - start


def _sfx_chain(entry: dict) -> str:
    """Build ffmpeg audio filter chain for one `audio.sfx[]` entry (#10.4, #5).

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
    edl: dict, session_dir: Path, threads: int, suffix: str = "", preview: bool = False
) -> Path:
    """Concatenate rendered segments and apply loudnorm in two passes, per #10.4.

    If no music track is set, segments are concatenated stream-copied with
    no audio. Otherwise, ffmpeg's `loudnorm` filter is run once in
    measurement mode and once in linear-correction mode using the measured
    values, per ffmpeg's two-pass loudnorm recipe. The closing `afade`
    completes when the C0 outro starts (#6.8), so the brand image
    appears over silence; without an outro it completes at the reel end.

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
        preview: If `True`, reads from `preview_segments{suffix}` (per
            `render_preview_segments`) and writes `reel_preview{suffix}.mp4`
            instead of the final-resolution `segments{suffix}`/`reel{suffix}.mp4`.

    Returns:
        Path to the rendered reel: `session_dir / "reel_preview{suffix}.mp4"`
        if `preview`, else `session_dir / "reel{suffix}.mp4"`.

    Raises:
        RenderError: If the render or measurement ffmpeg invocation fails,
            or its stderr does not contain the expected loudnorm JSON
            block.
    """
    segments_dir = f"{'preview_segments' if preview else 'segments'}{suffix}"
    reel_name = f"{'reel_preview' if preview else 'reel'}{suffix}"
    audio = edl["audio"]
    duration_s = edl["target"]["duration_f"] / 30
    segments_txt = session_dir / f"{segments_dir}.txt"
    segments_txt.write_text(
        "".join(
            f"file '{segments_dir}/seg_{c['slot']:02d}.mp4'\n" for c in edl["clips"]
        ),
    )
    reel_path = session_dir / f"{reel_name}.mp4"

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
    sfx_inputs = []
    sfx_labels = []
    graph = f"[1:a]{music_chain}[m];"
    for i, entry in enumerate(sfx):
        sfx_inputs += [
            "-ss",
            str(entry["in_s"]),
            "-t",
            str(entry["dur_s"]),
            "-i",
            str(session_dir / entry["src"]),
        ]
        label = f"s{i}"
        sfx_labels.append(label)
        graph += f"[{i + 2}:a]{_sfx_chain(entry)}[{label}];"
    mix_inputs = "".join(f"[{label}]" for label in sfx_labels)
    fade_st, fade_d = _fade_window(
        duration_s, float(audio["fade_out_s"]), _outro_s(edl)
    )
    tail = (
        f"afade=t=out:st={fade_st}:d={fade_d}"
        if fade_d > 0
        else "anull"
    )
    graph += (
        f"[m]{mix_inputs}amix=inputs={len(sfx) + 1}:duration=first:normalize=0,"
        f"{tail}[a]"
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
