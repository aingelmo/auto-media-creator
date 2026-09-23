import { useState } from "react";
import { api, fileUrl } from "../api";
import type { MusicCandidate } from "../types";
import TrackPlayer from "./TrackPlayer";

function formatOffset(offsetS: number): string {
  const m = Math.floor(offsetS / 60);
  const s = Math.floor(offsetS % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDuration(durationS: number | null): string {
  if (durationS === null) return "";
  return ` · ${durationS.toFixed(1)}s`;
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
  const [busy, setBusy] = useState(false);

  async function submit(proceed: boolean, moreMusic: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("music_offset", String(candidates[selected]?.offset_s ?? 0));
    form.set("music_duration", String(candidates[selected]?.duration_s ?? 15));
    form.set("more_music", String(moreMusic));
    await api.confirm(name, form);
    onDone();
  }

  return (
    <div className="warning">
      <p>
        <strong>Pick the music cut</strong> &mdash; preview each candidate and choose the best
        moment, or generate more.
      </p>
      <div className="contact-sheet contact-sheet--music" role="radiogroup" aria-label="Music cuts">
        {candidates.map((c, i) => {
          const src = fileUrl(name, c.path);
          const isSelected = i === selected;
          const label = `Cut ${i + 1} at ${formatOffset(c.offset_s)}`;
          return (
            <figure key={c.path} className={isSelected ? "is-selected" : undefined}>
              <TrackPlayer src={src} label={label} computePeaks preload="metadata" />
              <figcaption>
                <label>
                  <input
                    type="radio"
                    name="music_cut"
                    checked={isSelected}
                    onChange={() => setSelected(i)}
                  />
                  #{i + 1} &middot; {formatOffset(c.offset_s)}
                  {formatDuration(c.duration_s)}
                  {c.score !== null ? ` · ${c.score.toFixed(2)}` : ""}
                </label>
              </figcaption>
            </figure>
          );
        })}
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
