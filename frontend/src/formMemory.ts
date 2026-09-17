/** Remembers cross-run form fields (provider/theme/audience/brand) in
 * localStorage so New/Start/Regenerate forms don't need retyping every run.
 */
const KEY = "edl-agent:form-memory";
const REMEMBERED_FIELDS = ["provider", "theme", "audience", "handle", "line"] as const;
type RememberedField = (typeof REMEMBERED_FIELDS)[number];

function readAll(): Partial<Record<RememberedField, string>> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "{}");
  } catch {
    return {};
  }
}

export function getFormMemory(field: RememberedField): string | undefined {
  return readAll()[field];
}

export function saveFormMemory(formData: FormData): void {
  const next = readAll();
  for (const field of REMEMBERED_FIELDS) {
    const value = formData.get(field);
    if (typeof value === "string" && value !== "") next[field] = value;
  }
  localStorage.setItem(KEY, JSON.stringify(next));
}
