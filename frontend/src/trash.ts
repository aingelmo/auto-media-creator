/**
 * Client-side slice of the bin: brand presets live in localStorage, so their
 * deleted state does too. The Trash page merges these rows with the server's
 * session/media items, and the header count reads both. The restore window
 * mirrors `web/trash.py` (`PURGE_AFTER_DAYS`).
 */
import { type BrandPreset, saveBrandPreset } from "./brandPresets";

const KEY = "edl-agent:trash";
const DAY_MS = 86_400_000;

/** Restore window for client-side items; matches the server's 30 days. */
export const CLIENT_PURGE_DAYS = 30;

export interface ClientTrashItem {
  id: string;
  kind: "preset";
  label: string;
  deletedAt: number;
  purgeAfter: number;
  preset: BrandPreset;
}

function isItem(value: unknown): value is ClientTrashItem {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<ClientTrashItem>;
  return (
    typeof item.id === "string" &&
    item.kind === "preset" &&
    typeof item.label === "string" &&
    typeof item.deletedAt === "number" &&
    typeof item.purgeAfter === "number" &&
    typeof item.preset === "object" &&
    item.preset !== null
  );
}

function write(items: ClientTrashItem[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    // Private-mode or full storage: a preset we cannot park is not worth
    // breaking the delete flow over.
  }
}

/** Read the stored rows, dropping anything past its purge window. */
function read(): ClientTrashItem[] {
  let raw: unknown;
  try {
    raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
  if (!Array.isArray(raw)) return [];
  const valid = raw.filter(isItem);
  const now = Date.now();
  const live = valid.filter((item) => item.purgeAfter > now);
  if (live.length !== valid.length) write(live);
  return live;
}

export function listClientTrash(): ClientTrashItem[] {
  return read();
}

export function countClientTrash(): number {
  return read().length;
}

/** Move one brand preset into the client bin. */
export function trashPreset(preset: BrandPreset): ClientTrashItem {
  const deletedAt = Date.now();
  const item: ClientTrashItem = {
    id: `preset-${deletedAt}-${Math.random().toString(16).slice(2, 8)}`,
    kind: "preset",
    label: preset.name,
    deletedAt,
    purgeAfter: deletedAt + CLIENT_PURGE_DAYS * DAY_MS,
    preset,
  };
  write([item, ...read()]);
  notifyTrashChanged();
  return item;
}

/** Put one trashed preset back into the saved-brand list. */
export function restorePreset(id: string): void {
  const item = read().find((entry) => entry.id === id);
  if (!item) return;
  saveBrandPreset(item.preset);
  write(read().filter((entry) => entry.id !== id));
  notifyTrashChanged();
}

/** Permanently drop one client bin row. */
export function purgeClientItem(id: string): void {
  write(read().filter((item) => item.id !== id));
  notifyTrashChanged();
}

/** Tell listeners (the header count) that the bin changed. */
export function notifyTrashChanged(): void {
  window.dispatchEvent(new Event("trash:changed"));
}

export function subscribeTrashChanged(listener: () => void): () => void {
  window.addEventListener("trash:changed", listener);
  return () => window.removeEventListener("trash:changed", listener);
}
