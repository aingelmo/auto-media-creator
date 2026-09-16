import { useState } from "react";
import { api, fileUrl } from "../api";
import type { MusicCandidate } from "../types";

function formatOffset(offsetS: number): string {
  const m = Math.floor(offsetS / 60);
  const s = Math.floor(offsetS % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
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
  const [offset, setOffset] = useState(candidates[0]?.offset_s ?? 0);
  const [busy, setBusy] = useState(false);

  async function submit(proceed: boolean, moreMusic: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("music_offset", String(offset));
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
      <div className="contact-sheet">
        {candidates.map((c, i) => (
          <figure key={c.path}>
            <audio controls preload="none" src={fileUrl(name, c.path)} />
            <figcaption>
              <label>
                <input
                  type="radio"
                  name="music_offset"
                  checked={offset === c.offset_s}
                  onChange={() => setOffset(c.offset_s)}
                />
                #{i + 1} &middot; {formatOffset(c.offset_s)}
                {c.score !== null ? ` · ${c.score.toFixed(2)}` : ""}
              </label>
            </figcaption>
          </figure>
        ))}
      </div>
      <button type="button" className="primary" disabled={busy} onClick={() => submit(true, false)}>
        Use this cut
      </button>
      <button type="button" disabled={busy} onClick={() => submit(true, true)}>
        Generate 3 more
      </button>
      <button type="button" disabled={busy} onClick={() => submit(false, false)}>
        Cancel run
      </button>
    </div>
  );
}
