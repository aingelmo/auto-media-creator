import type {
  Candidate,
  CandidatesPayload,
  Config,
  Edl,
  Hooks,
  Manifest,
  MediaLibrary,
  SelectionPayload,
  SessionDetail,
  SessionListEntry,
  StatusPayload,
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

export type { Candidate };
