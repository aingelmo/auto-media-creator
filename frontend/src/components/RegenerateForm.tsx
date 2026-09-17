import { useState } from "react";
import { api } from "../api";
import { saveFormMemory } from "../formMemory";
import type { Config } from "../types";
import BrandFieldset from "./BrandFieldset";
import ProviderModelFields from "./ProviderModelFields";
import ThemeAudienceFields from "./ThemeAudienceFields";

const REGEN_STAGES = ["candidates", "selection", "planner", "hooks", "render"] as const;

// Provider/theme/audience/brief/hook fields only affect a regen that
// actually re-runs the LLM-driven selection/hooks stages; from planner on,
// those stages are resumed from disk untouched, so the fields are dead
// weight (kept mounted+hidden, not unmounted, so their values still submit
// with the form's remembered defaults intact).
const LLM_STAGES = new Set<string>(["candidates", "selection", "hooks"]);

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
  const [fromStage, setFromStage] = useState(defaultFromStage);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const formData = new FormData(e.currentTarget);
    saveFormMemory(formData);
    await api.regenerateSession(name, formData);
    onStarted();
  }

  return (
    <>
      <h3>Regenerate</h3>
      <form onSubmit={handleSubmit} className="form-grid">
        <label htmlFor="regen-from-stage">
          From stage
          <select
            id="regen-from-stage"
            name="from_stage"
            value={fromStage}
            onChange={(e) => setFromStage(e.target.value)}
          >
            {REGEN_STAGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <details hidden={!LLM_STAGES.has(fromStage)}>
          <summary>Model, theme, hook&hellip;</summary>
          <div className="form-grid">
            <ProviderModelFields
              providers={config.providers}
              defaultModels={config.default_models}
              idPrefix="regen"
            />
            <ThemeAudienceFields idPrefix="regen" />
            <label htmlFor="regen-hook">
              Hook text (manual, skips the LLM)
              <input
                id="regen-hook"
                type="text"
                name="hook_line"
                maxLength={40}
                placeholder="La barra despega del suelo"
              />
            </label>
          </div>
        </details>
        <BrandFieldset
          idPrefix="regen"
          legend="Brand (optional; new logo replaces the session's, applies from planner on)"
          collapsible
        />
        <button type="submit" className="primary" disabled={busy}>
          Regenerate from this stage
        </button>
      </form>
    </>
  );
}
