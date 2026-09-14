"""Layer 2 (partial) - Audio -> slots.json.

See docs/architecture/04-features.md #4.1.
"""

from __future__ import annotations

import itertools

import numpy as np

FRAME_RATE = 30
UNIFORM_GRID_S = 1.6  # 48 frames, used when beats_confident == False
MIN_SLOT_FRAMES = 30
# ponytail: below this, a beat tracker locking onto the backbeat/half-time
# period (a common octave error, e.g. four-on-the-floor at 128 BPM read as
# 64) is more likely than a genuinely slow track; raise/lower if a genre
# with legitimately slow real tempos starts getting doubled.
OCTAVE_CORRECT_BELOW_BPM = 95.0


def detect_beats(path: str) -> tuple[float, list[float]]:
    """Detect tempo and beat timestamps in an audio file, per #4.1.1.

    Args:
        path: Path to the audio file (e.g. `music/track_cut.wav`).

    Returns:
        `(tempo_bpm, beats_s)`: estimated tempo in BPM, and a list of beat
        timestamps in seconds.
    """
    import librosa

    y, sr = librosa.load(path, sr=None, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beats_s = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    return float(np.asarray(tempo).item()), beats_s


def _onset_autocorr_peak(onset_env: np.ndarray, sr: float, tempo_bpm: float) -> float:
    """Onset-strength autocorrelation strength at `tempo_bpm`'s beat lag, 0..1."""
    import librosa

    hop_length = 512
    lag_frames = round((60.0 / tempo_bpm) * sr / hop_length)
    if lag_frames <= 0 or lag_frames >= len(onset_env):
        return 0.0
    ac = librosa.autocorrelate(onset_env, max_size=lag_frames + 1)
    return float(ac[lag_frames] / ac[0]) if ac[0] > 0 else 0.0


def beats_confident(
    tempo_bpm: float, y: np.ndarray, sr: float, _beats_s: list[float]
) -> bool:
    """Decide whether detected beats are reliable enough to build slots from.

    Checks that `tempo_bpm` is in a plausible range and that onset-strength
    autocorrelation at the tempo's lag is strong, per #4.1.2.

    [validate threshold]

    Args:
        tempo_bpm: Estimated tempo, in BPM, from `detect_beats`.
        y: Audio samples (mono), as loaded by `librosa.load`.
        sr: Sample rate of `y`, in Hz.
        _beats_s: Beat timestamps from `detect_beats` (unused; kept for
            interface parity).

    Returns:
        `True` if beats look reliable enough to drive slot placement;
        `False` if a uniform grid should be used instead.
    """
    import librosa

    if not (50 <= tempo_bpm <= 200):
        return False
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    return _onset_autocorr_peak(onset_env, sr, tempo_bpm) >= 0.3


def correct_octave_error(
    tempo_bpm: float, beats_s: list[float], onset_env: np.ndarray, sr: float
) -> tuple[float, list[float]]:
    """Double `tempo_bpm`/interpolate `beats_s` if that looks like the real tempo.

    Beat trackers commonly lock onto the backbeat/half-time period instead
    of the true tempo (e.g. four-on-the-floor at 128 BPM read as 64), which
    halves the detected beat count and starves `build_slots` of slots. Only
    applies below `OCTAVE_CORRECT_BELOW_BPM`, and only if the doubled
    tempo's autocorrelation peak also clears the confidence threshold used
    by `beats_confident`.

    Args:
        tempo_bpm: Estimated tempo, in BPM, from `detect_beats`.
        beats_s: Beat timestamps, in seconds, from `detect_beats`.
        onset_env: Onset-strength envelope, from `librosa.onset.onset_strength`.
        sr: Sample rate `onset_env` was computed at, in Hz.

    Returns:
        `(tempo_bpm, beats_s)`, doubled/interpolated if an octave error was
        detected, unchanged otherwise.
    """
    if tempo_bpm >= OCTAVE_CORRECT_BELOW_BPM:
        return tempo_bpm, beats_s
    doubled_bpm = tempo_bpm * 2
    if _onset_autocorr_peak(onset_env, sr, doubled_bpm) < 0.3:
        return tempo_bpm, beats_s
    sorted_beats = sorted(beats_s)
    midpoints = [
        (a + b) / 2 for a, b in itertools.pairwise(sorted_beats)
    ]
    return doubled_bpm, sorted(sorted_beats + midpoints)


def build_slots(
    duration_s: float,
    tempo_bpm: float,
    beats_s: list[float],
    confident: bool,
) -> dict:
    """Build `slots.json` from detected beats (or a uniform grid), per #4.1.3-4.1.7.

    Args:
        duration_s: Target reel duration, in seconds.
        tempo_bpm: Estimated tempo, in BPM (see `detect_beats`).
        beats_s: Beat timestamps, in seconds (see `detect_beats`); ignored
            if `confident` is `False`.
        confident: Whether to use `beats_s` (`True`) or fall back to a
            uniform grid (`False`), per `beats_confident`.

    Returns:
        Dict with `duration_f` (int, total frames), `tempo_bpm` (float),
        `beats_confident` (bool, echoes `confident`), `beats_per_slot`
        (int), and `slots` (list of slot dicts, each with `slot` (int,
        0-based index), `start_f`/`end_f` (int, frame bounds), `role`
        (`"hook"`, `"develop"`, or `"close"`), and `beats_rel_f` (list of
        int, beat offsets relative to `start_f`)).

    Raises:
        ValueError: If fewer than 2 slots result (audio too short to
            produce hook+close slots).
    """
    duration_f = round(duration_s * FRAME_RATE)

    if confident:
        beats_f = sorted({round(b * FRAME_RATE) for b in beats_s})
        beats_per_slot = max(1, int(np.ceil(tempo_bpm / 60.0)))
        # #4.1.3: detected beats can stop partway through duration_f (e.g. a
        # rhythmic section ends early). Any gap wider than one uniform-grid
        # slot has no real beat to anchor a boundary, so fill it with the
        # same synthetic grid used for beats_confident == False, instead of
        # letting one oversized slot span the whole gap.
        gap_step_f = round(UNIFORM_GRID_S * FRAME_RATE / 2)
        gap_threshold_f = round(UNIFORM_GRID_S * FRAME_RATE)
        edges = [0, *beats_f, duration_f]
        filled = list(beats_f)
        for a, b in itertools.pairwise(edges):
            if b - a > gap_threshold_f:
                filled.extend(range(a + gap_step_f, b, gap_step_f))
        beats_f = sorted(set(filled))
    else:
        # #4.1.2: uniform 1.6s (48-frame) grid with synthetic beats every 24
        # frames (2 per slot) so beat alignment keeps working downstream.
        synthetic_step_f = round(UNIFORM_GRID_S * FRAME_RATE / 2)  # 24
        beats_f = list(range(0, duration_f, synthetic_step_f))
        beats_per_slot = 2

    beats_f = sorted(set(beats_f) | {0, duration_f})
    beats_f = [b for b in beats_f if 0 <= b <= duration_f]

    # Grouping: beats (excluding the synthetic end duration_f unless it
    # coincides with a real one) are grouped beats_per_slot at a time,
    # starting from the first beat >= 0.
    interior_beats = [b for b in beats_f if b < duration_f]
    if not interior_beats or interior_beats[0] != 0:
        interior_beats = [0, *interior_beats]

    starts = interior_beats[::beats_per_slot]
    slot_bounds = [*starts, duration_f]
    slot_bounds = sorted(set(slot_bounds))

    # #4.1.5 Remainder: any slot (interior or last) shorter than
    # MIN_SLOT_FRAMES is merged into the previous one (the first slot, hook,
    # is never merged backward). Merging slot j (bounds[j]..bounds[j+1])
    # into slot j-1 means deleting boundary bounds[j].
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
    """Run the full #4.1 pipeline over a WAV file.

    Args:
        path: Path to the audio file (e.g. `music/track_cut.wav`).

    Returns:
        The `slots.json` dict from `build_slots`, with an added
        `music_cut` key (str, echoes `path`).

    Raises:
        ValueError: If fewer than 2 slots result (audio too short to
            produce hook+close slots); see `build_slots`.
    """
    import librosa

    y, sr = librosa.load(path, sr=None, mono=True)
    duration_s = len(y) / sr
    tempo_bpm, beats_s = detect_beats(path)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo_bpm, beats_s = correct_octave_error(tempo_bpm, beats_s, onset_env, sr)
    confident = beats_confident(tempo_bpm, y, sr, beats_s)
    result = build_slots(duration_s, tempo_bpm, beats_s, confident)
    result["music_cut"] = path
    return result
