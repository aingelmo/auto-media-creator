import type {
  Candidate,
  CandidatesPayload,
  Config,
  Edl,
  Hooks,
  KeyStatus,
  KeysStatus,
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

  getKeysStatus: () => fetch("/api/settings/keys").then((r) => asJson<KeysStatus>(r)),

  saveApiKey: (provider: string, api_key: string) =>
    fetch("/api/settings/keys", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, api_key }),
    }).then((r) => asJson<{ provider: string } & KeyStatus>(r)),

  deleteApiKey: (provider: string) =>
    fetch(`/api/settings/keys/${encodeURIComponent(provider)}`, {
      method: "DELETE",
    }).then((r) => asJson<{ provider: string } & KeyStatus>(r)),

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

/** Small bodies survive a Cloudflare tunnel with tiny host QUIC buffers;
 * the backend `CHUNK_SIZE` (8 MB) stays the per-request max — this is just
 * the frontend slice size, so every PUT stays far under both caps. */
export const UPLOAD_CHUNK_SIZE = 2 * 1024 * 1024;

/** Retries per chunk on network errors / 5xx / 429 / 409-resume. */
export const UPLOAD_CHUNK_RETRIES = 3;

/** Base delay for per-chunk exponential backoff (doubled per attempt). */
const UPLOAD_RETRY_BASE_MS = 800;

/** Aborts a chunk PUT that produces no response within this long: a
 * stalled stream (open TCP, zero bytes) never settles `fetch`, so
 * without a deadline one hung PUT freezes the whole sequential upload
 * with no error and no retry. 2 MB at even 100 KB/s takes ~20 s. */
const UPLOAD_CHUNK_TIMEOUT_MS = 60_000;

/** Deadline for the small control calls (init/status/complete). */
const UPLOAD_CONTROL_TIMEOUT_MS = 30_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Human byte count for upload notes (`35.6 MB`, `900 KB`). */
export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`;
  return `${bytes} B`;
}

/** `fetch` with a response deadline: aborts (DOMException AbortError,
 * surfaced here as a plain Error) when the server takes longer than
 * `timeoutMs` to answer. Callers treat it like any network error. */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s: ${url}`, { cause: err });
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Rejects login-page HTML with a session-expired error: when the
 * Authelia session dies mid-upload, chunk PUTs 303-redirect to the
 * login page, which `fetch` follows to a 200 HTML body. Without this
 * guard that 200 would parse as (empty) JSON and advance progress
 * without uploading a single byte. */
async function asUploadJson<T>(res: Response, url: string): Promise<T> {
  const ctype = res.headers.get("content-type") ?? "";
  if (!ctype.includes("application/json")) {
    throw new ApiError(
      401,
      `Upload session expired (got ${ctype || "unknown content"} from ${url}) — ` +
        "reload the page, log in again, and press Start to resume.",
    );
  }
  return asJson<T>(res);
}

/** Total payload above this uses the chunked path instead of one multipart POST. */
export const CHUNKED_THRESHOLD_TOTAL = 50 * 1024 * 1024;

/** Any single file above this forces the chunked path (Cloudflare caps at 100 MB). */
export const CHUNKED_THRESHOLD_SINGLE = 90 * 1024 * 1024;

export type UploadKind = "clip" | "music" | "logo";

export interface ChunkedUploadRef {
  upload_id: string;
  ref: string;
  filename: string;
  size: number;
}

export interface UploadStatus {
  upload_id: string;
  received: number;
  size: number;
  done: boolean;
  completed: boolean;
}

/** Authoritative resume point for an in-progress upload. */
export async function getUploadStatus(upload_id: string): Promise<UploadStatus> {
  const url = `/api/uploads/${encodeURIComponent(upload_id)}/status`;
  const res = await fetchWithTimeout(url, {}, UPLOAD_CONTROL_TIMEOUT_MS);
  return asUploadJson<UploadStatus>(res, url);
}

