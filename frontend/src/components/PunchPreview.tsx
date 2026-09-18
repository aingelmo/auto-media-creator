import { useState } from "react";
import { api, fileUrl } from "../api";

export default function PunchPreview({
  name,
  punchIn,
  onDone,
}: {
  name: string;
  punchIn: boolean;
  onDone: () => void;
}) {
  const [checked, setChecked] = useState(punchIn);
  const [busy, setBusy] = useState(false);

  async function submit(proceed: boolean, punchPreviewAgain: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("punch_in", String(checked));
    form.set("punch_preview_again", String(punchPreviewAgain));
    await api.confirm(name, form);
    onDone();
  }

  return (
    <div className="warning">
      <p>
        <strong>Preview</strong> before the full-resolution render &mdash; this is preview quality,
        not final.
      </p>
      <video
        className="reel-player"
        controls
        autoPlay
        loop
        muted
        src={fileUrl(name, "reel_preview.mp4")}
      />
      <label>
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />{" "}
        punch-in zoom on develop cuts
      </label>
      <button type="button" className="primary" disabled={busy} onClick={() => submit(true, false)}>
        Render final video
      </button>
      <button type="button" disabled={busy} onClick={() => submit(true, true)}>
        Update preview
      </button>
      <button type="button" disabled={busy} onClick={() => submit(false, false)}>
        Cancel run
      </button>
    </div>
  );
}
