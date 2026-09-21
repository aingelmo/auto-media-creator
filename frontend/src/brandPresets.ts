/** Saved brand presets (logo/handle) shared by new/regenerate forms. */
const KEY = "edl-agent:brand-presets";

export interface BrandPreset {
  name: string;
  handle: string;
  logoDataUrl: string | null;
}

export function getBrandPresets(): BrandPreset[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function saveBrandPreset(preset: BrandPreset): void {
  const next = getBrandPresets().filter((p) => p.name !== preset.name);
  next.push(preset);
  localStorage.setItem(KEY, JSON.stringify(next));
}

export function deleteBrandPreset(name: string): void {
  localStorage.setItem(KEY, JSON.stringify(getBrandPresets().filter((p) => p.name !== name)));
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result as string));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsDataURL(file);
  });
}

export async function dataUrlToFile(dataUrl: string, name: string): Promise<File> {
  const res = await fetch(dataUrl);
  const blob = await res.blob();
  return new File([blob], name, { type: blob.type });
}