async function initChunkedUpload(
  file: File,
  kind: UploadKind,
  sessionName: string,
): Promise<string> {
  const url = "/api/uploads/init";
  let lastErr: unknown = null;
  for (let attempt = 0; attempt <= UPLOAD_CHUNK_RETRIES; attempt++) {
    if (attempt > 0) await sleep(UPLOAD_RETRY_BASE_MS * 2 ** (attempt - 1));
    try {
      const initRes = await fetchWithTimeout(
        url,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_name: sessionName,
            kind,
            filename: file.name,
            size: file.size,
          }),
        },
        UPLOAD_CONTROL_TIMEOUT_MS,
      );
      if (initRes.status >= 500 || initRes.status === 429) {
        lastErr = new ApiError(initRes.status, initRes.statusText);
        continue;
      }
      if (!initRes.ok) {
        const body = await initRes.json().catch(() => ({}));
        throw new ApiError(initRes.status, body.detail ?? initRes.statusText);
      }
      const { upload_id } = await asUploadJson<{ upload_id: string; chunk_size: number }>(
        initRes,
        url,
      );
      return upload_id;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      lastErr = err;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error("Upload init failed.");
}

async function completeChunkedUpload(upload_id: string): Promise<ChunkedUploadRef> {
  const url = `/api/uploads/${encodeURIComponent(upload_id)}/complete`;
  let lastErr: unknown = null;
  for (let attempt = 0; attempt <= UPLOAD_CHUNK_RETRIES; attempt++) {
    if (attempt > 0) await sleep(UPLOAD_RETRY_BASE_MS * 2 ** (attempt - 1));
    try {
      const doneRes = await fetchWithTimeout(url, { method: "POST" }, UPLOAD_CONTROL_TIMEOUT_MS);
      if (doneRes.status >= 500 || doneRes.status === 429) {
        lastErr = new ApiError(doneRes.status, doneRes.statusText);
        continue;
      }
      if (!doneRes.ok) {
        const body = await doneRes.json().catch(() => ({}));
        throw new ApiError(doneRes.status, body.detail ?? doneRes.statusText);
      }
      return await asUploadJson<ChunkedUploadRef>(doneRes, url);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      lastErr = err;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error("Upload complete failed.");
}

/**
 * Upload one file in 2 MB chunks so arbitrarily large sessions fit
 * through a 100 MB-capped reverse proxy (Cloudflare free/pro returns
 * 413 for bigger single bodies before the app is reached) and each
 * PUT stays small enough to move through a tunnel with tiny host
 * QUIC buffers. Every chunk carries a 60 s response deadline (a
 * stalled stream never settles `fetch`, so without it one hung PUT
 * would freeze the whole sequential upload with no error) and is
 * retried with exp backoff; a 409 offset-mismatch (or a network
 * error/timeout that may have landed server-side) refetches
 * `GET status` and continues from the authoritative `received`
 * count instead of failing. Login-page HTML (expired Authelia
 * session) is rejected instead of mistaken for a JSON success.
 * Passing a previous `opts.uploadId` for the same file resumes that
 * staging dir instead of orphaning it with a fresh init.
 */
export async function uploadFileChunked(
  file: File,
  kind: UploadKind,
  sessionName: string,
  onProgress?: (loadedBytes: number, totalBytes: number) => void,
  opts?: { uploadId?: string; onNote?: (note: string) => void },
): Promise<ChunkedUploadRef> {
  const note = (msg: string) => opts?.onNote?.(msg);
  let upload_id: string;
  let offset = 0;
  if (opts?.uploadId) {
    try {
      const st = await getUploadStatus(opts.uploadId);
      if (st.size === file.size) {
        if (st.completed || st.done) {
          note(`Already on server (${formatBytes(st.received)}), skipping re-upload.`);
          onProgress?.(st.received, file.size);
          return completeChunkedUpload(opts.uploadId);
        }
        note(`Resuming from ${formatBytes(st.received)} of ${formatBytes(st.size)}.`);
        upload_id = opts.uploadId;
        offset = st.received;
      } else {
        upload_id = await initChunkedUpload(file, kind, sessionName);
      }
    } catch {
      upload_id = await initChunkedUpload(file, kind, sessionName);
    }
  } else {
    upload_id = await initChunkedUpload(file, kind, sessionName);
  }
  onProgress?.(offset, file.size);
  // Informational sequence number only; the server treats `offset` as
  // authoritative so sub-max (2 MB) slices don't need 8 MB alignment.
  let seq = Math.floor(offset / UPLOAD_CHUNK_SIZE);
  while (offset < file.size) {
    const slice = file.slice(offset, offset + UPLOAD_CHUNK_SIZE);
    const params = new URLSearchParams({ index: String(seq), offset: String(offset) });
    const url = `/api/uploads/${encodeURIComponent(upload_id)}/chunk?${params}`;
    let putRes: Response | null = null;
    try {
      putRes = await fetchWithTimeout(
        url,
        {
          method: "PUT",
          headers: { "Content-Type": "application/octet-stream" },
          body: slice,
        },
        UPLOAD_CHUNK_TIMEOUT_MS,
      );
    } catch (err) {
      // Network error or chunk deadline: the chunk may still have
      // landed, so refetch the authoritative offset before retrying
      // instead of resending blind.
      note(
        err instanceof Error && err.message.startsWith("Request timed out")
          ? `Chunk ${seq} got no response for 60s — checking what landed…`
          : `Chunk ${seq} hit a network error — checking what landed…`,
      );
      let retried = false;
      for (let attempt = 0; attempt < UPLOAD_CHUNK_RETRIES; attempt++) {
        await sleep(UPLOAD_RETRY_BASE_MS * 2 ** attempt);
        try {
          const st = await getUploadStatus(upload_id);
          offset = st.received;
          seq = Math.floor(offset / UPLOAD_CHUNK_SIZE);
          onProgress?.(offset, file.size);
          if (offset >= file.size) return completeChunkedUpload(upload_id);
          retried = true;
          break;
        } catch {
          // status itself failed; keep backing off
        }
      }
      if (retried) continue;
      throw err instanceof Error ? err : new Error("Upload failed (network error).");
    }
    if (putRes.ok) {
      const body = await asUploadJson<{ received: number }>(putRes, url);
      offset = body.received;
      seq += 1;
      onProgress?.(offset, file.size);
      continue;
    }
    if (putRes.status === 409) {
      // Offset drift (e.g. a retried chunk that already landed):
      // continue from the server's count instead of failing.
      note(`Chunk ${seq} disagreed with the server — resuming from its count…`);
      let resumed = false;
      for (let attempt = 0; attempt <= UPLOAD_CHUNK_RETRIES; attempt++) {
        if (attempt > 0) await sleep(UPLOAD_RETRY_BASE_MS * 2 ** (attempt - 1));
        try {
          const st = await getUploadStatus(upload_id);
          if (st.size !== file.size) break;
          offset = st.received;
          seq = Math.floor(offset / UPLOAD_CHUNK_SIZE);
          onProgress?.(offset, file.size);
          if (offset >= file.size) return completeChunkedUpload(upload_id);
          resumed = true;
          break;
        } catch {
          // status failed; back off and retry the refetch
        }
      }
      if (resumed) continue;
      const body = await putRes.json().catch(() => ({}));
      throw new ApiError(putRes.status, body.detail ?? putRes.statusText);
    }
    if (putRes.status === 413) {
      const body = await putRes.json().catch(() => ({}));
      throw new ApiError(
        putRes.status,
        `Chunk rejected with 413 — the proxy caps single requests below 2 MB? (${body.detail ?? putRes.statusText})`,
      );
    }
    if (putRes.status >= 500 || putRes.status === 429) {
      note(`Server busy (${putRes.status}) on chunk ${seq} — backing off…`);
      let recovered = false;
      for (let attempt = 0; attempt < UPLOAD_CHUNK_RETRIES; attempt++) {
        await sleep(UPLOAD_RETRY_BASE_MS * 2 ** attempt);
        try {
          const st = await getUploadStatus(upload_id);
          offset = st.received;
          seq = Math.floor(offset / UPLOAD_CHUNK_SIZE);
          onProgress?.(offset, file.size);
          if (offset >= file.size) return completeChunkedUpload(upload_id);
          recovered = true;
          break;
        } catch {
          // status failed; keep backing off
        }
      }
      if (recovered) continue;
      const body = await putRes.json().catch(() => ({}));
      throw new ApiError(putRes.status, body.detail ?? putRes.statusText);
    }
    const body = await putRes.json().catch(() => ({}));
    throw new ApiError(putRes.status, body.detail ?? putRes.statusText);
  }
  return completeChunkedUpload(upload_id);
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
