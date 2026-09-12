"""Capa 6 (preview) y Capa 7 (render): segmentos, concat, audio, checks R1-R6.

Ver docs/architecture/arquitectura_edl_agent_v4.md #9, #10.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

FINAL_TARGET = {"w": 1080, "h": 1920}
PREVIEW_TARGET = {"w": 540, "h": 960}

COLOR_ARGS = [
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-colorspace",
    "bt709",
    "-color_range",
    "tv",
]


class RenderError(RuntimeError):
    """Un check R1-R6 ha fallado, o el render en si ha fallado."""


# --------------------------------------------------------------------------
# render_profile (#7, #10): todo lo que hace falta para re-renderizar bit a bit.
# --------------------------------------------------------------------------


def _dpkg_version(package_prefix: str) -> str | None:
    # ponytail: solo cubre Debian/Ubuntu (dpkg-query); en otras distros
    # devuelve None y zimg_version/libx264_version quedan sin verificar.
    try:
        out = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package} ${Version}\n"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError, FileNotFoundError:
        return None
    for line in out.splitlines():
        pkg, _, version = line.partition(" ")
        if pkg.startswith(package_prefix):
            return version
    return None


def _ffmpeg_version_info() -> dict:
    out = subprocess.run(
        ["ffmpeg", "-version"], check=True, capture_output=True, text=True
    ).stdout
    lines = out.splitlines()
    version = lines[0].split(" ")[2]
    config_line = next(
        (line for line in lines if line.startswith("configuration:")), ""
    )
    configuration = config_line.removeprefix("configuration:").strip()
    return {"ffmpeg_version": version, "ffmpeg_configuration": configuration}


def get_render_profile(
    threads: int = 4, tonemap_chain: str = "", tonemap_chain_pq: str | None = None
) -> dict:
    profile = {
        **_ffmpeg_version_info(),
        "libx264_version": _dpkg_version("libx264") or "unknown",
        "zimg_version": _dpkg_version("libzimg"),
        "threads": threads,
        "tonemap_chain": tonemap_chain,
        "tonemap_chain_pq": tonemap_chain_pq,
        "video_codec_args": " ".join(_video_codec_args(threads, preview=False)),
        "segment_filter_template": (
            "crop={w}:{h}:{x}:{y},setpts=PTS/{speed},fps=30,"
            "scale={tw}:{th}:flags=lanczos,{hdr}setsar=1,format=yuv420p"
        ),
        "blur_pad_filter_template": (
            "[0:v]setpts=PTS/{speed},fps=30,scale='if(gt(iw,ih),-2,{tw})':'if(gt(iw,ih),{tw},-2)':flags=lanczos,{hdr}split[a][b];"
            "[a]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},boxblur={blur_radius}:{blur_power},eq=brightness={bg_brightness}[bg];"
            "[b]scale={tw}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]"
        ),
        "image_filter_template": (
            "crop={w}:{h}:{x}:{y},scale={ptw}:{pth}:flags=lanczos,"
            "zoompan=z='min(1.0+{zoom_per_frame}*(on-1),{zoom_max})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={tw}x{th}:fps=30,"
            "setsar=1,format=yuv420p"
        ),
        "audio_codec_args": "-c:a aac -b:a 192k -ar 48000",
    }
    profile["profile_sha256"] = hashlib.sha256(
        json.dumps(profile, sort_keys=True).encode(),
    ).hexdigest()
    return profile


def _video_codec_args(threads: int, preview: bool) -> list[str]:
    crf, preset = ("30", "ultrafast") if preview else ("18", "medium")
    return [
        "-c:v",
        "libx264",
        "-crf",
        crf,
        "-preset",
        preset,
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        "30000",
        "-g",
        "60",
        "-keyint_min",
        "60",
        "-sc_threshold",
        "0",
        "-threads",
        str(threads),
    ]


# --------------------------------------------------------------------------
# Crop normalizado -> pixeles (#6.5). Funcion pura; la usa el planner (parte 3)
# y aqui la preview para recalcular sobre las dims del proxy.
# --------------------------------------------------------------------------


def is_916(w: int, h: int) -> bool:
    return abs(w / h - 9 / 16) < 0.01


def _even(x: float) -> int:
    v = round(x)
    return v - (v % 2)


def crop_to_px(crop: dict, w: int, h: int, layout: str) -> dict:
    h_px = _even(crop["h"] * h)
    if layout == "crop" and not is_916(w, h):
        w_px = _even(h_px * 9 / 16)
        if w_px > w:
            w_px = w if w % 2 == 0 else w - 1
            h_px = _even(w_px * 16 / 9)
    else:
        w_px = _even(crop["w"] * w)
    h_px, w_px = max(h_px, 2), max(w_px, 2)
    x_px = max(0, min(_even(crop["x"] * w), w - w_px))
    y_px = max(0, min(_even(crop["y"] * h), h - h_px))
    return {"x": x_px, "y": y_px, "w": w_px, "h": h_px}


# --------------------------------------------------------------------------
# Segmentos (#10.1-10.3, #9)
# --------------------------------------------------------------------------


def _hdr_prefix(hdr: str, tonemap_chain: str) -> str:
    return f"{tonemap_chain}," if hdr in ("hlg", "dv84") and tonemap_chain else ""


def render_video_segment(
    clip: dict,
    src_path: str,
    crop_px: dict,
    out_path: Path,
    threads: int,
    tonemap_chain: str,
    preview: bool = False,
) -> None:
    target = PREVIEW_TARGET if preview else FINAL_TARGET
    n_frames = clip["n_frames"]
    speed = clip["speed"]
    t_safety = n_frames / 30 * speed + 0.5
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # El proxy (fuente de la preview) ya sale de build_proxy tonemapeado a bt709 SDR
    # (#3.2); reaplicar la cadena aqui interpretaria esos pixeles SDR como HLG de
    # nuevo y oscureceria/desaturaria la preview.
    hdr_prefix = "" if preview else _hdr_prefix(clip["hdr"], tonemap_chain)

    if clip["layout"] == "crop":
        vf = (
            f"crop={crop_px['w']}:{crop_px['h']}:{crop_px['x']}:{crop_px['y']},"
            f"setpts=PTS/{speed},fps=30,"
            f"scale={target['w']}:{target['h']}:flags=lanczos,"
            f"{hdr_prefix}setsar=1,format=yuv420p"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(clip["in_s"]),
            "-t",
            str(t_safety),
            "-i",
            src_path,
            "-vf",
            vf,
            "-fps_mode",
            "cfr",
            "-frames:v",
            str(n_frames),
            *COLOR_ARGS,
            "-an",
            *_video_codec_args(threads, preview),
            str(out_path),
        ]
    else:  # blur_pad
        params = clip["effect_params"]
        filter_complex = (
            f"[0:v]setpts=PTS/{speed},fps=30,"
            f"scale='if(gt(iw,ih),-2,{target['w']})':'if(gt(iw,ih),{target['w']},-2)':flags=lanczos,"
            f"{hdr_prefix}split[a][b];"
            f"[a]scale={target['w']}:{target['h']}:force_original_aspect_ratio=increase,"
            f"crop={target['w']}:{target['h']},"
            f"boxblur={params['blur_radius']}:{params['blur_power']},"
            f"eq=brightness={params['bg_brightness']}[bg];"
            f"[b]scale={target['w']}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(clip["in_s"]),
            "-t",
            str(t_safety),
            "-i",
            src_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-fps_mode",
            "cfr",
            "-frames:v",
            str(n_frames),
            *COLOR_ARGS,
            "-an",
            *_video_codec_args(threads, preview),
            str(out_path),
        ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def render_image_segment(
    clip: dict,
    image_path: str,
    crop_px: dict,
    out_path: Path,
    threads: int,
    preview: bool = False,
) -> None:
    target = PREVIEW_TARGET if preview else FINAL_TARGET
    n_frames = clip["n_frames"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if clip["effect"] == "kenburns":
        params = clip["effect_params"]
        prescale_w, prescale_h = target["w"] * 3, target["h"] * 3
        vf = (
            f"crop={crop_px['w']}:{crop_px['h']}:{crop_px['x']}:{crop_px['y']},"
            f"scale={prescale_w}:{prescale_h}:flags=lanczos,"
            f"zoompan=z='min(1.0+{params['zoom_per_frame']}*(on-1),{params['zoom_max']})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={target['w']}x{target['h']}:fps=30,"
            f"setsar=1,format=yuv420p"
        )
    else:
        vf = (
            f"crop={crop_px['w']}:{crop_px['h']}:{crop_px['x']}:{crop_px['y']},"
            f"scale={target['w']}:{target['h']}:flags=lanczos,setsar=1,format=yuv420p"
        )
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        image_path,
        "-vf",
        vf,
        "-fps_mode",
        "cfr",
        "-frames:v",
        str(n_frames),
        *COLOR_ARGS,
        "-an",
        *_video_codec_args(threads, preview),
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _src_path_and_dims(
    clip: dict,
    sources_by_src: dict,
    session_dir: Path,
    preview: bool,
) -> tuple[str, int, int]:
    if clip["type"] == "image":
        normalized = session_dir / sources_by_src[clip["src"]]["normalized"]
        return str(normalized), clip["src_w"], clip["src_h"]
    if preview:
        source = sources_by_src[clip["src"]]
        proxy = session_dir / source["proxy"]
        return (str(proxy), *_proxy_wh(proxy))
    return str(session_dir / clip["src"]), clip["src_w"], clip["src_h"]


def render_segment(
    clip: dict,
    sources_by_src: dict,
    session_dir: Path,
    out_dir: Path,
    threads: int,
    tonemap_chain: str,
    preview: bool = False,
) -> Path:
    src_path, w, h = _src_path_and_dims(clip, sources_by_src, session_dir, preview)
    out_path = out_dir / f"seg_{clip['slot']:02d}.mp4"
    crop_px = (
        crop_to_px(clip["crop"], w, h, clip["layout"]) if preview else clip["crop_px"]
    )

    if clip["type"] == "image":
        render_image_segment(
            clip, src_path, crop_px, out_path, threads, preview=preview
        )
    else:
        render_video_segment(
            clip, src_path, crop_px, out_path, threads, tonemap_chain, preview=preview
        )
    return out_path


def render_segments(
    edl: dict, manifest: dict, session_dir: Path, threads: int, tonemap_chain: str = ""
) -> list[Path]:
    sources_by_src = {s["src"]: s for s in manifest["sources"]}
    out_dir = session_dir / "segments"
    return [
        render_segment(
            clip,
            sources_by_src,
            session_dir,
            out_dir,
            threads,
            tonemap_chain,
            preview=False,
        )
        for clip in edl["clips"]
    ]


def render_preview_segments(
    edl: dict,
    manifest: dict,
    session_dir: Path,
    threads: int,
    tonemap_chain: str = "",
) -> list[Path]:
    sources_by_src = {s["src"]: s for s in manifest["sources"]}
    out_dir = session_dir / "preview_segments"
    return [
        render_segment(
            clip,
            sources_by_src,
            session_dir,
            out_dir,
            threads,
            tonemap_chain,
            preview=True,
        )
        for clip in edl["clips"]
    ]


def _proxy_wh(proxy_path: Path) -> tuple[int, int]:
    from .ingest import _video_stream, ffprobe

    stream = _video_stream(ffprobe(proxy_path))
    return int(stream["width"]), int(stream["height"])


# --------------------------------------------------------------------------
# Concat + audio, dos pasadas de loudnorm (#10.4)
# --------------------------------------------------------------------------

_LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}")


def _parse_loudnorm_json(stderr: str) -> dict:
    match = _LOUDNORM_JSON_RE.search(stderr)
    if not match:
        msg = f"no loudnorm JSON found in ffmpeg output:\n{stderr}"
        raise RenderError(msg)
    return json.loads(match.group(0))


def concat_and_audio(edl: dict, session_dir: Path, threads: int) -> Path:
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


# --------------------------------------------------------------------------
# Checks R1-R6 (#10.5)
# --------------------------------------------------------------------------


@dataclass
class CheckResult:
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
            "-vsync",
            "0",
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
    applied = audio.get("loudnorm_applied")
    if applied is None:
        return CheckResult("R5", True, "no music track")
    normalization_type = applied.get("normalization_type")
    if normalization_type == "linear":
        return CheckResult("R5", True)
    return CheckResult("R5", allow_dynamic, f"normalization_type={normalization_type}")


def check_r6_monotonic_dts(reel_path: Path) -> CheckResult:
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
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for clip in edl["clips"]:
        final_seg = session_dir / "segments" / f"seg_{clip['slot']:02d}.mp4"
        results.append(check_r1_frame_count(final_seg, clip["n_frames"]))
        if run_r2:
            preview_seg = (
                session_dir / "preview_segments" / f"seg_{clip['slot']:02d}.mp4"
            )
            results.append(check_r2_phash(final_seg, preview_seg, clip["n_frames"]))
        results.append(check_r4_color(final_seg))

    reel_path = session_dir / "reel.mp4"
    results.append(check_r3_reel_duration(reel_path, edl["target"]["duration_f"]))
    results.append(check_r4_color(reel_path))
    results.append(
        check_r5_loudnorm_linear(edl["audio"], allow_dynamic=allow_dynamic_loudnorm)
    )
    results.append(check_r6_monotonic_dts(reel_path))
    return results


# --------------------------------------------------------------------------
# Orquestacion (#8.5, #14 paso 2): render + preview + concat + checks.
# --------------------------------------------------------------------------


def run_render(
    edl: dict,
    manifest: dict,
    session_dir: Path,
    threads: int = 4,
    tonemap_chain: str = "",
    allow_dynamic_loudnorm: bool = False,
) -> list[CheckResult]:
    render_segments(edl, manifest, session_dir, threads, tonemap_chain)
    render_preview_segments(edl, manifest, session_dir, threads, tonemap_chain)
    concat_and_audio(edl, session_dir, threads)
    results = run_render_checks(
        edl, session_dir, allow_dynamic_loudnorm=allow_dynamic_loudnorm
    )
    failed = [r for r in results if not r.ok]
    if failed:
        raise RenderError("; ".join(f"{r.name}: {r.detail}" for r in failed))
    return results
