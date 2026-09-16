import { useState } from "react";
import { api, fileUrl } from "../api";
import type { Hooks } from "../types";

function previewUrl(name: string, key: string, flash: boolean, hookSlot: number): string {
  const dir = flash ? key : `${key}_noflash`;
  const seg = String(hookSlot).padStart(2, "0");
  return fileUrl(name, `hook_previews/${dir}/seg_${seg}.mp4`);
}

export default function HookPicker({
  name,
  hooks,
  hookSlot,
  onDone,
}: {
  name: string;
  hooks: Hooks;
  hookSlot: number;
  onDone: () => void;
}) {
  const [flash, setFlash] = useState(true);
  const [selected, setSelected] = useState(
    hooks.hooks.length === 0 ? "" : hooks.hooks[0]!.hook_line,
  );
  const [custom, setCustom] = useState("");
  const [variantB, setVariantB] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(proceed: boolean, more: boolean) {
    setBusy(true);
    const form = new FormData();
    form.set("proceed", String(proceed));
    form.set("hook_flash", String(flash));
    form.set("hook_line", selected);
    form.set("hook_custom", custom);
    form.set("hook_line_b", variantB);
    form.set("more", String(more));
    await api.confirm(name, form);
    onDone();
  }

  return (
    <div className="warning">
      <p>
        <strong>Pick the hook line</strong> (or none, or write your own).
      </p>
      <label>
        <input type="checkbox" checked={flash} onChange={(e) => setFlash(e.target.checked)} /> white
        flash on the hook beat
      </label>
      <div className="contact-sheet">
        <figure>
          <video autoPlay loop muted playsInline src={previewUrl(name, "none", flash, hookSlot)} />
          <figcaption>
            <label>
              <input
                type="radio"
                name="hook_line"
                checked={selected === "" && hooks.hooks.length === 0}
                onChange={() => setSelected("")}
              />{" "}
              no text
            </label>
          </figcaption>
        </figure>
        {hooks.hooks.map((h, i) => (
          <figure key={i}>
            <video
              autoPlay
              loop
              muted
              playsInline
              src={previewUrl(name, String(i), flash, hookSlot)}
            />
            <figcaption>
              <label>
                <input
                  type="radio"
                  name="hook_line"
                  checked={selected === h.hook_line}
                  onChange={() => setSelected(h.hook_line)}
                />{" "}
                [{h.angle}] {h.hook_line}
              </label>
            </figcaption>
          </figure>
        ))}
      </div>
      {hooks.evidence && hooks.evidence.length > 0 && (
        <p>
          evidence: {hooks.evidence.join(", ")} (source: {hooks.source})
        </p>
      )}
      {hooks.hooks.length === 0 && (
        <p>No valid lines from the model (reason: {hooks.rejected || "no evidence"}).</p>
      )}
      <label>
        Custom text (wins over the radio above if non-empty)
        <input
          type="text"
          maxLength={40}
          placeholder="La barra despega del suelo"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
        />
      </label>
      <label>
        Variant B hook line (optional; renders a second reel, same clip)
        <select value={variantB} onChange={(e) => setVariantB(e.target.value)}>
          <option value="">no variant B</option>
          {hooks.hooks.map((h, i) => (
            <option key={i} value={h.hook_line}>
              [{h.angle}] {h.hook_line}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="primary" disabled={busy} onClick={() => submit(true, false)}>
        Render with this hook
      </button>
      <button type="button" disabled={busy} onClick={() => submit(true, true)}>
        Regenerate
      </button>
      <button type="button" disabled={busy} onClick={() => submit(false, false)}>
        Cancel run
      </button>
    </div>
  );
}
