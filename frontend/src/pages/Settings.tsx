import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import type { KeysStatus } from "../types";

/**
 * API key settings: one password field per keyed provider. Keys are
 * persisted on the server (data volume) so reinstalls keep them;
 * environment-provided keys are shown as-is and can't be cleared here.
 */
export default function Settings() {
  const [status, setStatus] = useState<KeysStatus | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.getKeysStatus().then(setStatus).catch(setFailure);
  }, []);

  function setFailure(err: unknown) {
    setError(err instanceof Error ? err.message : "Request failed.");
  }

  async function save(provider: string) {
    setMessage("");
    setError("");
    try {
      await api.saveApiKey(provider, inputs[provider] ?? "");
      setInputs((prev) => ({ ...prev, [provider]: "" }));
      setStatus(await api.getKeysStatus());
      setMessage(`Key saved for ${provider}.`);
    } catch (err) {
      setFailure(err instanceof ApiError ? err.detail : err);
    }
  }

  async function clear(provider: string) {
    setMessage("");
    setError("");
    try {
      await api.deleteApiKey(provider);
      setStatus(await api.getKeysStatus());
      setMessage(`Saved key cleared for ${provider}.`);
    } catch (err) {
      setFailure(err instanceof ApiError ? err.detail : err);
    }
  }

  if (!status) return <p>Loading&hellip;</p>;

  return (
    <>
      <h2>Settings</h2>
      {message && <p className="status-done">{message}</p>}
      {error && (
        <p className="status-failed" role="alert">
          {error}
        </p>
      )}
      <p className="field-hint">
        Keys are stored on the server and survive reinstalls. A key set in the server&apos;s
        environment always wins and can&apos;t be cleared here.
      </p>
      {Object.entries(status).map(([provider, s]) => (
        <fieldset key={provider}>
          <legend>{provider}</legend>
          <p className="field-hint">
            {s.configured
              ? s.source === "env"
                ? "Provided by the server environment."
                : "Saved on the server."
              : "No key — runs with this provider fail at launch."}
          </p>
          <label htmlFor={`settings-key-${provider}`}>
            {s.configured && s.source === "server" ? "Replace key" : "API key"}
            <input
              id={`settings-key-${provider}`}
              type="password"
              autoComplete="off"
              value={inputs[provider] ?? ""}
              onChange={(e) => setInputs((prev) => ({ ...prev, [provider]: e.target.value }))}
              placeholder={s.configured ? "••••••••" : "sk-…"}
            />
          </label>
          <span className="name-row">
            <button type="button" className="primary" onClick={() => void save(provider)}>
              Save
            </button>
            {s.configured && s.source === "server" && (
              <button type="button" onClick={() => void clear(provider)}>
                Clear
              </button>
            )}
          </span>
        </fieldset>
      ))}
    </>
  );
}
