import { useState } from "react";
import { getFormMemory } from "../formMemory";
import type { Provider } from "../types";

/**
 * Provider dropdown + model text input pair, auto-filling the model from
 * `defaultModels` whenever the provider changes (mirrors the inline sync
 * script duplicated across new.html/session.html's three forms).
 */
export default function ProviderModelFields({
  providers,
  defaultModels,
  idPrefix,
}: {
  providers: Provider[];
  defaultModels: Record<string, string>;
  idPrefix: string;
}) {
  const rememberedProvider = getFormMemory("provider");
  const initialProvider =
    rememberedProvider && providers.includes(rememberedProvider as Provider)
      ? rememberedProvider
      : (providers[0] ?? "");
  const [provider, setProvider] = useState<string>(initialProvider);
  const [model, setModel] = useState(
    getFormMemory("model") || defaultModels[initialProvider] || "",
  );

  return (
    <>
      <label htmlFor={`${idPrefix}-provider`}>
        LLM provider
        <select
          id={`${idPrefix}-provider`}
          name="provider"
          value={provider}
          onChange={(e) => {
            const next = e.target.value;
            setProvider(next);
            setModel(defaultModels[next] ?? "");
          }}
        >
          {providers.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={`${idPrefix}-model`}>
        Model
        <input
          id={`${idPrefix}-model`}
          type="text"
          name="model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
      </label>
    </>
  );
}
