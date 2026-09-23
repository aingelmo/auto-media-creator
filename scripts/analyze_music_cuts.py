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
HEADROOM_MIN_S = 8.0
HEADROOM_MAX_S = 15.0
HEADROOM_PRE_S = 3.0
HEADROOM_POST_S = 1.0
HEADROOM_GAIN_THRESH = 0.2  # best-in-range minus forced-15s counting as real


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


def headroom_for_track(track: Path, opens: list[float]) -> list[dict]:
    """Scan beat-quantized ends over 8-15s per open for closure headroom."""
    import librosa
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        wav = cut_music(track, Path(tmp) / "full.wav", 0.0, 1e6)
        y, sr = librosa.load(wav, sr=22050, mono=True)
    hop = 512
    fr = sr / hop
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    beats = [float(b) for b in beats]
    dur = len(y) / sr
    track_mean = float(np.mean(rms))
    eps = 1e-6

    def mean(t0: float, t1: float) -> tuple[float, float]:
        a = max(0, int(t0 * fr))
        b = min(len(rms), int(t1 * fr))
        cov = max(0.0, (min(t1, dur) - max(t0, 0.0)))
        if b <= a:
            return 0.0, cov
        return float(np.mean(rms[a:b])), cov

    def closure(e: float) -> float | None:
        pre, _ = mean(e - HEADROOM_PRE_S, e)
        post, cov = mean(e, e + HEADROOM_POST_S)
        if cov < 0.5:
            return None
        decay = max(0.0, (pre - post) / (pre + eps))
        return (pre / (track_mean + eps)) * decay

    rows = []
    for o in opens:
        ends = [b for b in beats if o + HEADROOM_MIN_S <= b <= o + HEADROOM_MAX_S]
        if len(ends) < 3:
            n = int((HEADROOM_MAX_S - HEADROOM_MIN_S) / 0.25)
            ends = sorted({o + HEADROOM_MIN_S + i * 0.25 for i in range(n + 1)})
        scored = [(e, closure(e)) for e in ends if e + 0.5 <= dur]
        scored = [(e, v) for e, v in scored if v is not None]
        forced = closure(o + HEADROOM_MAX_S)
        if not scored or forced is None:
            rows.append({"offset_s": o, "error": "no scorable ends"})
            continue
        best_e, best_v = max(scored, key=lambda p: p[1])
        rows.append(
            {
                "offset_s": o,
                "forced_15s": round(forced, 3),
                "best_end_s": round(best_e, 2),
                "best_dur_s": round(best_e - o, 2),
                "best_closure": round(best_v, 3),
                "gain": round(best_v - forced, 3),
            }
        )
    return rows


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
            opens = list(dict.fromkeys(c["offset_s"] for c in top15[:TOP_N]))
            try:
                row["headroom"] = headroom_for_track(path, opens)
            except Exception as e:
                row["headroom"] = {"error": str(e)}
        report_tracks.append(row)
        n15 = len((row["windows"].get("15.0") or {}).get("top", []))
        print(f"  {path.name} dur={row['duration_s']}s top15={n15}")
    (args.out / "results.json").write_text(json.dumps(report_tracks, indent=2))
    headroom_rows = []
    for r in report_tracks:
        top15 = (r["windows"].get("15.0") or {}).get("top") or []
        top1_off = top15[0]["offset_s"] if top15 else None
        headroom = r.get("headroom")
        if not isinstance(headroom, list):
            continue
        headroom_rows.extend(
            {"track": r["name"], "is_top1": h.get("offset_s") == top1_off, **h}
            for h in headroom
        )
    (args.out / "headroom.json").write_text(json.dumps(headroom_rows, indent=2))
    top1 = [h for h in headroom_rows if h["is_top1"] and "gain" in h]
    big = [h for h in top1 if h["gain"] >= HEADROOM_GAIN_THRESH]
    durs = [h["best_dur_s"] for h in headroom_rows if "best_dur_s" in h]
    print(
        f"headroom: {len(big)}/{len(top1)} top-1 opens gain >= "
        f"{HEADROOM_GAIN_THRESH} off-15s; "
        f"best_dur range: {min(durs):.1f}-{max(durs):.1f}s"
        if durs
        else "headroom: no scorable ends"
    )
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
