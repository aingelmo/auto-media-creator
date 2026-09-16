import { useState } from "react";
import { api } from "../api";
import type { Config } from "../types";
import BrandFieldset from "./BrandFieldset";
import ProviderModelFields from "./ProviderModelFields";
import ThemeAudienceFields from "./ThemeAudienceFields";

const REGEN_STAGES = ["candidates", "selection", "hooks", "planner", "render"] as const;

export default function RegenerateForm({
  name,
  config,
  defaultFromStage,
  onStarted,
}: {
  name: string;
  config: Config;
  defaultFromStage: string;
  onStarted: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    await api.regenerateSession(name, new FormData(e.currentTarget));
    onStarted();
  }

  return (
    <>
      <h3>Regenerate</h3>
      <form onSubmit={handleSubmit}>
        <label htmlFor="regen-from-stage">
          From stage
          <select id="regen-from-stage" name="from_stage" defaultValue={defaultFromStage}>
            {REGEN_STAGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <ProviderModelFields
          providers={config.providers}
          defaultModels={config.default_models}
          idPrefix="regen"
        />
        <ThemeAudienceFields idPrefix="regen" />
        <BrandFieldset
          idPrefix="regen"
          legend="Brand (optional; new logo replaces the session's, applies from planner on)"
        />
        <button type="submit" className="primary" disabled={busy}>
          Regenerate from this stage
        </button>
      </form>
    </>
  );
}
