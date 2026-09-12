"""Capa 2 (parcial) - Audio -> slots.json.

Ver docs/architecture/arquitectura_edl_agent_v4.md #4.1.
"""

from __future__ import annotations

import numpy as np

FRAME_RATE = 30
UNIFORM_GRID_S = 1.6  # 48 frames, usado si beats_confident == False
MIN_SLOT_FRAMES = 30


def detect_beats(path: str) -> tuple[float, list[float]]:
    """#4.1.1. Devuelve (tempo_bpm, beats_s)."""
    import librosa

    y, sr = librosa.load(path, sr=None, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beats_s = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    return float(np.asarray(tempo).item()), beats_s


def beats_confident(
    tempo_bpm: float, y: np.ndarray, sr: float, _beats_s: list[float]
) -> bool:
    """#4.1.2. [validar umbral] autocorrelacion de onset_strength en el lag
    del tempo.
    """
    import librosa

    if not (50 <= tempo_bpm <= 200):
        return False
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    hop_length = 512
    lag_frames = round((60.0 / tempo_bpm) * sr / hop_length)
    if lag_frames <= 0 or lag_frames >= len(onset_env):
        return False
    ac = librosa.autocorrelate(onset_env, max_size=lag_frames + 1)
    peak = ac[lag_frames] / ac[0] if ac[0] > 0 else 0.0
    return bool(peak >= 0.3)


def build_slots(
    duration_s: float,
    tempo_bpm: float,
    beats_s: list[float],
    confident: bool,
) -> dict:
    """#4.1.3-4.1.7. Construye slots.json a partir de beats (o grid uniforme)."""
    duration_f = round(duration_s * FRAME_RATE)

    if confident:
        beats_f = sorted({round(b * FRAME_RATE) for b in beats_s})
        beats_per_slot = max(1, int(np.ceil(tempo_bpm / 60.0)))
    else:
        # #4.1.2: grid uniforme de 1.6s (48 frames) con beats sinteticos cada
        # 24 frames (2 por slot) para que la alineacion a beat siga funcionando.
        synthetic_step_f = round(UNIFORM_GRID_S * FRAME_RATE / 2)  # 24
        beats_f = list(range(0, duration_f, synthetic_step_f))
        beats_per_slot = 2

    beats_f = sorted(set(beats_f) | {0, duration_f})
    beats_f = [b for b in beats_f if 0 <= b <= duration_f]

    # Agrupacion: los beats (sin contar el final synthetic duration_f salvo que
    # coincida con uno real) se agrupan de beats_per_slot en beats_per_slot,
    # empezando por el primer beat >= 0.
    interior_beats = [b for b in beats_f if b < duration_f]
    if not interior_beats or interior_beats[0] != 0:
        interior_beats = [0, *interior_beats]

    starts = interior_beats[::beats_per_slot]
    slot_bounds = [*starts, duration_f]
    slot_bounds = sorted(set(slot_bounds))

    # #4.1.5 Residuo: cualquier slot (interior o el ultimo) < MIN_SLOT_FRAMES se
    # fusiona con el anterior (el primero, hook, nunca se fusiona hacia atras).
    # Fusionar el slot j (bounds[j]..bounds[j+1]) con el j-1 anterior es borrar
    # el limite bounds[j].
    bounds = list(slot_bounds)
    changed = True
    while changed:
        changed = False
        for j in range(1, len(bounds) - 1):
            if bounds[j + 1] - bounds[j] < MIN_SLOT_FRAMES and len(bounds) > 2:
                del bounds[j]
                changed = True
                break

    slots = []
    for i in range(len(bounds) - 1):
        start_f, end_f = bounds[i], bounds[i + 1]
        if i == 0:
            role = "hook"
        elif i == len(bounds) - 2:
            role = "close"
        else:
            role = "develop"
        beats_rel_f = sorted(
            {b - start_f for b in beats_f if start_f <= b < end_f} | {0}
        )
        slots.append(
            {
                "slot": i,
                "start_f": start_f,
                "end_f": end_f,
                "role": role,
                "beats_rel_f": beats_rel_f,
            }
        )

    if len(slots) < 2:
        msg = "audio too short to produce hook+close slots"
        raise ValueError(msg)

    return {
        "duration_f": duration_f,
        "tempo_bpm": tempo_bpm,
        "beats_confident": confident,
        "beats_per_slot": beats_per_slot,
        "slots": slots,
    }


def slots_from_file(path: str) -> dict:
    """Orquesta #4.1 completo sobre un WAV (music/track_cut.wav)."""
    import librosa

    y, sr = librosa.load(path, sr=None, mono=True)
    duration_s = len(y) / sr
    tempo_bpm, beats_s = detect_beats(path)
    confident = beats_confident(tempo_bpm, y, sr, beats_s)
    result = build_slots(duration_s, tempo_bpm, beats_s, confident)
    result["music_cut"] = path
    return result
