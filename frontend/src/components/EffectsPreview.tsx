import { useEffect, useRef, useState } from "react";
import { api, fileUrl } from "../api";

const DEBOUNCE_MS = 500;

export default function EffectsPreview({
  name,
  punchIn,
  hookFlash,
  onDone,
}: {
  name: string;
  punchIn: boolean;
  hookFlash: boolean;
  onDone: () => void;
}) {
  const [punchChecked, setPunchChecked] = useState(punchIn);
  const [flashChecked, setFlashChecked] = useState(hookFlash);
  const [busy, setBusy] = useState(false);
  // Tracks the combo last sent to the backend, so the debounce effect
  // below doesn't fire on mount (when checked state already matches it).
  const lastSubmitted = useRef({ punchIn, hookFlash });

  useEffect(() => {
    if (
      punchChecked === lastSubmitted.current.punchIn &&
      flashChecked === lastSubmitted.current.hookFlash
    ) {
      return;
    }
    const timer = setTimeout(() => {
      lastSubmitted.current = { punchIn: punchChecked, hookFlash: flashChecked };
      void submit(true, true);
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [punchChecked, flashChecked]);

  async function submit(proceed: boolean, previewAgain: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("punch_in", String(punchChecked));
    form.set("hook_flash", String(flashChecked));
    form.set("effects_preview_again", String(previewAgain));
    await api.confirm(name, form);
    onDone();
  }

  // Each hook_flash/punch_in combo is cached under its own suffixed file
  // (see stages/render.py's _combo_suffix), so this can be computed from
  // the checkboxes directly -- no round trip needed once it's cached.
  const previewSrc = fileUrl(
    name,
    `reel_preview_h${flashChecked ? 1 : 0}p${punchChecked ? 1 : 0}.mp4`,
  );

  return (
    <div className="warning">
      <p>
        <strong>Preview</strong> before the full-resolution render &mdash; this is preview quality,
        not final. Toggling an effect below updates the preview automatically.
      </p>
      <video className="reel-player" controls autoPlay loop muted src={previewSrc} />
      <label>
        <input
          type="checkbox"
          checked={flashChecked}
          onChange={(e) => setFlashChecked(e.target.checked)}
        />{" "}
        white flash on the hook beat
      </label>
      <label>
        <input
          type="checkbox"
          checked={punchChecked}
          onChange={(e) => setPunchChecked(e.target.checked)}
        />{" "}
        punch-in zoom on develop cuts
      </label>
      {busy && <p>Updating preview&hellip;</p>}
      <button type="button" className="primary" disabled={busy} onClick={() => submit(true, false)}>
        Render final video
      </button>
      <button type="button" disabled={busy} onClick={() => submit(false, false)}>
        Cancel run
      </button>
    </div>
  );
}
