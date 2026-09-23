import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

const peaksCache = new Map<string, number[]>();

async function loadPeaks(
  ref: string,
  opts?: { buckets?: number; start_s?: number; end_s?: number },
): Promise<number[]> {
  const key =
    opts?.start_s != null && opts?.end_s != null
      ? `${ref}@${opts.start_s.toFixed(1)}-${opts.end_s.toFixed(1)}`
      : ref;
  const cached = peaksCache.get(key);
  if (cached) return cached;
  try {
    const { peaks } = await api.getPeaks(ref, opts);
    peaksCache.set(key, peaks);
    return peaks;
  } catch {
    peaksCache.set(key, []);
    return [];
  }
}

async function decodePeaks(url: string, buckets = 160): Promise<number[]> {
  const res = await fetch(url);
  const buf = await res.arrayBuffer();
  const Ctor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return [];
  const ctx = new Ctor();
  try {
    const decoded = await ctx.decodeAudioData(buf);
    const channel = decoded.getChannelData(0);
    if (channel.length === 0) return [];
    const peaks: number[] = [];
    for (let i = 0; i < buckets; i++) {
      const lo = Math.floor((channel.length * i) / buckets);
      const hi = Math.max(lo + 1, Math.floor((channel.length * (i + 1)) / buckets));
      let top = 0;
      for (let j = lo; j < hi; j += Math.max(1, Math.floor((hi - lo) / 64))) {
        const v = Math.abs(channel[j]);
        if (v > top) top = v;
      }
      peaks.push(Math.min(1, top));
    }
    return peaks;
  } catch {
    return [];
  } finally {
    void ctx.close().catch(() => {});
  }
}

