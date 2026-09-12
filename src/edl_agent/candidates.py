"""Capa 2 - Candidatos (candidates.json), #4.3.

Consume las series de `features.py` (una por fuente de video) y produce los
candidatos `peak`/`calm`/`image` que el planner y el selector LLM consumen.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

FPS = 30
PEAK_MIN_DISTANCE_SAMPLES = 10  # >=1s entre picos a 10fps (#4.3.1)
PEAK_MIN_PROMINENCE = 0.2  # [validar]
SHARPNESS_MIN = 0.35  # [validar]
PEAK_MOTION_BG_MAX = 0.6  # [validar]
PEAK_WINDOW_MAX_S = 6.0
PEAK_WINDOW_SHARPNESS_TOLERANCE = 3  # frames de sharpness baja tolerados sin cortar la ventana (motion blur transitorio en el pico); subir si sigue cortando ventanas cerca de picos reales

CALM_MIN_DURATION_S = 2.0
CALM_KP_SPEED_MAX = 0.25
CALM_MOTION_BG_MAX = 0.25  # [validar]
CALM_SHARPNESS_MIN = 0.5
CALM_CENTER_X_TOL = 0.2
CALM_CENTER_Y_TOL = 0.25
CALM_MAX_PER_CLIP = 2

PEAK_FRAME_OFFSETS_S = (-0.3, 0.0, 0.3)
PEAK_FRAME_SIDE_PX = 512


def edge_margin_s(clip_duration_s: float) -> float:
    """#4.3.2: 0.5s si el clip dura >=5s, si no 0.25s."""
    return 0.5 if clip_duration_s >= 5.0 else 0.25


def find_peak_windows(features: dict, clip_duration_s: float, scene_cuts_s: list[float]) -> list[dict]:
    """#4.3 `peak`: picos locales de kp_speed con descarte y ventana."""
    kp_speed = np.asarray(features["kp_speed"])
    t_s = features["t_s"]
    sharpness = features["sharpness"]
    subject_visible = features["subject_visible"]
    motion_bg = features["motion_bg"]

    idxs, _ = find_peaks(kp_speed, distance=PEAK_MIN_DISTANCE_SAMPLES, prominence=PEAK_MIN_PROMINENCE)
    margin = edge_margin_s(clip_duration_s)

    out = []
    for i in idxs:
        t_peak = t_s[i]
        if sharpness[i] < SHARPNESS_MIN or not subject_visible[i] or motion_bg[i] > PEAK_MOTION_BG_MAX:
            continue
        if t_peak < margin or (clip_duration_s - t_peak) < margin:
            continue
        if any(abs(t_peak - c) < margin for c in scene_cuts_s):
            continue
        window = _peak_window(features, int(i), scene_cuts_s)
        out.append({"kind": "peak", "t_peak": t_peak, "window": window, "index": int(i)})
    return out


def _crosses_cut(t_a: float, t_b: float, scene_cuts_s: list[float]) -> bool:
    lo, hi = min(t_a, t_b), max(t_a, t_b)
    return any(lo < c <= hi for c in scene_cuts_s)


def _peak_window(features: dict, i: int, scene_cuts_s: list[float]) -> list[float]:
    """Crece la ventana desde el pico hacia cada lado. Un corte de escena o
    perdida de sujeto es un limite real y corta de inmediato; una racha corta
    de sharpness baja (motion blur del propio movimiento explosivo que hace
    el pico) se tolera sin cortar, pero el limite de la ventana no pasa del
    ultimo frame nitido.
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
    """#4.3 `calm`: tramos estables, maximo 2 por clip (los mas largos)."""
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
        out.append({"kind": "calm", "t_peak": t_s[center_i], "window": [t_s[a], t_s[b]]})
    return out


def admits_slots(window: tuple[float, float], slots: list[dict], speed: float = 1.0, fps: int = FPS) -> list[int]:
    """#4.3 `admits_slots`: mismo calculo que #6.1, precalculado para no
    enviar al LLM candidatos que no caben en ningun slot.
    """
    out = []
    for s in slots:
        d_f = s["end_f"] - s["start_f"]
        need_s = d_f / fps * speed
        if (window[1] - window[0]) >= need_s + 2 / fps:
            out.append(s["slot"])
    return out


def score_cv(kp_speed: float, sharpness: float, bbox: tuple | None, kind: str) -> float:
    """#4.3 `score_cv`, usado por el fallback y la relajacion del planner."""
    cx = (bbox[0] + bbox[2]) / 2 if bbox else 0.5
    centrality = 1 - 2 * abs(cx - 0.5)
    action_term = 0.5 * (1 - kp_speed) if kind == "calm" else 0.5 * kp_speed
    return action_term + 0.3 * sharpness + 0.2 * centrality


