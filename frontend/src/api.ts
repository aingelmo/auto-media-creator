import type {
  Candidate,
  CandidatesPayload,
  Config,
  Edl,
  Hooks,
  LoudnessInfo,
  Manifest,
  MediaEntry,
  MediaLibrary,
  MusicTrackInfo,
  SelectionPayload,
  SessionDetail,
  SessionListEntry,
  StatusPayload,
  TimelinePayload,
  TrashItem,
  TrashPayload,
} from "./types";

/** Thrown for any non-2xx API response; `detail` is the FastAPI error body. */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listSessions: () => fetch("/api/sessions").then((r) => asJson<SessionListEntry[]>(r)),

  getConfig: () => fetch("/api/config").then((r) => asJson<Config>(r)),

  getMedia: () => fetch("/api/media").then((r) => asJson<MediaLibrary>(r)),

  deleteMedia: (ref: string) =>
    fetch(`/api/media?ref=${encodeURIComponent(ref)}`, { method: "DELETE" }).then((r) =>
      asJson<{ ref: string; item: TrashItem }>(r),
    ),

  /** Move a whole session to the trash (`DELETE /api/sessions/{name}`). */
  deleteSession: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) =>
      asJson<{ name: string; item: TrashItem }>(r),
    ),

  getTrash: () => fetch("/api/trash").then((r) => asJson<TrashPayload>(r)),

  restoreTrashItem: (id: string) =>
    fetch(`/api/trash/${encodeURIComponent(id)}/restore`, { method: "POST" }).then((r) =>
      asJson<{ item: TrashItem }>(r),
    ),

  purgeTrashItem: (id: string) =>
    fetch(`/api/trash/${encodeURIComponent(id)}`, { method: "DELETE" }).then((r) =>
      asJson<{ id: string }>(r),
    ),

  emptyTrash: () =>
    fetch("/api/trash", { method: "DELETE" }).then((r) => asJson<{ removed: number }>(r)),

  getPeaks: (ref: string, opts?: { buckets?: number; start_s?: number; end_s?: number }) => {
    const params = new URLSearchParams({ ref });
    if (opts?.buckets != null) params.set("buckets", String(opts.buckets));
    if (opts?.start_s != null) params.set("start_s", String(opts.start_s));
    if (opts?.end_s != null) params.set("end_s", String(opts.end_s));
    return fetch(`/api/media/peaks?${params.toString()}`).then((r) =>
      asJson<{ peaks: number[]; start_s: number | null; end_s: number | null }>(r),
    );
  },

  getLoudness: (ref: string) =>
    fetch(`/api/media/loudness?ref=${encodeURIComponent(ref)}`).then((r) =>
      asJson<LoudnessInfo>(r),
    ),

  getMusicTrack: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/music-track`).then((r) =>
      asJson<MusicTrackInfo>(r),
    ),

  getSession: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}`).then((r) => asJson<SessionDetail>(r)),

  getStatus: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/status`).then((r) => asJson<StatusPayload>(r)),

  getIngest: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/ingest`).then((r) => asJson<Manifest>(r)),

  getCandidates: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/candidates`).then((r) =>
      asJson<CandidatesPayload>(r),
    ),

  getSelection: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/selection`).then((r) =>
      asJson<SelectionPayload>(r),
    ),

  getHooks: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/hooks`).then((r) => asJson<Hooks>(r)),

  getPlanner: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/planner`).then((r) => asJson<Edl>(r)),

  startSession: (name: string, form: FormData) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/start`, {
      method: "POST",
      body: form,
    }).then((r) => asJson<{ name: string }>(r)),

  retrySession: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/retry`, { method: "POST" }).then((r) =>
      asJson<{ name: string }>(r),
    ),

  regenerateSession: (name: string, form: FormData) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/regenerate`, {
      method: "POST",
      body: form,
    }).then((r) => asJson<{ name: string }>(r)),

  confirm: (name: string, form: FormData) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/confirm`, {
      method: "POST",
      body: form,
    }).then((r) => asJson<{ name: string }>(r)),

  getTimeline: (name: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/timeline`).then((r) =>
      asJson<TimelinePayload>(r),
    ),

  reorderDevelops: (name: string, order: number[]) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/develop-order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order }),
    }).then((r) => asJson<TimelinePayload>(r)),

  setHookText: (name: string, hook_text: string) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/hook-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hook_text }),
    }).then((r) => asJson<TimelinePayload>(r)),

  setEffects: (name: string, hook_flash: boolean, punch_in: boolean) =>
    fetch(`/api/sessions/${encodeURIComponent(name)}/effects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hook_flash, punch_in }),
    }).then((r) => asJson<TimelinePayload>(r)),
};

/**
 * Submit the new-session form via XHR (not `fetch`) so upload progress can
 * be reported — `fetch` has no upload-progress event. Mirrors the original
 * `new.html` inline script.
 */
export function createSessionWithProgress(
  form: FormData,
  onProgress: (loadedBytes: number, totalBytes: number) => void,
): Promise<{ name: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/sessions");
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        let detail = xhr.statusText;
        try {
          detail = JSON.parse(xhr.responseText).detail ?? detail;
        } catch {
          // non-JSON error body; fall back to statusText
        }
        reject(new ApiError(xhr.status, detail));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Upload failed (network error).")));
    xhr.send(form);
  });
}

export function peakUrl(name: string, path: string): string {
  return `/sessions/${encodeURIComponent(name)}/files/${path}`;
}

export function reelUrl(name: string): string {
  return `/sessions/${encodeURIComponent(name)}/reel.mp4`;
}

export function fileUrl(name: string, path: string): string {
  return `/sessions/${encodeURIComponent(name)}/files/${path}`;
}

/** Playable preview URL for a library entry: the H.264 proxy when the
 * backend reports one, else the original file. Originals are often iPhone
 * HEVC 10-bit MOVs that desktop browsers can't decode (black tiles), while
 * proxies are plain H.264. Callers needing the original (audio, full
 * quality) must use fileUrl() directly. */
export function previewUrl(entry: MediaEntry): string {
  if (entry.kind === "video" && entry.proxy_path) {
    return fileUrl(entry.session, entry.proxy_path);
  }
  return fileUrl(entry.session, entry.path);
}

export type { Candidate };
