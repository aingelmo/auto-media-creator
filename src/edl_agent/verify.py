"""Capa 1 - Verificacion temporal proxy <-> original (#4.4).

En Capa 1 (antes de que exista kp_speed, calculado en Capa 2) los instantes de
prueba son el fallback de percentiles {10%, 50%, 90%} de la duracion. Cuando
Capa 2 aporte los picos de kp_speed, se pasan como `extra_instants_s` y tienen
prioridad (se completa con percentiles hasta 5 si hacen falta).
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

FRAME_OFFSETS = (-2, -1, 0, 1, 2)  # frames de proxy a comparar, a 30 fps
D0_MAX = 6  # umbral [validar margen] segun #4.4


@dataclass
class InstantResult:
    t_s: float
    distances: dict[int, int]  # offset -> hamming distance
    ok: bool


def pick_instants(duration_s: float, extra_instants_s: list[float] | None = None) -> list[float]:
    extra = sorted(set(extra_instants_s or []))
    percentiles = [duration_s * p for p in (0.10, 0.50, 0.90)]
    instants = list(extra)
    for p in percentiles:
        if len(instants) >= 5:
            break
        if all(abs(p - i) >= 2.0 for i in instants):
            instants.append(p)
    return instants[:5]


def _extract_frame(cmd_extra: list[str], src: str, t: float, out_path: Path) -> None:
    cmd = ["ffmpeg", "-y", "-ss", str(max(t, 0.0)), "-i", src, "-frames:v", "1", *cmd_extra, str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _phash(path: Path) -> imagehash.ImageHash:
    with Image.open(path) as im:
        return imagehash.phash(im)


def verify_source(
    original: str,
    proxy: str,
    tonemap_chain: str = "",
    extra_instants_s: list[float] | None = None,
    proxy_fps: int = 30,
) -> tuple[bool, list[InstantResult]]:
    from .ingest import ffprobe, _video_stream  # local import: evita ciclo en tests unitarios

    duration_s = float(_video_stream(ffprobe(Path(proxy)))["duration"])
    instants = pick_instants(duration_s, extra_instants_s)

    orig_vf = f"{tonemap_chain},scale=256:-2" if tonemap_chain else "scale=256:-2"

    results: list[InstantResult] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for t in instants:
            orig_png = tmp_path / f"orig_{t:.3f}.png"
            _extract_frame(["-vf", orig_vf], original, t, orig_png)
            orig_hash = _phash(orig_png)

            distances: dict[int, int] = {}
            for k in FRAME_OFFSETS:
                proxy_png = tmp_path / f"proxy_{t:.3f}_{k}.png"
                _extract_frame(["-vf", "scale=256:-2"], proxy, t + k / proxy_fps, proxy_png)
                distances[k] = orig_hash - _phash(proxy_png)

            d0 = distances[0]
            best = min(distances.values())
            # #4.4 + riesgo #13: argmin_k==0 admite empates (movimiento lento);
            # solo exige que 0 alcance el minimo y este por debajo del umbral.
            ok = d0 == best and d0 <= D0_MAX
            results.append(InstantResult(t_s=t, distances=distances, ok=ok))

    return all(r.ok for r in results), results
