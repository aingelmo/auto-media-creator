import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export default function VerificationPause({
  name,
  unverifiedSources,
  onDone,
}: {
  name: string;
  unverifiedSources: string[];
  onDone: () => void;
}) {
  const [excluded, setExcluded] = useState(() => new Set(unverifiedSources));
  const [busy, setBusy] = useState(false);

  async function submit(proceed: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    for (const src of excluded) form.append("exclude", src);
    await api.confirm(name, form);
    onDone();
  }

  return (
    <div className="warning is-error">
      <p>
        <strong>Warning:</strong> {unverifiedSources.length} video(s) failed proxy
        verification: their re-encoded working proxy's timeline doesn't line up with
        the original file's, so timestamps chosen later (candidate peaks, cut points)
        may land on the wrong frame when the final render pulls from the original for
        these clips.
      </p>
      <p>
        See <Link to={`/sessions/${name}/ingest`}>ingest details</Link> for the mismatch
        data.
      </p>
      {unverifiedSources.map((src) => (
        <label key={src}>
          <input
            type="checkbox"
            checked={excluded.has(src)}
            onChange={(e) =>
              setExcluded((prev) => {
                const next = new Set(prev);
                if (e.target.checked) next.add(src);
                else next.delete(src);
                return next;
              })
            }
          />{" "}
          exclude {src}
        </label>
      ))}
      <button type="button" className="primary" disabled={busy} onClick={() => submit(true)}>
        Continue with checked clips excluded
      </button>
      <button type="button" disabled={busy} onClick={() => submit(false)}>
        Cancel run
      </button>
    </div>
  );
}