def extract_peak_frames(proxy_path: str, t_peak: float, window: tuple[float, float],
                         out_dir: Path, cand_id: str) -> tuple[list[str], list[str]]:
    """#4.3 `peak_frames`: 3 JPEG (t-0.3, t, t+0.3, clamp a la ventana)."""
    from .ingest import sha256_file

    out_dir.mkdir(parents=True, exist_ok=True)
    scale = f"scale='if(gt(iw,ih),{PEAK_FRAME_SIDE_PX},-2)':'if(gt(iw,ih),-2,{PEAK_FRAME_SIDE_PX})'"
    paths, hashes = [], []
    for i, off in enumerate(PEAK_FRAME_OFFSETS_S):
        t = min(max(t_peak + off, window[0]), window[1])
        out_path = out_dir / f"{cand_id}_{i}.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", str(max(t, 0.0)), "-i", str(proxy_path),
            "-frames:v", "1", "-vf", scale, "-q:v", "4", str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        paths.append(str(out_path))
        hashes.append(sha256_file(out_path))
    return paths, hashes


def build_contact_sheet(peak_frame_paths: list[str], out_path: Path) -> Path:
    """Hoja de contacto horizontal, solo para inspeccion humana (#4.3)."""
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
    src: str, id_start: int, features: dict, clip_duration_s: float,
    scene_cuts_s: list[float], slots: list[dict], proxy_path: str, peaks_dir: Path,
    speed: float = 1.0,
) -> list[dict]:
    """Ensambla los candidatos `peak`+`calm` de una fuente de video (#4.3).
    Ids globales `c{NN}` a partir de `id_start`.
    """
    windows = find_peak_windows(features, clip_duration_s, scene_cuts_s) + find_calm_windows(features)
    out = []
    for n, w in enumerate(windows):
        cand_id = f"c{id_start + n:02d}"
        i = w.get("index")
        bbox = features["subject_bbox"][i] if i is not None else _bbox_at(features, w["t_peak"])
        kp_speed = features["kp_speed"][i] if i is not None else _value_at(features, "kp_speed", w["t_peak"])
        sharpness = features["sharpness"][i] if i is not None else _value_at(features, "sharpness", w["t_peak"])
        motion_bg = features["motion_bg"][i] if i is not None else _value_at(features, "motion_bg", w["t_peak"])
        multi_subject = features["multi_subject"][i] if i is not None else False

        peak_frames, peak_frames_sha256 = extract_peak_frames(
            proxy_path, w["t_peak"], tuple(w["window"]), peaks_dir, cand_id,
        )
        build_contact_sheet(peak_frames, peaks_dir / f"{cand_id}_contact.jpg")

        out.append({
            "id": cand_id, "src": src, "kind": w["kind"],
            "t_peak": w["t_peak"], "window": w["window"],
            "kp_speed": kp_speed, "motion_bg": motion_bg, "sharpness": sharpness,
            "subject_bbox": list(bbox) if bbox else [0.0, 0.0, 1.0, 1.0],
            "multi_subject": bool(multi_subject),
            "score_cv": score_cv(kp_speed, sharpness, bbox, w["kind"]),
            "admits_slots": admits_slots(tuple(w["window"]), slots, speed),
            "peak_frames": peak_frames, "peak_frames_sha256": peak_frames_sha256,
        })
    return out


def _nearest_index(features: dict, t: float) -> int:
    t_s = features["t_s"]
    return min(range(len(t_s)), key=lambda i: abs(t_s[i] - t))


def _bbox_at(features: dict, t: float):
    return features["subject_bbox"][_nearest_index(features, t)]


def _value_at(features: dict, key: str, t: float):
    return features[key][_nearest_index(features, t)]


def build_image_candidate(src: str, cand_id: str, slots: list[dict], peak_frame: str) -> dict:
    """#4.3 candidato `image`: t_peak=0, ventana [0, 1e9], se admite en todos los slots."""
    import hashlib

    from .ingest import sha256_file

    return {
        "id": cand_id, "src": src, "kind": "image",
        "t_peak": 0.0, "window": [0.0, 1e9],
        "kp_speed": 0.0, "motion_bg": 0.0, "sharpness": 0.85,
        "subject_bbox": [0.25, 0.10, 0.75, 0.90],
        "multi_subject": False,
        "score_cv": score_cv(0.0, 0.85, (0.25, 0.10, 0.75, 0.90), "image"),
        "admits_slots": [s["slot"] for s in slots],
        "peak_frames": [peak_frame],
        "peak_frames_sha256": [sha256_file(Path(peak_frame))] if Path(peak_frame).exists()
        else [hashlib.sha256(b"").hexdigest()],
    }
