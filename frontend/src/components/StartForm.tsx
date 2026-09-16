import { useState } from "react";
import { api } from "../api";
import type { Config } from "../types";
import ProviderModelFields from "./ProviderModelFields";
import ThemeAudienceFields from "./ThemeAudienceFields";

/** Launches a session whose inputs exist but never got a job (server restarted before any stage finished). */
export default function StartForm({
  name,
  config,
  onStarted,
}: {
  name: string;
  config: Config;
  onStarted: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    await api.startSession(name, new FormData(e.currentTarget));
    onStarted();
  }

  return (
    <>
      <p>No run found for this session (server restarted before any stage finished).</p>
      <form onSubmit={handleSubmit}>
        <ProviderModelFields
          providers={config.providers}
          defaultModels={config.default_models}
          idPrefix="start"
        />
        <ThemeAudienceFields idPrefix="start" />
        <button type="submit" className="primary" disabled={busy}>
          Start / resume run
        </button>
      </form>
    </>
  );
}
