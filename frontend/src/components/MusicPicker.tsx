import { useCallback, useEffect, useState } from "react";
import { api, fileUrl } from "../api";
import type { LoudnessInfo, MediaEntry, MusicCandidate, MusicTrackInfo } from "../types";
import MusicWindowPicker from "./MusicWindowPicker";
import TrackPlayer from "./TrackPlayer";

const MIN_DUR = 8;
const MAX_DUR = 15;

function formatOffset(offsetS: number): string {
  const m = Math.floor(offsetS / 60);
  const s = Math.floor(offsetS % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDuration(durationS: number | null): string {
  if (durationS === null) return "";
  return ` · ${durationS.toFixed(1)}s`;
}

function scoreTooltip(c: MusicCandidate): string {
  const bits: string[] = [];
  bits.push(c.score !== null ? `Score ${c.score.toFixed(2)} of 1` : "Unranked fallback cut");
  if (c.reason) bits.push(c.reason);
  if (c.close_closure != null) bits.push(`phrase-close ${c.close_closure.toFixed(2)}`);
  if (c.d_close_beat_s != null) {
    bits.push(c.d_close_beat_s === 0 ? "ends on the beat" : `ends ${c.d_close_beat_s}s off beat`);
  }
  return bits.join(" · ");
}

function clampTrim(
  offset: number,
  duration: number,
  trackDur: number | null,
): { offset: number; duration: number; clamped: boolean } {
  let dur = Math.min(MAX_DUR, Math.max(MIN_DUR, duration));
  dur = Math.round(dur * 10) / 10;
  let off = Math.max(0, offset);
  if (trackDur != null && trackDur > 0 && trackDur > MAX_DUR) {
    off = Math.min(off, Math.max(0, trackDur - dur));
  }
  off = Math.round(off * 10) / 10;
  const clamped = Math.abs(off - offset) > 0.05 || Math.abs(dur - duration) > 0.05;
  return { offset: off, duration: dur, clamped };
}

export default function MusicPicker({
  name,
  candidates,
  onDone,
}: {
  name: string;
  candidates: MusicCandidate[];
  onDone: () => void;
}) {
  const [selected, setSelected] = useState(0);
  const [prevSelected, setPrevSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  // Per-candidate trim memory: switching cards no longer discards a
  // customized offset/duration. Keys are candidate indexes; entries
  // default to the candidate's own window until trimmed.
  const [trims, setTrims] = useState<Record<number, { offset: number; duration: number }>>({});
  const [trimHint, setTrimHint] = useState<string | null>(null);
  const [trackInfo, setTrackInfo] = useState<MusicTrackInfo | null>(null);
  const [libTrack, setLibTrack] = useState<MediaEntry | null>(null);
  const [trackFailed, setTrackFailed] = useState(false);
  const [trackLoading, setTrackLoading] = useState(true);
  const [loud, setLoud] = useState<LoudnessInfo | null>(null);

  const selCandidate = candidates[selected];
  const trimOffset = trims[selected]?.offset ?? selCandidate?.offset_s ?? 0;
  const trimDuration = trims[selected]?.duration ?? selCandidate?.duration_s ?? MAX_DUR;
  const customized =
    selCandidate != null &&
    (Math.abs(trimOffset - selCandidate.offset_s) >= 0.05 ||
      Math.abs(trimDuration - (selCandidate.duration_s ?? MAX_DUR)) >= 0.05);

  function pick(i: number) {
    setPrevSelected((prev) => (i === selected ? prev : selected));
    setSelected(i);
    setTrimHint(null);
  }

  const loadTrack = useCallback(async () => {
    setTrackFailed(false);
    setTrackLoading(true);
    try {
      const info = await api.getMusicTrack(name);
      setTrackInfo(info);
      setTrackLoading(false);
      return;
    } catch {
      // Fall through to the library lookup below.
    }
    try {
      const lib = await api.getMedia();
      const found = lib.music.find((m) => m.session === name) ?? null;
      if (found) {
        setLibTrack(found);
        setTrackLoading(false);
        return;
      }
      const byName = lib.music.find((m) => m.session === name);
      setLibTrack(byName ?? null);
      setTrackFailed(true);
    } catch {
      setTrackFailed(true);
    } finally {
      setTrackLoading(false);
    }
  }, [name]);

  useEffect(() => {
    let live = true;
    void (async () => {
      setTrackInfo(null);
      setLibTrack(null);
      setTrackFailed(false);
      setTrackLoading(true);
      try {
        const info = await api.getMusicTrack(name);
        if (live) setTrackInfo(info);
      } catch {
        try {
          const lib = await api.getMedia();
          if (!live) return;
          const found = lib.music.find((m) => m.session === name) ?? null;
          setLibTrack(found);
          if (!found) setTrackFailed(true);
        } catch {
          if (live) setTrackFailed(true);
        }
      } finally {
        if (live) setTrackLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [name]);

  const fullDur = trackInfo?.duration_s ?? libTrack?.duration_s ?? null;

  function applyTrim(nextOff: number, nextDur: number) {
    const c = clampTrim(nextOff, nextDur, fullDur);
    setTrims((prev) => ({
      ...prev,
      [selected]: { offset: c.offset, duration: c.duration },
    }));
    setTrimHint(c.clamped ? `clamped to ${MIN_DUR}–${MAX_DUR}s inside the track` : null);
  }

  // Clicking a card's position strip centers that card's trim there:
  // the strip is a miniature of the full track, so a click maps back
  // to seconds. Also selects the card.
  function jumpStripTo(i: number, frac: number) {
    if (!(fullDur && fullDur > 0)) return;
    const cand = candidates[i];
    if (!cand) return;
    const cutDur = trims[i]?.duration ?? cand.duration_s ?? MAX_DUR;
    const c = clampTrim(frac * fullDur - cutDur / 2, cutDur, fullDur);
    setTrims((prev) => ({ ...prev, [i]: { offset: c.offset, duration: c.duration } }));
    if (i !== selected) {
      setPrevSelected(selected);
      setSelected(i);
    }
    setTrimHint(c.clamped ? `clamped to ${MIN_DUR}–${MAX_DUR}s inside the track` : null);
  }

  async function submit(proceed: boolean, moreMusic: boolean) {
    setBusy(true);
    try {
      const form = new FormData();
      form.set("proceed", String(proceed));
      form.set("music_offset", String(trimOffset));
      form.set("music_duration", String(trimDuration));
      form.set("more_music", String(moreMusic));
      await api.confirm(name, form);
      onDone();
    } finally {
      setBusy(false);
    }
  }

  const trackUrl = trackInfo
    ? fileUrl(name, trackInfo.path)
    : libTrack
      ? fileUrl(libTrack.session, libTrack.path)
      : null;
  const trackRef = trackInfo
    ? trackInfo.peaks_ref
    : libTrack
      ? `${libTrack.session}/${libTrack.path}`
      : undefined;
  const trackName = trackInfo?.filename ?? libTrack?.filename ?? null;

  // Track-level loudness for the trim header: server-measured, cached
  // per file (see `GET /api/media/loudness`). Excerpt-level meters
  // would need per-cut analysis; the full-track mean/peak is what tells
  // the operator whether the bed will sit under dialogue or mask it.
  useEffect(() => {
    if (!trackRef) {
      setLoud(null);
      return;
    }
    let live = true;
    api
      .getLoudness(trackRef)
      .then((l) => {
        if (live) setLoud(l);
      })
      .catch(() => {
        if (live) setLoud(null);
      });
    return () => {
      live = false;
    };
  }, [trackRef]);

  const loudText =
    loud != null && (loud.mean_volume_db != null || loud.max_volume_db != null)
      ? [
          loud.mean_volume_db != null ? `mean ${loud.mean_volume_db.toFixed(1)} dB` : null,
          loud.max_volume_db != null ? `peak ${loud.max_volume_db.toFixed(1)} dB` : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;

  const fallbackSpan = Math.max(
    trimOffset + trimDuration,
    ...candidates.map((c) => c.offset_s + (c.duration_s ?? MAX_DUR)),
    1,
  );

  return (
    <div className="warning">
      <p>
        <strong>Pick the music cut</strong> &mdash; the cards play the cut excerpt only; the strip
        below each card shows where it sits in the full track (click it to move the cut there).
        Choose the best moment, place it on the full track, or generate more.
      </p>
      {prevSelected !== null && candidates[prevSelected] && prevSelected !== selected && (
        <p className="field-hint">
          Comparing #{prevSelected + 1} and #{selected + 1} — trims are kept per cut.{" "}
          <button type="button" onClick={() => pick(prevSelected)}>
            Back to #{prevSelected + 1}
          </button>
        </p>
      )}
      <div className="contact-sheet contact-sheet--music" role="radiogroup" aria-label="Music cuts">
        {candidates.map((c, i) => {
          const src = fileUrl(name, c.path);
          const isSelected = i === selected;
          const label = `Cut ${i + 1} at ${formatOffset(c.offset_s)}`;
          const cutDur = c.duration_s ?? MAX_DUR;
          const leftPct =
            fullDur && fullDur > 0
              ? Math.min(100, Math.max(0, (c.offset_s / fullDur) * 100))
              : (c.offset_s / fallbackSpan) * 100;
          const widthPct =
            fullDur && fullDur > 0
              ? Math.min(100 - leftPct, (cutDur / fullDur) * 100)
              : Math.min(100 - leftPct, (cutDur / fallbackSpan) * 100);
          return (
            <figure key={c.path} className={isSelected ? "is-selected" : undefined}>
              <TrackPlayer src={src} label={label} computePeaks preload="metadata" />
              {fullDur && fullDur > 0 ? (
                <button
                  type="button"
                  className="cut-context cut-context--button"
                  title={`${formatOffset(c.offset_s)} in ${formatOffset(fullDur)} — click to place the cut here`}
                  aria-label={`Place cut ${i + 1} at a point in the full track`}
                  onClick={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect();
                    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
                    jumpStripTo(i, frac);
                  }}
                >
                  <span
                    className="cut-context-fill"
                    aria-hidden="true"
                    style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                  />
                </button>
              ) : (
                <div
                  className="cut-context"
                  aria-hidden="true"
                  title={`${formatOffset(c.offset_s)} excerpt`}
                >
                  <div
                    className="cut-context-fill"
                    style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                  />
                </div>
              )}
              <figcaption>
                <label>
                  <input
                    type="radio"
                    name="music_cut"
                    checked={isSelected}
                    onChange={() => pick(i)}
                  />
                  #{i + 1} &middot; {formatOffset(c.offset_s)}
                  {formatDuration(c.duration_s)}
                  {fullDur && fullDur > 0 && (
                    <span className="cut-place"> · {formatOffset(fullDur)} track</span>
                  )}
                  {c.score !== null ? (
                    <span className="score-tip" title={scoreTooltip(c)}>
                      {` · ${c.score.toFixed(2)}`}
                    </span>
                  ) : (
                    ""
                  )}
                  {isSelected && customized && <span className="music-badge"> · customized</span>}
                </label>
              </figcaption>
            </figure>
          );
        })}
      </div>

      <div className="music-trim" aria-label="Trim selected cut">
        <p className="field-hint">
          Trim cut #{selected + 1} — drag the highlighted section on the full track
          {trackName ? (
            <>
              {" "}
              (<span className="music-track-name">{trackName}</span>
              {fullDur && fullDur > 0 && ` · ${formatOffset(fullDur)}`}
              {loudText && ` · ${loudText}`}){" "}
            </>
          ) : (
            " "
          )}
          or fine-tune below. Start and length stay inside {MIN_DUR}–{MAX_DUR}s.
        </p>
        {trackUrl ? (
          <MusicWindowPicker
            key={`${selected}-${trackUrl}-${candidates[selected]?.path ?? "cut"}`}
            src={trackUrl}
            peaksRef={trackRef}
            durationHint={fullDur}
            initialOffset={trimOffset}
            initialDuration={trimDuration}
            minDuration={MIN_DUR}
            maxDuration={MAX_DUR}
            onChange={(o, d) => applyTrim(o, d)}
            label={`Trim cut ${selected + 1} on the full track`}
          />
        ) : (
          <>
            <div
              className="cut-context cut-context--fallback"
              aria-hidden="true"
              title="Cut position among candidates"
            >
              <div
                className="cut-context-fill"
                style={{
                  left: `${(trimOffset / fallbackSpan) * 100}%`,
                  width: `${Math.min(100 - (trimOffset / fallbackSpan) * 100, (trimDuration / fallbackSpan) * 100)}%`,
                }}
              />
              {candidates.map((c) => (
                <span
                  key={c.path}
                  className="cut-context-tick"
                  style={{ left: `${(c.offset_s / fallbackSpan) * 100}%` }}
                />
              ))}
            </div>
            <div className="window-fields">
              <label>
                Start (s)
                <span className="window-step-row">
                  <button type="button" onClick={() => applyTrim(trimOffset - 5, trimDuration)}>
                    −5
                  </button>
                  <button type="button" onClick={() => applyTrim(trimOffset - 1, trimDuration)}>
                    −1
                  </button>
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={Math.round(trimOffset * 10) / 10}
                    onChange={(e) => applyTrim(Number(e.target.value) || 0, trimDuration)}
                    aria-label="Trimmed start in seconds"
                  />
                  <button type="button" onClick={() => applyTrim(trimOffset + 1, trimDuration)}>
                    +1
                  </button>
                  <button type="button" onClick={() => applyTrim(trimOffset + 5, trimDuration)}>
                    +5
                  </button>
                </span>
              </label>
              <label>
                Length (s)
                <span className="window-step-row">
                  <button type="button" onClick={() => applyTrim(trimOffset, trimDuration - 5)}>
                    −5
                  </button>
                  <button type="button" onClick={() => applyTrim(trimOffset, trimDuration - 1)}>
                    −1
                  </button>
                  <input
                    type="number"
                    min={MIN_DUR}
                    max={MAX_DUR}
                    step={0.1}
                    value={Math.round(trimDuration * 10) / 10}
                    onChange={(e) => applyTrim(trimOffset, Number(e.target.value) || 0)}
                    aria-label="Trimmed length in seconds"
                  />
                  <button type="button" onClick={() => applyTrim(trimOffset, trimDuration + 1)}>
                    +1
                  </button>
                  <button type="button" onClick={() => applyTrim(trimOffset, trimDuration + 5)}>
                    +5
                  </button>
                </span>
              </label>
              <span className="window-readout" aria-live="polite">
                {formatOffset(trimOffset)}–{formatOffset(trimOffset + trimDuration)}
              </span>
              {trackFailed && (
                <button type="button" onClick={() => void loadTrack()}>
                  Retry full-track preview
                </button>
              )}
            </div>
            {trackLoading ? (
              <p className="field-hint">Loading full-track preview…</p>
            ) : (
              <p className="field-hint">
                Full-track preview could not load — the bar above places this cut among the
                candidates; trim the numbers, or retry the preview.
              </p>
            )}
          </>
        )}
        {trimHint && <output className="field-hint">{trimHint}</output>}
      </div>

      <div className="music-cut-actions">
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => submit(true, false)}
        >
          Use this cut
        </button>
        <button type="button" disabled={busy} onClick={() => submit(true, true)}>
          Generate 3 more
        </button>
        <button type="button" disabled={busy} onClick={() => submit(false, false)}>
          Cancel run
        </button>
      </div>
    </div>
  );
}
