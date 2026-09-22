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
) -> list[float]:
    """Decode a track and return its normalized amplitude envelope.

    Runs ffmpeg in-process to convert `path` to signed 16-bit mono PCM on
    stdout, then reduces it to one peak per bucket. Any container/codec
    ffmpeg reads is supported, including the `mp4`/`m4a` music uploads
    that a WAV-only reader would miss.

    Args:
        path: Audio (or audio-bearing container) file to decode.
        buckets: Number of equal-duration slices to reduce to one peak
            each. Buckets are contiguous and cover the whole track.
        sample_rate: Decode rate in Hz for the intermediate PCM.

    Returns:
        List of `buckets` floats in `0.0`-`1.0`, where `1.0` is full
        scale. An empty track (no decodable samples) yields `[]`.

    Raises:
        subprocess.CalledProcessError: If ffmpeg fails to read the file
            (unsupported codec, corrupt container, missing input).
        FileNotFoundError: If the `ffmpeg` binary is not on `PATH`.
    """
    out = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
    )
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
