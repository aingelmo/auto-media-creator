import { useState } from "react";
import { api, fileUrl } from "../api";

function previewUrl(name: string, hookSlot: number): string {
  const seg = String(hookSlot).padStart(2, "0");
  return fileUrl(name, `hook_previews/none/seg_${seg}.mp4`);
}

export default function HookPicker({
  name,
  hookSlot,
  onDone,
}: {
  name: string;
  hookSlot: number;
  onDone: () => void;
}) {
  const [custom, setCustom] = useState("");
  const [variantB, setVariantB] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(proceed: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("hook_line", "");
    form.set("hook_custom", custom);
    form.set("hook_line_b", variantB);
    form.set("more", "false");
    await api.confirm(name, form);
    onDone();
  }

  return (
    <div className="warning">
      <p>
        <strong>Pick the hook line</strong> (or none, or write your own).
      </p>
      <div className="contact-sheet">
        <figure>
          <video autoPlay loop muted playsInline src={previewUrl(name, hookSlot)} />
          <figcaption>no text</figcaption>
        </figure>
      </div>
      <label>
        Hook text (optional; empty means no text)
        <input
          type="text"
          maxLength={40}
          placeholder="La barra despega del suelo"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
        />
      </label>
      <label>
        Variant B hook text (optional; renders a second reel, same clip)
        <input
          type="text"
          maxLength={40}
          placeholder="No variant B"
          value={variantB}
          onChange={(e) => setVariantB(e.target.value)}
        />
      </label>
      <button type="button" className="primary" disabled={busy} onClick={() => submit(true)}>
        Render with this hook
      </button>
      <button type="button" disabled={busy} onClick={() => submit(false)}>
        Cancel run
      </button>
    </div>
  );
}