function formatMMSS(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

/** Nice time-ruler step for a visible span, so ticks stay readable. */
function rulerStep(spanS: number): number {
  if (spanS <= 12) return 1;
  if (spanS <= 30) return 2;
  if (spanS <= 75) return 5;
  if (spanS <= 180) return 10;
  return 30;
}

const ZOOM_LEVELS = [1, 2, 4] as const;

function clampWindow(
  trackDur: number,
  offset: number,
  dur: number,
  minD: number,
  maxD: number,
): { offset: number; duration: number; clamped: boolean } {
  if (!(trackDur > 0)) return { offset, duration: dur, clamped: false };
  if (trackDur <= maxD) {
    const clamped = offset !== 0 || Math.abs(dur - trackDur) > 0.05;
    return { offset: 0, duration: trackDur, clamped };
  }
  let cDur = Math.min(maxD, Math.max(minD, dur));
  let cOff = Math.min(Math.max(0, offset), Math.max(0, trackDur - cDur));
  cOff = Math.round(cOff * 10) / 10;
  cDur = Math.round(cDur * 10) / 10;
  const clamped = Math.abs(cOff - offset) > 0.05 || Math.abs(cDur - dur) > 0.05;
  return { offset: cOff, duration: cDur, clamped };
}

export default function MusicWindowPicker({
  src,
  peaksRef,
  durationHint = null,
  initialOffset = 0,
  initialDuration = null,
  minDuration = 8,
  maxDuration = 15,
  onChange,
  label = "Music section",
}: {
  src: string;
  peaksRef?: string;
  durationHint?: number | null;
  initialOffset?: number;
  initialDuration?: number | null;
  minDuration?: number;
  maxDuration?: number;
  onChange?: (offsetS: number, durationS: number) => void;
  label?: string;
}) {
  const [peaks, setPeaks] = useState<number[]>(() =>
    peaksRef ? (peaksCache.get(peaksRef) ?? []) : (peaksCache.get(src) ?? []),
  );
  const [trackDur, setTrackDur] = useState(durationHint ?? 0);
  const [offset, setOffset] = useState(initialOffset);
  const [winDur, setWinDur] = useState(initialDuration ?? maxDuration);
  const [hint, setHint] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const [zoom, setZoom] = useState<number>(1);
  const [loop, setLoop] = useState(false);
  const [preRoll, setPreRoll] = useState(false);
  const [rangePeaks, setRangePeaks] = useState<{ s: number; e: number; peaks: number[] } | null>(
    null,
  );
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const waveRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    kind: "left" | "right" | "body";
    x0: number;
    o0: number;
    d0: number;
  } | null>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);
  // Live window bounds for the audio `timeupdate` listener, which is
  // registered once per element and would otherwise close over stale values.
  const winRef = useRef({ offset, winDur });
  winRef.current = { offset, winDur };
  // One-shot stop point for Shift-click/double-click auditions; null
  // during normal window playback (see the `timeupdate` listener).
  const auditionEndRef = useRef<number | null>(null);
  // Playback options for the same once-registered listener.
  const playOptsRef = useRef({ loop, preRoll });
  playOptsRef.current = { loop, preRoll };

  useEffect(() => {
    setOffset(initialOffset);
    setWinDur(initialDuration ?? maxDuration);
  }, [src, initialOffset, initialDuration, maxDuration]);

  const knownDurBase = trackDur > 0 ? trackDur : (durationHint ?? 0);

  // Visible window for the current zoom, centered on the selection and
  // clamped inside the track. Fit (1x) shows the whole track; 2x/4x
  // narrow the span so 0.1s edge drags land on distinct pixels.
  function zoomRange(): { s: number; e: number } {
    if (!(knownDurBase > 0) || zoom <= 1) return { s: 0, e: knownDurBase };
    const span = knownDurBase / zoom;
    const center = Math.min(
      Math.max(offset + winDur / 2, span / 2),
      Math.max(span / 2, knownDurBase - span / 2),
    );
    const s = Math.min(Math.max(0, center - span / 2), Math.max(0, knownDurBase - span));
    return { s: Math.round(s * 10) / 10, e: Math.round((s + span) * 10) / 10 };
  }

  const vis = zoomRange();

  // Zoomed windows fetch crisp server-side peaks for just the visible
  // range (see `GET /api/media/peaks` start_s/end_s). Debounced so a
  // drag across the overview resets the timer instead of fanning out
  // requests; the fetch fires 400ms after the selection settles. While
  // loading, draw() slices the full-track envelope as a placeholder.
  useEffect(() => {
    if (zoom <= 1 || !peaksRef || !(knownDurBase > 0)) {
      setRangePeaks(null);
      return;
    }
    const center = offset + winDur / 2;
    const span = knownDurBase / zoom;
    const s0 = Math.min(Math.max(0, center - span / 2), Math.max(0, knownDurBase - span));
    const s = Math.round(s0 * 2) / 2;
    const e = Math.round((s + span) * 2) / 2;
    const key = `${peaksRef}@${s.toFixed(1)}-${e.toFixed(1)}`;
    const cached = peaksCache.get(key);
    if (cached) {
      setRangePeaks({ s, e, peaks: cached });
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      void loadPeaks(peaksRef, { buckets: 320, start_s: s, end_s: e }).then((loaded) => {
        if (!cancelled && loaded.length > 0) setRangePeaks({ s, e, peaks: loaded });
      });
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [zoom, peaksRef, knownDurBase, offset, winDur]);

  useEffect(() => {
    let cancelled = false;
    const key = peaksRef ?? src;
    if (peaksCache.has(key)) {
      setPeaks(peaksCache.get(key) ?? []);
      return;
    }
    const job = peaksRef ? loadPeaks(peaksRef) : decodePeaks(src).catch(() => []);
    void job.then((loaded) => {
      peaksCache.set(key, loaded);
      if (!cancelled) setPeaks(loaded);
    });
    return () => {
      cancelled = true;
    };
  }, [peaksRef, src]);

  const apply = useCallback(
    (nextOff: number, nextDur: number) => {
      const durBase = trackDur > 0 ? trackDur : (durationHint ?? 0);
      if (durBase > 0) {
        const c = clampWindow(durBase, nextOff, nextDur, minDuration, maxDuration);
        setOffset(c.offset);
        setWinDur(c.duration);
        if (durBase <= maxDuration) {
          setHint(`track is ${formatMMSS(durBase)}, using 0:00–${formatMMSS(c.duration)}`);
        } else if (c.clamped) {
          setHint(`clamped to ${minDuration}–${maxDuration}s inside the track`);
        } else {
          setHint(null);
        }
        onChangeRef.current?.(c.offset, c.duration);
      } else {
        setOffset(Math.max(0, nextOff));
        setWinDur(nextDur);
        onChangeRef.current?.(Math.max(0, nextOff), nextDur);
      }
    },
    [trackDur, durationHint, minDuration, maxDuration],
  );

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    if (w === 0 || h === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    const styles = getComputedStyle(canvas);
    const signal = styles.getPropertyValue("--signal").trim() || "#35c2c8";
    const rule = styles.getPropertyValue("--rule").trim() || "#363636";
    const ink = styles.getPropertyValue("--ink").trim() || "#ffffff";
    // Envelope for the visible zoom window with the cut highlighted:
    // bars inside [offset, offset + winDur] paint in signal, the rest
    // stays dim so the user reads where the cut sits and drags its
    // limits directly. Zoomed ranges use crisp server peaks when loaded,
    // else slice the full-track envelope as a placeholder.
    const base = trackDur > 0 ? trackDur : (durationHint ?? 0);
    const viewS = zoom > 1 && base > 0 ? vis.s : 0;
    const viewE = zoom > 1 && base > 0 ? vis.e : base;
    const span = viewE - viewS;
    const useRange =
      zoom > 1 &&
      rangePeaks &&
      rangePeaks.peaks.length > 0 &&
      rangePeaks.s <= viewS &&
      rangePeaks.e >= viewE
        ? rangePeaks
        : null;
    const bars = useRange ? useRange.peaks : peaks;
    const barsS = useRange ? useRange.s : 0;
    const barsE = useRange ? useRange.e : base;
    if (bars.length === 0 || !(span > 0)) {
      ctx.fillStyle = rule;
      ctx.fillRect(0, h / 2 - 1, w, 2);
      return;
    }
    const selStart = offset;
    const selEnd = offset + winDur;
    const barW = w / bars.length;
    for (let i = 0; i < bars.length; i++) {
      const t = barsE > barsS ? barsS + ((i + 0.5) / bars.length) * (barsE - barsS) : 0;
      if (t < viewS || t > viewE) continue;
      const x = ((t - viewS) / span) * w;
      const inside = base <= 0 || (t >= selStart && t <= selEnd);
      ctx.fillStyle = inside ? signal : rule;
      ctx.globalAlpha = inside ? 1 : 0.45;
      const barH = Math.max(2, bars[i] * (h - 14));
      ctx.fillRect(x - barW / 2, h / 2 - barH / 2 - 5, Math.max(1, barW - 0.5), barH);
    }
    ctx.globalAlpha = 1;
    // Time ruler along the bottom: ticks adapt to the visible span.
    if (span > 0) {
      const step = rulerStep(span);
      ctx.fillStyle = rule;
      ctx.font = "10px monospace";
      ctx.textBaseline = "bottom";
      const firstTick = Math.ceil(viewS / step) * step;
      for (let t = firstTick; t <= viewE; t += step) {
        const x = ((t - viewS) / span) * w;
        ctx.globalAlpha = 0.8;
        ctx.fillRect(x, h - 12, 1, 6);
        ctx.globalAlpha = 0.9;
        ctx.fillText(formatMMSS(t), Math.min(x + 3, w - 30), h - 1);
      }
      ctx.globalAlpha = 1;
    }
    if (playhead != null && span > 0 && playhead >= viewS && playhead <= viewE) {
      const x = ((playhead - viewS) / span) * w;
      ctx.fillStyle = ink;
      ctx.fillRect(x - 1, 0, 2, h - 12);
    }
  }, [peaks, rangePeaks, vis.s, vis.e, zoom, offset, winDur, trackDur, durationHint, playhead]);

  useEffect(() => {
    requestAnimationFrame(() => draw());
  }, [draw, trackDur]);

  useEffect(() => {
    const parent = waveRef.current;
    if (!parent) return;
    const resize = new ResizeObserver(() => draw());
    resize.observe(parent);
    return () => resize.disconnect();
  }, [draw]);

  function ensureAudio(): HTMLAudioElement {
    let el = audioRef.current;
    if (!el) {
      el = new Audio(src);
      el.preload = "metadata";
      el.addEventListener("loadedmetadata", () => {
        const d = Number.isFinite(el!.duration) ? el!.duration : 0;
        setTrackDur(d);
      });
      el.addEventListener("timeupdate", () => {
        setPlayhead(el!.currentTime);
        // A Shift-click/double-click audition sets its own stop point
        // and always plays one-shot; window playback uses the cut end
        // with the Loop toggle.
        const auditionEnd = auditionEndRef.current;
        const end = auditionEnd ?? winRef.current.offset + winRef.current.winDur;
        if (el!.currentTime >= end) {
          if (auditionEnd != null) {
            auditionEndRef.current = null;
            el!.pause();
            setPlaying(false);
          } else if (playOptsRef.current.loop) {
            const backoff = playOptsRef.current.preRoll ? 1 : 0;
            el!.currentTime = Math.max(0, winRef.current.offset - backoff);
          } else {
            el!.pause();
            setPlaying(false);
          }
        }
      });
      el.addEventListener("pause", () => setPlaying(false));
      el.addEventListener("ended", () => setPlaying(false));
      audioRef.current = el;
    }
    if (el.src !== new URL(src, window.location.href).href) {
      el.src = src;
      el.load();
    }
    return el;
  }

  useEffect(() => {
    const el = ensureAudio();
    if (Number.isFinite(el.duration) && el.duration > 0) {
      setTrackDur(el.duration);
    } else if (durationHint) {
      setTrackDur(durationHint);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  function playWindow() {
    const el = ensureAudio();
    auditionEndRef.current = null;
    const backoff = preRoll ? 1 : 0;
    const start = Math.min(Math.max(0, offset - backoff), Math.max(0, (trackDur || 1e9) - 0.1));
    el.currentTime = start;
    setPlayhead(el.currentTime);
    void el
      .play()
      .then(() => setPlaying(true))
      .catch(() => setPlaying(false));
  }

  // Listen from an arbitrary point without moving the cut: plays until
  // the cut end when starting before it (to hear the entry in context),
  // else a 5s skim to the track end. Always one-shot.
  function auditionFrom(secs: number) {
    const el = ensureAudio();
    const dur = Number.isFinite(el.duration) && el.duration > 0 ? el.duration : trackDur;
    if (!(dur > 0)) return;
    const from = Math.min(Math.max(0, secs), Math.max(0, dur - 0.1));
    const cutEnd = offset + winDur;
    auditionEndRef.current = from < cutEnd ? cutEnd : Math.min(dur, from + 5);
    el.currentTime = from;
    setPlayhead(from);
    void el
      .play()
      .then(() => setPlaying(true))
      .catch(() => setPlaying(false));
  }

  function togglePlay() {
    if (playing) stop();
    else playWindow();
  }

  function stop() {
    auditionEndRef.current = null;
    audioRef.current?.pause();
    setPlaying(false);
  }

  function secsFromClientX(clientX: number): number {
    const wave = waveRef.current;
    if (!wave || !(trackDur > 0)) return 0;
    const r = wave.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    if (zoom > 1 && knownDurBase > 0) {
      const span = vis.e - vis.s;
      return vis.s + frac * span;
    }
    return frac * trackDur;
  }

  function onHandlePointerDown(kind: "left" | "right" | "body") {
    return (e: React.PointerEvent) => {
      // Shift-click anywhere on the wave auditions from that point
      // without moving the cut (see onWavePointerDown).
      if (e.shiftKey && trackDur > 0) {
        e.preventDefault();
        e.stopPropagation();
        auditionFrom(secsFromClientX(e.clientX));
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      dragRef.current = { kind, x0: e.clientX, o0: offset, d0: winDur };
    };
  }

  function onWavePointerDown(e: React.PointerEvent) {
    // Clicking the dimmed area jumps the cut there, then starts a body
    // drag so a click-drag repositions in one gesture. Clicks that begin
    // inside the highlighted cut are handled by the body grip above.
    // Shift-click (or double-click) instead auditions from that point
    // without moving anything.
    if ((e.target as HTMLElement).closest?.(".window-select")) return;
    if (!(trackDur > 0)) return;
    const secs = secsFromClientX(e.clientX);
    if (e.shiftKey || e.detail >= 2) {
      auditionFrom(secs);
      return;
    }
    const c = clampWindow(trackDur, secs - winDur / 2, winDur, minDuration, maxDuration);
    apply(c.offset, c.duration);
    dragRef.current = { kind: "body", x0: e.clientX, o0: c.offset, d0: c.duration };
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    const drag = dragRef.current;
    if (!drag || !(trackDur > 0)) return;
    const secs = secsFromClientX(e.clientX);
    const startSecs = secsFromClientX(drag.x0);
    const delta = secs - startSecs;
    if (drag.kind === "body") {
      apply(drag.o0 + delta, drag.d0);
    } else if (drag.kind === "left") {
      const end = drag.o0 + drag.d0;
      const nextOff = Math.min(Math.max(0, drag.o0 + delta), end - minDuration);
      apply(nextOff, end - nextOff);
    } else {
      apply(drag.o0, drag.d0 + delta);
    }
  }

  function endDrag() {
    dragRef.current = null;
  }

  function stepOffset(delta: number) {
    apply(offset + delta, winDur);
  }

  function stepDuration(delta: number) {
    apply(offset, winDur + delta);
  }

  function onNumberKey(e: React.KeyboardEvent<HTMLInputElement>, baseStep: number) {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const dir = e.key === "ArrowUp" ? 1 : -1;
      const step = e.shiftKey ? baseStep * 10 : baseStep;
      const target = (e.target as HTMLInputElement).dataset.field;
      if (target === "offset") stepOffset(dir * step);
      else stepDuration(dir * step);
    }
  }

  // Edge thumbs are native buttons (focusable, operable) with arrow-key
  // trimming at 0.1s (Shift for 1s); the whole-cut move stays pointer-only
  // on the body grip, with the Start steppers and number input as its
  // keyboard path.
  function onGripKey(kind: "left" | "right") {
    return (e: React.KeyboardEvent) => {
      const jump = e.shiftKey ? 1 : 0.1;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        e.stopPropagation();
        const dir = e.key === "ArrowRight" ? 1 : -1;
        if (kind === "left") {
          const end = offset + winDur;
          const nextOff = Math.min(Math.max(0, offset + dir * jump), end - minDuration);
          apply(nextOff, end - nextOff);
        } else {
          stepDuration(dir * jump);
        }
      } else if (e.key === "Home" && kind === "left") {
        e.preventDefault();
        e.stopPropagation();
        apply(0, offset + winDur);
      } else if (e.key === "End" && kind === "right") {
        e.preventDefault();
        e.stopPropagation();
        apply(offset, maxDuration);
      }
    };
  }

  const knownDur = trackDur > 0 ? trackDur : (durationHint ?? 0);
  // Selection overlay is positioned against the visible zoom window, not
  // the full track, so it stays put while zoomed in.
  const viewSpan = zoom > 1 && knownDur > 0 ? vis.e - vis.s : knownDur;
  const leftPct =
    knownDur > 0 && viewSpan > 0 ? ((offset - (zoom > 1 ? vis.s : 0)) / viewSpan) * 100 : 0;
  const widthPct = viewSpan > 0 ? (winDur / viewSpan) * 100 : 0;

  function onPickerKey(e: React.KeyboardEvent) {
    const target = e.target as HTMLElement;
    // Let inputs and edge thumbs keep their own arrow/space handling.
    if (target.closest?.("input, button")) return;
    if (e.code === "Space") {
      e.preventDefault();
      togglePlay();
    } else if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      const i = ZOOM_LEVELS.indexOf(zoom as (typeof ZOOM_LEVELS)[number]);
      if (i < ZOOM_LEVELS.length - 1) setZoom(ZOOM_LEVELS[i + 1]);
    } else if (e.key === "-") {
      e.preventDefault();
      const i = ZOOM_LEVELS.indexOf(zoom as (typeof ZOOM_LEVELS)[number]);
      if (i > 0) setZoom(ZOOM_LEVELS[i - 1]);
    } else if (e.key === "0") {
      e.preventDefault();
      setZoom(1);
    }
  }

  return (
    // Keyboard shortcuts (Space, +/-, 0) mirror the buttons below; inputs
    // and edge thumbs keep their own handlers (see onPickerKey).
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions
    <div className="music-window-picker" aria-label={label} onKeyDown={onPickerKey}>
      <div
        className="window-wave"
        ref={waveRef}
        title="Click to move the cut here · Shift-click or double-click to listen from here"
        onPointerDown={onWavePointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <canvas ref={canvasRef} aria-hidden="true" />
        {knownDur > 0 && (
          <div
            className="window-select"
            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
            onPointerDown={onHandlePointerDown("body")}
          >
            <button
              type="button"
              className="window-handle window-handle--left"
              aria-label={`Cut start ${formatMMSS(offset)}. Arrow keys nudge 0.1 seconds, Shift for 1 second.`}
              onPointerDown={onHandlePointerDown("left")}
              onKeyDown={onGripKey("left")}
            />
            <button
              type="button"
              className="window-handle window-handle--right"
              aria-label={`Cut end ${formatMMSS(offset + winDur)}, length ${winDur.toFixed(1)} seconds. Arrow keys nudge 0.1 seconds, Shift for 1 second.`}
              onPointerDown={onHandlePointerDown("right")}
              onKeyDown={onGripKey("right")}
            />
          </div>
        )}
      </div>
      <div className="window-fields">
        <fieldset className="window-zoom">
          <legend>Zoom</legend>
          {ZOOM_LEVELS.map((z) => (
            <button
              key={z}
              type="button"
              aria-pressed={zoom === z}
              title={z === 1 ? "Fit whole track (0)" : `Zoom ${z}x (−/+ to change)`}
              onClick={() => setZoom(z)}
            >
              {z === 1 ? "Fit" : `${z}x`}
            </button>
          ))}
        </fieldset>
        <label>
          Start (s)
          <span className="window-step-row">
            <button type="button" onClick={() => stepOffset(-5)} aria-label="Start minus 5 seconds">
              −5
            </button>
            <button type="button" onClick={() => stepOffset(-1)} aria-label="Start minus 1 second">
              −1
            </button>
            <input
              type="number"
              data-field="offset"
              min={0}
              max={knownDur > 0 ? Math.max(0, knownDur - winDur) : undefined}
              step={0.1}
              value={Math.round(offset * 10) / 10}
              onChange={(e) => apply(Number(e.target.value) || 0, winDur)}
              onKeyDown={(e) => onNumberKey(e, 0.1)}
              aria-label="Window start in seconds"
            />
            <button type="button" onClick={() => stepOffset(1)} aria-label="Start plus 1 second">
              +1
            </button>
            <button type="button" onClick={() => stepOffset(5)} aria-label="Start plus 5 seconds">
              +5
            </button>
          </span>
        </label>
        <label>
          Length (s)
          <span className="window-step-row">
            <button
              type="button"
              onClick={() => stepDuration(-5)}
              aria-label="Length minus 5 seconds"
            >
              −5
            </button>
            <button
              type="button"
              onClick={() => stepDuration(-1)}
              aria-label="Length minus 1 second"
            >
              −1
            </button>
            <input
              type="number"
              data-field="duration"
              min={minDuration}
              max={maxDuration}
              step={0.1}
              value={Math.round(winDur * 10) / 10}
              onChange={(e) => apply(offset, Number(e.target.value) || 0)}
              onKeyDown={(e) => onNumberKey(e, 0.1)}
              aria-label="Window length in seconds"
            />
            <button type="button" onClick={() => stepDuration(1)} aria-label="Length plus 1 second">
              +1
            </button>
            <button
              type="button"
              onClick={() => stepDuration(5)}
              aria-label="Length plus 5 seconds"
            >
              +5
            </button>
          </span>
        </label>
        <span className="window-readout" aria-live="polite">
          {formatMMSS(offset)}–{formatMMSS(offset + winDur)}
          {knownDur > 0 && ` of ${formatMMSS(knownDur)}`}
          {zoom > 1 && ` · ${zoom}x`}
        </span>
        <label className="window-check">
          <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop
        </label>
        <label className="window-check">
          <input type="checkbox" checked={preRoll} onChange={(e) => setPreRoll(e.target.checked)} />{" "}
          1s pre-roll
        </label>
        {playing ? (
          <button type="button" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="button" onClick={playWindow} title="Space">
            Play window
          </button>
        )}
      </div>
      {hint && <output className="field-hint">{hint}</output>}
    </div>
  );
}
