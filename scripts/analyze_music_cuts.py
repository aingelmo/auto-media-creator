"""Batch-profile music open/close quality for calibration (report-only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from edl_agent.ingest import ffprobe, rank_highlights
from edl_agent.ingest.media import cut_music
from edl_agent.slots import slots_from_file

WINDOWS = [15.0, 11.7, 8.3, 5.0]
TOP_N = 5


def find_unique_tracks(var: Path) -> list[dict]:
    seen: dict[str, dict] = {}
    for p in sorted((var / "sessions").glob("*/music/*.*")):
        if "candidates" in str(p) or p.name == "track_cut.wav":
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        entry = seen.setdefault(
            h, {"sha": h, "path": str(p), "sessions": []}
        )
        entry["sessions"].append(p.parent.parent.name)
    return sorted(seen.values(), key=lambda e: e["path"])


def duration_s(path: Path) -> float:
    try:
        return float(ffprobe(path)["format"]["duration"])
    except Exception:
        return -1.0


def boundary_metrics(track: Path, offset: float, window: float) -> dict:
    import librosa
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        wav = cut_music(track, Path(tmp) / "full.wav", 0.0, 1e6)
        y, sr = librosa.load(wav, sr=22050, mono=True)
    hop = 512
    fr = sr / hop
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    beats = np.asarray(beats, dtype=float)

    def sl(t0: float, t1: float) -> np.ndarray:
        a = max(0, int(t0 * fr))
        b = min(len(rms), max(a + 1, int(t1 * fr)))
        return rms[a:b]

    win = sl(offset, offset + window)
    win_mean = float(np.mean(win)) if len(win) else 0.0
    eps = 1e-6
    open_mean = float(np.mean(sl(offset, offset + 0.5)))
    close_mean = float(np.mean(sl(offset + window - 0.5, offset + window)))
    pre = float(np.mean(sl(offset + window - 1.5, offset + window - 0.5)))
    end_slope = (close_mean - pre) / (win_mean + eps)
    d_open = float(np.min(np.abs(beats - offset))) if len(beats) else -1.0
    end_t = offset + window
    d_close = float(np.min(np.abs(beats - end_t))) if len(beats) else -1.0
    open_ratio = open_mean / (win_mean + eps)
    close_ratio = close_mean / (win_mean + eps)
    flags = []
    if open_ratio < 0.7:
        flags.append("weak_open")
    if close_ratio > 0.9 and end_slope > -0.05:
        flags.append("abrupt_close")
    if end_slope < -0.25:
        flags.append("fade_close")
    if close_ratio < 0.5:
        flags.append("weak_close")
    if d_close > 0.15:
        flags.append("offbeat_close")
    return {
        "open_ratio": round(open_ratio, 3),
        "close_ratio": round(close_ratio, 3),
        "end_slope": round(float(end_slope), 3),
        "d_open_beat": round(d_open, 3),
        "d_close_beat": round(d_close, 3),
        "flags": flags,
    }


def probe_slots(track: Path, offset: float, window: float) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        cut = cut_music(track, Path(tmp) / "cut.wav", offset, window)
        try:
            s = slots_from_file(str(cut))
        except Exception as e:
            return {"error": str(e)}
    slots = s["slots"]
    return {
        "tempo_bpm": round(s["tempo_bpm"], 1),
        "beats_confident": s["beats_confident"],
        "n_slots": len(slots),
        "close_len_f": slots[-1]["end_f"] - slots[-1]["start_f"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--var", type=Path, default=Path("var"))
    ap.add_argument("--out", type=Path, default=Path("var/music_calibration"))
    args = ap.parse_args()
    tracks = find_unique_tracks(args.var)
    print(f"unique tracks: {len(tracks)}")
    args.out.mkdir(parents=True, exist_ok=True)
    report_tracks = []
    for t in tracks:
        path = Path(t["path"])
        dur = duration_s(path)
        row: dict = {
            "name": path.name,
            "sha12": t["sha"][:12],
            "sessions": sorted(set(t["sessions"])),
            "duration_s": round(dur, 1),
            "windows": {},
        }
        for w in WINDOWS:
            if dur > 0 and dur <= w:
                continue
            try:
                ranked = rank_highlights(path, w)
            except Exception as e:
                row["windows"][str(w)] = {"error": str(e)}
                continue
            cands = []
            for c in ranked[:TOP_N]:
                m = boundary_metrics(path, c["offset_s"], w)
                cands.append({**c, **m})
            row["windows"][str(w)] = {"top": cands, "n_ranked": len(ranked)}
        # slots probe on top-1 15s cut
        top15 = (row["windows"].get("15.0") or {}).get("top") or []
        if top15:
            row["slots_probe_15s"] = probe_slots(
                path, top15[0]["offset_s"], 15.0
            )
        report_tracks.append(row)
        n15 = len((row["windows"].get("15.0") or {}).get("top", []))
        print(f"  {path.name} dur={row['duration_s']}s top15={n15}")
    (args.out / "results.json").write_text(json.dumps(report_tracks, indent=2))
    lines = ["# Music open/close calibration — diagnostic report", ""]
    lines.append(f"Tracks: {len(report_tracks)} (unique by sha256).")
    lines.append("Windows profiled: " + ", ".join(map(str, WINDOWS)) + "s.")
    lines.append("")
    flag_counts: dict[str, int] = {}
    for r in report_tracks:
        top = (r["windows"].get("15.0") or {}).get("top") or []
        if top:
            for f in top[0]["flags"]:
                flag_counts[f] = flag_counts.get(f, 0) + 1
    lines.append("Top-1 @15s flag counts: " + json.dumps(flag_counts))
    lines.append("")
    for r in report_tracks:
        lines.append(f"## {r['name']} ({r['duration_s']}s, {r['sha12']})")
        lines.append(f"Sessions: {', '.join(r['sessions'])}")
        if "slots_probe_15s" in r:
            lines.append(f"Slots probe: {json.dumps(r['slots_probe_15s'])}")
        for w, data in r["windows"].items():
            if "error" in data:
                lines.append(f"- {w}s: ERROR {data['error']}")
                continue
            lines.append(f"- {w}s (ranked {data['n_ranked']}):")
            lines.extend(
                f"  - off={c['offset_s']}s score={c['score']} "
                f"open={c['open_ratio']} close={c['close_ratio']} "
                f"slope={c['end_slope']} dClose={c['d_close_beat']}s "
                f"flags={c['flags']} reason={c.get('reason')}"
                for c in data["top"]
            )
        lines.append("")
    (args.out / "report.md").write_text("\n".join(lines))
    print(f"wrote {args.out / 'results.json'} and report.md")


if __name__ == "__main__":
    main()
