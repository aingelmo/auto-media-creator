import { useEffect, useRef, useState } from "react";
import { api, fileUrl } from "../api";

const DEBOUNCE_MS = 500;

function comboSrc(name: string, hookFlash: boolean, punchIn: boolean) {
  return fileUrl(name, `reel_preview_h${hookFlash ? 1 : 0}p${punchIn ? 1 : 0}.mp4`);
}

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

  // The src actually shown, and the one being cross-faded in. Only updated
  // once the backend confirms the corresponding file has finished
  // rendering (see submit()) -- the file doesn't exist yet the moment a
  // checkbox is toggled, so swapping the visible <video>'s src eagerly
  // would just show a broken/blank video until it appears.
  const [displayedSrc, setDisplayedSrc] = useState(comboSrc(name, hookFlash, punchIn));
  const [fading, setFading] = useState(false);

  // This is a required gate (render or cancel), not a dismissible panel, so
  // it opens as a modal dialog -- centered over the page regardless of
  // scroll position -- with Escape disabled; only the two buttons close it.
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  function swapTo(src: string) {
    if (src === displayedSrc) return;
    setFading(true);
    const preload = document.createElement("video");
    preload.muted = true;
    preload.src = src;
    preload.addEventListener("loadeddata", () => {
      setDisplayedSrc(src);
      setFading(false);
    });
  }

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function toggle(setter: (v: boolean) => void, checked: boolean) {
    setter(checked);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => void submit(true, true), DEBOUNCE_MS);
  }

  async function submit(proceed: boolean, previewAgain: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("punch_in", String(punchChecked));
    form.set("hook_flash", String(flashChecked));
    form.set("effects_preview_again", String(previewAgain));
    await api.confirm(name, form);
    if (!previewAgain) {
      // Proceeding to the final render or cancelling: hand off to the
      // parent, which switches to the running/result view.
      onDone();
      return;
    }
    lastSubmitted.current = { punchIn: punchChecked, hookFlash: flashChecked };
    // Re-rendering the preview in place: the backend briefly drops
    // awaiting_confirmation while it re-renders, then sets it again once the
    // new preview is ready. Poll status directly instead of calling onDone(),
    // so this panel stays mounted (with a loading indicator) the whole time
    // instead of the parent swapping it out for the "Running..." view and
    // back once the render finishes.
    for (;;) {
      const status = await api.getStatus(name);
      if (status.awaiting_confirmation && status.pause_kind === "effects_preview") break;
      if (status.done || status.error) {
        onDone();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    swapTo(comboSrc(name, lastSubmitted.current.hookFlash, lastSubmitted.current.punchIn));
    setBusy(false);
  }

  return (
    <dialog
      ref={dialogRef}
      className="stage-modal effects-preview-modal"
      onCancel={(e) => e.preventDefault()}
    >
      <p>
        <strong>Preview</strong> before the full-resolution render &mdash; this is preview quality,
        not final. Toggling an effect below updates the preview automatically.
      </p>
      <div className="effects-preview-body">
        <div className="reel-preview-frame">
          <video
            className="reel-player"
            style={{ filter: busy || fading ? "grayscale(1) brightness(0.6)" : "none" }}
            controls
            autoPlay
            loop
            muted
            src={displayedSrc}
          />
          {(busy || fading) && (
            <div className="reel-preview-overlay" aria-live="polite">
              <span>Updating preview&hellip;</span>
            </div>
          )}
        </div>
        <div className="effects-preview-controls">
          <label>
            <input
              type="checkbox"
              checked={flashChecked}
              onChange={(e) => toggle(setFlashChecked, e.target.checked)}
            />{" "}
            white flash on the hook beat
          </label>
          <label>
            <input
              type="checkbox"
              checked={punchChecked}
              onChange={(e) => toggle(setPunchChecked, e.target.checked)}
            />{" "}
            punch-in zoom on develop cuts
          </label>
          <div className="effects-preview-actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => submit(true, false)}
            >
              Render final video
            </button>
            <button type="button" disabled={busy} onClick={() => submit(false, false)}>
              Cancel run
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
