import { useEffect, useState } from "react";

export interface CreateDraft {
  name: string;
  brief: string;
  theme: string;
  audience: string;
  handle: string;
  clipRefs: string[];
  musicRef: string;
  musicOffset: number | null;
  musicDuration: number | null;
}

const KEY = "edl-agent:new-draft";

/** Autosave/restore for the new-session flow. Text fields plus library refs
 * survive reload; fresh `File` uploads cannot (browser-owned) and must be
 * re-added — the banner says so. */
export function loadDraft(): CreateDraft | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CreateDraft>;
    if (typeof parsed !== "object" || parsed === null) return null;
    return {
      name: typeof parsed.name === "string" ? parsed.name : "",
      brief: typeof parsed.brief === "string" ? parsed.brief : "",
      theme: typeof parsed.theme === "string" ? parsed.theme : "",
      audience: typeof parsed.audience === "string" ? parsed.audience : "",
      handle: typeof parsed.handle === "string" ? parsed.handle : "",
      clipRefs: Array.isArray(parsed.clipRefs) ? parsed.clipRefs : [],
      musicRef: typeof parsed.musicRef === "string" ? parsed.musicRef : "",
      musicOffset: typeof parsed.musicOffset === "number" ? parsed.musicOffset : null,
      musicDuration: typeof parsed.musicDuration === "number" ? parsed.musicDuration : null,
    };
  } catch {
    return null;
  }
}

export function clearDraft(): void {
  localStorage.removeItem(KEY);
}

export function useCreateDraft(draft: CreateDraft): boolean {
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => {
      const empty =
        !draft.name &&
        !draft.brief &&
        draft.clipRefs.length === 0 &&
        !draft.musicRef &&
        !draft.handle;
      if (empty) return;
      localStorage.setItem(KEY, JSON.stringify(draft));
      setRestored(true);
    }, 300);
    return () => clearTimeout(t);
  }, [draft]);
  return restored;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

export function suggestName(): string {
  const d = new Date();
  const rand = Math.floor(Math.random() * 90 + 10);
  return `reel-${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}-${rand}`;
}
