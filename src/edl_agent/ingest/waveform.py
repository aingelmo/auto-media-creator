"""Waveform peak extraction for the library's compact audio players.

Peaks are the maximum absolute amplitude per equal-width bucket across a
track, normalized to `0.0`-`1.0`. The UI draws them as a waveform that
doubles as the scrub affordance, so the shape of a track (intro, build,
drop) is visible before pressing play. See `#6.2` for music sourcing.
"""

from __future__ import annotations

import array
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Enough resolution for a wide player without shipping kilobytes per
# track: 320 buckets redraw a ~900px band at roughly 3px per bar.
PEAK_BUCKETS = 320

# Decode target for peak extraction. 8 kHz mono is far below anything
# audible but plenty to recover an envelope, and keeps the ffmpeg pipe
# small (~16 KB/s of source).
PEAK_SAMPLE_RATE = 8000


def extract_peaks(
    path: Path,
    buckets: int = PEAK_BUCKETS,
    sample_rate: int = PEAK_SAMPLE_RATE,
    start_s: float | None = None,
    window_s: float | None = None,
) -> list[float]:
    """Decode a track and return its normalized amplitude envelope.

    Runs ffmpeg in-process to convert `path` to signed 16-bit mono PCM on
    stdout, then reduces it to one peak per bucket. Any container/codec
    ffmpeg reads is supported, including the `mp4`/`m4a` music uploads
    that a WAV-only reader would miss.

    Args:
        path: Audio (or audio-bearing container) file to decode.
        buckets: Number of equal-duration slices to reduce to one peak
            each. Buckets are contiguous and cover the whole track, or
            just `[start_s, start_s + window_s]` when a range is given.
        sample_rate: Decode rate in Hz for the intermediate PCM.
        start_s: Optional range start in seconds (seek before decode,
            for zoomed windows). `None` decodes from the start.
        window_s: Optional range length in seconds (limit decode length).
            `None` decodes to the end of the file.

    Returns:
        List of `buckets` floats in `0.0`-`1.0`, where `1.0` is full
        scale. An empty track (no decodable samples) yields `[]`.

    Raises:
        subprocess.CalledProcessError: If ffmpeg fails to read the file
            (unsupported codec, corrupt container, missing input).
        FileNotFoundError: If the `ffmpeg` binary is not on `PATH`.
    """
    cmd = ["ffmpeg", "-v", "error"]
    if start_s is not None and start_s > 0:
        cmd += ["-ss", str(max(0.0, start_s))]
    cmd += ["-i", str(path)]
    if window_s is not None and window_s > 0:
        cmd += ["-t", str(window_s)]
    cmd += ["-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"]
    out = subprocess.run(cmd, check=True, capture_output=True)
    raw = out.stdout[: len(out.stdout) // 2 * 2]
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    total = len(samples)
    if total == 0:
        return []

    peaks: list[float] = []
    for i in range(buckets):
        lo = total * i // buckets
        hi = max(lo + 1, total * (i + 1) // buckets)
        chunk = samples[lo:hi]
        high, low = max(chunk), min(chunk)
        amplitude = max(high, -low)
        peaks.append(round(amplitude / 32768.0, 3))
    return peaks


def measure_loudness(path: Path) -> dict[str, float | None]:
    """Measure a track's loudness via ffmpeg volumedetect, never raising.

    Args:
        path: Audio (or audio-bearing container) file to measure.

    Returns:
        Dict with `mean_volume_db` and `max_volume_db` (`float` or
        `None` when ffmpeg reports `n/a`, e.g. digital silence), plus
        `peak` (`0.0`-`1.0` linear peak derived from `max_volume_db`).
        Any decode failure yields all-`None` (plus `peak` 0.0) so one
        bad file leaves the surrounding list intact.
    """
    try:
        out = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "info",
                "-i",
                str(path),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "/dev/null",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return {"mean_volume_db": None, "max_volume_db": None, "peak": 0.0}
    stderr = out.stderr or ""
    mean_db: float | None = None
    max_db: float | None = None
    for raw_line in stderr.splitlines():
        line = raw_line.strip()
        if "mean_volume:" in line:
            val = line.split("mean_volume:")[-1].split("dB")[0].strip()
            try:
                mean_db = float(val)
            except ValueError:
                mean_db = None
        elif "max_volume:" in line:
            val = line.split("max_volume:")[-1].split("dB")[0].strip()
            try:
                max_db = float(val)
            except ValueError:
                max_db = None
    peak = round(10.0 ** (max_db / 20.0), 3) if max_db is not None else 0.0
    return {"mean_volume_db": mean_db, "max_volume_db": max_db, "peak": peak}
