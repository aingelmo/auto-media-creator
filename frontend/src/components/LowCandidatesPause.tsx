import { useState } from "react";
import { api } from "../api";
import type { LowCandidates } from "../types";

export default function LowCandidatesPause({
  name,
  lowCandidates,
  onDone,
}: {
  name: string;
  lowCandidates: LowCandidates;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function submit(proceed: boolean, shorten: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("shorten", String(shorten));
    await api.confirm(name, form);
    onDone();
  }

  return (
    <div className="warning">
      <p>
        <strong>Warning:</strong> only {lowCandidates.real_sources} usable source clip(s) for{" "}
        {lowCandidates.slot_count} slots to fill. Some clips will repeat across slots, which can
        make the reel feel slow/static.
      </p>
      <p>
        Keep the current duration and accept the repeats, or shorten the reel to about{" "}
        {lowCandidates.suggested_duration_s}s so there are enough distinct clips to keep it dynamic.
      </p>
      <button type="button" disabled={busy} onClick={() => submit(true, false)}>
        Keep current duration
      </button>
      <button type="button" className="primary" disabled={busy} onClick={() => submit(true, true)}>
        Shorten to {lowCandidates.suggested_duration_s}s
      </button>
      <button type="button" disabled={busy} onClick={() => submit(false, false)}>
        Cancel run
      </button>
    </div>
  );
}
