import { useRef, useState } from "react";
import {
  type BrandPreset,
  dataUrlToFile,
  deleteBrandPreset,
  fileToDataUrl,
  getBrandPresets,
  saveBrandPreset,
} from "../brandPresets";
import { getFormMemory } from "../formMemory";
import { trashPreset } from "../trash";
import { useConfirm } from "./confirm";

/** Optional brand fieldset (logo/handle) shared by new/regenerate forms. */
export default function BrandFieldset({
  idPrefix,
  legend,
  collapsible,
}: {
  idPrefix: string;
  legend: string;
  collapsible?: boolean;
}) {
  const logoRef = useRef<HTMLInputElement>(null);
  const handleRef = useRef<HTMLInputElement>(null);
  const [presets, setPresets] = useState<BrandPreset[]>(getBrandPresets);
  const [selected, setSelected] = useState("");
  const confirm = useConfirm();

  async function applyPreset(name: string) {
    setSelected(name);
    const preset = presets.find((p) => p.name === name);
    if (!preset) return;
    if (handleRef.current) handleRef.current.value = preset.handle;
    if (logoRef.current) {
      if (preset.logoDataUrl) {
        const file = await dataUrlToFile(preset.logoDataUrl, `${preset.name}-logo.png`);
        const dt = new DataTransfer();
        dt.items.add(file);
        logoRef.current.files = dt.files;
      } else {
        logoRef.current.value = "";
      }
    }
  }

  async function saveCurrentAsPreset() {
    const name = prompt("Save this brand as:");
    if (!name) return;
    const logoFile = logoRef.current?.files?.[0];
    const preset: BrandPreset = {
      name,
      handle: handleRef.current?.value ?? "",
      logoDataUrl: logoFile ? await fileToDataUrl(logoFile) : null,
    };
    saveBrandPreset(preset);
    setPresets(getBrandPresets());
    setSelected(name);
  }

  async function removeSelectedPreset() {
    if (!selected) return;
    const preset = presets.find((p) => p.name === selected);
    const ok = await confirm({
      title: `Move "${selected}" to the trash?`,
      body: (
        <>
          <p>Removes it from your saved brands. Nothing is deleted.</p>
          <p className="confirm-note">Moves to Trash · restorable for 30 days.</p>
        </>
      ),
      confirmLabel: "Move to trash",
      tone: "danger",
    });
    if (!ok) return;
    deleteBrandPreset(selected);
    if (preset) trashPreset(preset);
    setPresets(getBrandPresets());
    setSelected("");
  }

  const fields = (
    <>
      {presets.length > 0 && (
        <label htmlFor={`${idPrefix}-brand-preset`}>
          Saved brand
          <select
            id={`${idPrefix}-brand-preset`}
            value={selected}
            onChange={(e) => applyPreset(e.target.value)}
          >
            <option value="">— choose —</option>
            {presets.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label htmlFor={`${idPrefix}-logo`}>
        Logo (PNG with alpha)
        <input id={`${idPrefix}-logo`} type="file" name="logo" accept="image/png" ref={logoRef} />
      </label>
      <label htmlFor={`${idPrefix}-handle`}>
        Handle
        <input
          id={`${idPrefix}-handle`}
          type="text"
          name="handle"
          maxLength={40}
          placeholder="@migimnasio"
          defaultValue={getFormMemory("handle")}
          ref={handleRef}
        />
      </label>
      <p>
        <button type="button" onClick={saveCurrentAsPreset}>
          Save as brand preset
        </button>
        {selected && (
          <button type="button" onClick={removeSelectedPreset}>
            Delete "{selected}"
          </button>
        )}
      </p>
    </>
  );

  if (collapsible) {
    return (
      <details>
        <summary>{legend}</summary>
        <div className="form-grid">{fields}</div>
      </details>
    );
  }

  return (
    <fieldset>
      <legend>{legend}</legend>
      {fields}
    </fieldset>
  );
}
