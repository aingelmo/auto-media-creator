import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { KeysStatus } from "../types";

/**
 * Missing-key hint for the new-session form: lists keyed providers with
 * no key configured, pointing at Settings. `null` while loading or when
 * every provider is ready (e.g. ollama needs no key at all).
 */
export default function ApiKeyHint() {
  const [status, setStatus] = useState<KeysStatus | null>(null);

  useEffect(() => {
    api
      .getKeysStatus()
      .then(setStatus)
      .catch(() => null);
  }, []);

  if (!status) return null;
  const missing = Object.keys(status).filter((p) => !status[p]?.configured);
  if (missing.length === 0) return null;
  return (
    <p className="field-hint">
      No API key for {missing.join(", ")} — add one in <Link to="/settings">Settings</Link> or the
      run fails at launch.
    </p>
  );
}
