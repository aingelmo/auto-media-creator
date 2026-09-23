import type { Edl } from "../types";

/** One library clip's reuse across final EDLs (#8.5 output, `edl.json`). */
export interface ClipUsage {
  /** Distinct sessions whose final EDL uses this filename. */
  count: number;
  /** Session names using it, sorted alphabetically. */
  sessions: string[];
}

/** Usage keyed by library `filename` (see `buildUsage` for why). */
export type UsageMap = Record<string, ClipUsage>;

/** Basename of an EDL `src` (`inputs/clip.mp4` → `clip.mp4`). */
export function basenameOf(src: string): string {
  const i = src.lastIndexOf("/");
  return i >= 0 ? src.slice(i + 1) : src;
}

/** Fold per-session final EDLs into a filename-keyed usage map.
 *
 * Args:
 *   edls: One entry per session with a readable final EDL; each clip
 *     carries `src` (session-relative, e.g. `inputs/clip.mp4`).
 *
 * Returns:
 *   Usage keyed by basename. Keyed by basename — not `session/path` —
 *   because `/api/media` dedupes by `(filename, size)` and the EDL
 *   carries no size, while a picked clip is symlinked into the using
 *   session under the same filename. One EDL counts once per session
 *   even if the same `src` fills two slots. Sessions with no EDL (or
 *   an unreadable one) contribute nothing, so their absence reads as
 *   `unused`, never as an error.
 */
export function buildUsage(edls: Array<{ session: string; edl: Edl }>): UsageMap {
  const byFile = new Map<string, Set<string>>();
  for (const { session, edl } of edls) {
    for (const clip of edl.clips ?? []) {
      if (!clip?.src) continue;
      const file = basenameOf(clip.src);
      let set = byFile.get(file);
      if (!set) {
        set = new Set();
        byFile.set(file, set);
      }
      set.add(session);
    }
  }
  const out: UsageMap = {};
  for (const [file, set] of byFile) {
    const sessions = [...set].toSorted();
    out[file] = { count: sessions.length, sessions };
  }
  return out;
}

/** Fetch every session's final EDL and fold into a usage map.
 *
 * Args:
 *   sessions: Session names to query (typically from `listSessions`).
 *   getPlanner: Fetch returning the parsed `edl.json` for a session.
 *
 * Returns:
 *   Filename-keyed usage. Sessions whose EDL is missing/unreadable
 *   (404, failed job, corrupt JSON) are skipped, never thrown, so the
 *   Library always renders even when no final EDL exists yet.
 */
export async function fetchUsage(
  sessions: string[],
  getPlanner: (name: string) => Promise<Edl>,
): Promise<UsageMap> {
  const settled = await Promise.allSettled(
    sessions.map(async (session) => ({ session, edl: await getPlanner(session) })),
  );
  return buildUsage(settled.flatMap((r) => (r.status === "fulfilled" ? [r.value] : [])));
}
