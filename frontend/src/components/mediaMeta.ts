import type { MediaEntry } from "../types";

// Stills hold for ~3s in the render, so they count as 3s of footage in
// coverage math. Unknown video durations count as 0, never as a guess.
export const IMAGE_FOOTAGE_S = 3;

// Browsers decode these natively; HEIC/HEIF stills get a placeholder tile.
const BROWSER_IMAGE_EXTS = [".jpg", ".jpeg", ".png"];

export function isDisplayableImage(filename: string): boolean {
  const i = filename.lastIndexOf(".");
  return BROWSER_IMAGE_EXTS.includes(i >= 0 ? filename.slice(i).toLowerCase() : "");
}

export function extOf(filename: string): string {
  const i = filename.lastIndexOf(".");
  return i >= 0 ? filename.slice(i).toLowerCase() : "";
}

export function formatSecs(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m${Math.round(s % 60)}s`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1e6) return `${(bytes / 1000).toFixed(0)} KB`;
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

export function clipSecs(c: MediaEntry): number {
  if (c.duration_s != null) return c.duration_s;
  return c.kind === "image" ? IMAGE_FOOTAGE_S : 0;
}

export function orientation(w: number | null, h: number | null): string {
  if (w == null || h == null) return "";
  if (w === h) return "square";
  return h > w ? "portrait" : "landscape";
}

export function dimsLabel(w: number | null, h: number | null): string {
  if (w == null || h == null) return "";
  return `${w}×${h} ${orientation(w, h)}`;
}

export function durationLabel(duration_s: number | null, kind: MediaEntry["kind"]): string {
  if (duration_s != null) return formatSecs(duration_s);
  return kind === "image" ? "still" : "—";
}
