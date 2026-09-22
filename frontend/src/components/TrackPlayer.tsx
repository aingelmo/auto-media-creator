import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { formatSecs } from "./mediaMeta";

/** Audio element currently playing across all track rows: starting one
 *  track pauses any other, so the library never layers two tracks. */
let activeAudio: HTMLAudioElement | null = null;

/** Extracted peaks per media ref, shared across rows and remounts so
 *  expanding the library never refetches an envelope it already has. */
const peaksCache = new Map<string, number[]>();

/** Peaks from `GET /api/media/peaks`, memoized per ref. Failures cache an
 *  empty list so a broken track is requested once, not on every render. */
async function loadPeaks(ref: string): Promise<number[]> {
  const cached = peaksCache.get(ref);
  if (cached) return cached;
  try {
    const { peaks } = await api.getPeaks(ref);
    peaksCache.set(ref, peaks);
    return peaks;
  } catch {
    peaksCache.set(ref, []);
    return [];
  }
}

/** Compact track player: play/pause button, time readout, and a waveform
 *  that doubles as the seek control. The waveform fills the row's free
 *  width with the track's actual shape (intro, build, drop), replacing
 *  the native control bar so rows stay one dense console line.
 *
 *  With `peaksRef`, peaks load lazily when the row scrolls into view; the
 *  drawn waveform is a scrub surface over an invisible range input, which
 *  keeps keyboard seeking and screen-reader semantics native. */
export default function TrackPlayer({
  src,
  label,
  preload = "none",
  onDuration,
  peaksRef,
}: {
  src: string;
  label: string;
  preload?: "none" | "metadata";
  onDuration?: (secs: number | null) => void;
  peaksRef?: string;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const createdFor = useRef<string | null>(null);
  const onDurationRef = useRef(onDuration);
  useEffect(() => {
    onDurationRef.current = onDuration;
  }, [onDuration]);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const waveRef = useRef<HTMLSpanElement>(null);
  const pendingRatio = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [peaks, setPeaks] = useState<number[]>(
    () => (peaksRef ? peaksCache.get(peaksRef) : undefined) ?? [],
  );

  /** Element factory shared by all handlers, keyed on `src`: at most one
   *  element per row, recreated if the source ever changes. */
  const ensureAudio = useCallback((): HTMLAudioElement => {
    let el = audioRef.current;
    if (!el || createdFor.current !== src) {
      el?.pause();
      el = new Audio(src);
      el.preload = preload;
      const target = el;
      target.addEventListener("timeupdate", () => setCurrent(target.currentTime));
      target.addEventListener("loadedmetadata", () => {
        const d = Number.isFinite(target.duration) ? target.duration : null;
        setDuration(d ?? 0);
        onDurationRef.current?.(d);
        const ratio = pendingRatio.current;
        if (ratio != null && d != null && d > 0) {
          target.currentTime = ratio * d;
          setCurrent(target.currentTime);
          pendingRatio.current = null;
        }
      });
      target.addEventListener("pause", () => {
        setPlaying(false);
        if (activeAudio === target) activeAudio = null;
      });
      target.addEventListener("ended", () => {
        if (activeAudio === target) activeAudio = null;
      });
      audioRef.current = target;
      createdFor.current = src;
    }
    return el;
  }, [src, preload]);

  useEffect(
    () => () => {
      const el = audioRef.current;
      if (el) {
        el.pause();
        if (activeAudio === el) activeAudio = null;
      }
    },
    [],
  );

  // Eager element for metadata preload (upload coverage): durations
  // must resolve on mount, not lazily on first play.
  useEffect(() => {
    if (preload === "metadata") ensureAudio();
  }, [preload, ensureAudio]);

  // Fetch peaks only once the row is on screen: the dashboard renders up
  // to 200 rows, and decoding every envelope up front would stall paint.
  useEffect(() => {
    if (!peaksRef || peaksCache.has(peaksRef)) {
      if (peaksRef) setPeaks(peaksCache.get(peaksRef) ?? []);
      return;
    }
    const wave = waveRef.current;
    if (!wave) return;
    let cancelled = false;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      observer.disconnect();
      void loadPeaks(peaksRef).then((loaded) => {
        if (!cancelled) setPeaks(loaded);
      });
    });
    observer.observe(wave);
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [peaksRef]);

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
    const mid = h / 2;

    if (peaks.length === 0) {
      ctx.fillStyle = rule;
      ctx.fillRect(0, mid - 1, w, 2);
      return;
    }

    const progress = duration > 0 ? Math.min(1, current / duration) : 0;
    const barW = w / peaks.length;
    for (let i = 0; i < peaks.length; i++) {
      const played = (i + 0.5) / peaks.length <= progress;
      ctx.fillStyle = played ? signal : rule;
      const barH = Math.max(2, peaks[i] * (h - 2));
      ctx.fillRect(i * barW, mid - barH / 2, Math.max(1, barW - 0.5), barH);
    }
    if (progress > 0) {
      ctx.fillStyle = signal;
      ctx.fillRect(progress * w - 1, 0, 2, h);
    }
  }, [peaks, current, duration]);

  useEffect(() => {
    draw();
  }, [draw]);

  // The band is fluid (grid/row width) and the palette is themeable, so
  // redraw on either: a resize, or a `data-theme` flip on the document.
  useEffect(() => {
    const parent = waveRef.current;
    if (!parent) return;
    const resize = new ResizeObserver(() => draw());
    resize.observe(parent);
    const theme = new MutationObserver(() => draw());
    theme.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => {
      resize.disconnect();
      theme.disconnect();
    };
  }, [draw]);

  function toggle() {
    const el = ensureAudio();
    if (playing) {
      el.pause();
    } else {
      if (activeAudio && activeAudio !== el) activeAudio.pause();
      activeAudio = el;
      void el
        .play()
        .then(() => setPlaying(true))
        .catch(() => {
          setPlaying(false);
          if (activeAudio === el) activeAudio = null;
        });
    }
  }

  function seekTo(secs: number) {
    const el = ensureAudio();
    if (!Number.isFinite(el.duration) || el.duration <= 0) return;
    el.currentTime = Math.min(el.duration, Math.max(0, secs));
  }

  return (
    <div className="track-player">
      <button
        type="button"
        className="icon-button track-play"
        onClick={toggle}
        aria-label={playing ? `Pause ${label}` : `Play ${label}`}
        aria-pressed={playing}
      >
        {playing ? (
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M4.5 2.5v11M11.5 2.5v11"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
            />
          </svg>
        ) : (
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4.5 2.5l8 5.5-8 5.5z" fill="currentColor" />
          </svg>
        )}
      </button>
      <span className="track-time">
        {formatSecs(current)} / {duration > 0 ? formatSecs(duration) : "—"}
      </span>
      <span className="track-wave" ref={waveRef}>
        <canvas ref={canvasRef} aria-hidden="true" />
        <input
          type="range"
          className="track-seek"
          min={0}
          max={duration > 0 ? duration : 100}
          step={duration > 0 ? 0.1 : 1}
          value={duration > 0 ? Math.min(current, duration) : 0}
          onChange={(e) => {
            const raw = Number(e.target.value);
            if (duration > 0) {
              seekTo(raw);
              return;
            }
            // Metadata not resolved yet: remember the position as a ratio
            // and let `loadedmetadata` apply it once the duration lands, so
            // a click never feels dead before the track has loaded.
            pendingRatio.current = raw / 100;
            ensureAudio();
          }}
          aria-label={`Seek ${label}`}
        />
      </span>
    </div>
  );
}
