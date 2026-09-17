import { getFormMemory } from "../formMemory";
import type { Provider } from "../types";

/**
 * Model picker: each supported provider only offers one model, so the
 * select shows the model name and submits its provider as a hidden
 * `provider` field plus the resolved `model`.
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

  return (
    <label htmlFor={`${idPrefix}-provider`}>
      Model
      <select id={`${idPrefix}-provider`} name="provider" defaultValue={initialProvider}>
        {providers.map((p) => (
          <option key={p} value={p}>
            {defaultModels[p] ?? p}
          </option>
        ))}
      </select>
    </label>
  );
}
