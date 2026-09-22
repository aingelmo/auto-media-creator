// Mirrors the JSON shapes served by src/edl_agent/web/app.py. Keep in sync
// with `_job_payload` and the route handlers there — this file has no
// runtime validation, it's a compile-time contract only.

export type StageName =
  | "ingest"
  | "candidates"
  | "selection"
  | "hooks"
  | "planner"
  | "render"
  | "checks";

export type StageStatus = "pending" | "running" | "done" | "failed";

export type PauseKind =
  | ""
  | "music_choice"
  | "verification"
  | "low_candidates"
  | "hook_choice"
  | "effects_preview";

export type Provider = "deepseek" | "ollama";

export interface Config {
  providers: Provider[];
  default_models: Record<string, string>;
}

export interface SessionListEntry {
  name: string;
  status: "new" | "running" | "done" | "failed";
  reel_exists: boolean;
  clip_count: number;
  music_name: string;
  total_cost_usd: number;
  mtime: number;
}

export interface HookCandidate {
  hook_line: string;
  angle: string;
}

export interface Hooks {
  hook_line?: string;
  hooks: HookCandidate[];
  dropped?: unknown;
  evidence?: string[];
  rejected?: string;
  source?: string;
}

export interface MusicCandidate {
  offset_s: number;
  path: string;
  score: number | null;
}

export interface MediaEntry {
  session: string;
  path: string;
  filename: string;
  size: number;
  mtime: number;
  duration_s: number | null;
  w: number | null;
  h: number | null;
  kind: "video" | "image" | "audio";
}

export interface MediaLibrary {
  clips: MediaEntry[];
  music: MediaEntry[];
}

/** Server-side trash entry: a session or media file parked in `var/trash`. */
export interface TrashItem {
  id: string;
  kind: "session" | "media";
  label: string;
  session: string;
  origin: string;
  /** Unix milliseconds. */
  deleted_at: number;
  /** Unix milliseconds; the entry auto-purges at this time. */
  purge_after: number;
  size_bytes: number;
  meta: Record<string, unknown>;
}

export interface TrashPayload {
  items: TrashItem[];
  retention_days: number;
}

export interface LowCandidates {
  real_sources?: number;
  slot_count?: number;
  suggested_duration_s?: number;
}

export interface StudioNotice {
  kind: string;
  message: string;
}

export interface JobPayload {
  stages: Record<StageName, StageStatus>;
  detail: Record<StageName, string>;
  done: boolean;
  error: string | null;
  awaiting_confirmation: boolean;
  pause_kind: PauseKind;
  check_results: string[];
  check_results_b: string[];
  unverified_sources: string[];
  low_candidates: LowCandidates;
  hooks: Hooks;
  hook_slot: number;
  hook_choice: string;
  music_candidates: MusicCandidate[];
  punch_in: boolean;
  hook_flash: boolean;
  notices: StudioNotice[];
}

export interface TimelineClip {
  slot: number;
  role: "hook" | "develop" | "close" | string;
  candidate_id: string;
  src: string;
  locked: boolean;
}

export interface TimelinePayload {
  clips: TimelineClip[];
  reel_exists: boolean;
  preview_exists: boolean;
  preview_path: string;
}

export interface HistoryEntry {
  ts: string;
  from_stage: string;
  provider: string;
  model: string;
  theme: string;
  audience: string;
  brief: string;
  hook_line: string;
  brand_updated: boolean;
}

export interface SessionDetail {
  name: string;
  job: JobPayload | null;
  reel_exists: boolean;
  reel_b_exists: boolean;
  stages: StageName[];
  stage_statuses: Record<StageName, StageStatus>;
  providers: Provider[];
  default_models: Record<string, string>;
  default_from_stage: string;
  history: HistoryEntry[];
  total_cost_usd: number;
}

export interface StatusPayload {
  stages: Record<StageName, StageStatus>;
  detail: Record<StageName, string>;
  done: boolean;
  error: string | null;
  awaiting_confirmation: boolean;
  pause_kind: PauseKind;
}

export interface ManifestSource {
  src: string;
  type: "video" | "image";
  w: number;
  h: number;
  rotation: number;
  duration_s?: number;
  hdr: string;
  proxy_verified: boolean;
}

export interface Manifest {
  sources: ManifestSource[];
  warnings?: string[];
  target: unknown;
  music?: unknown;
}

export interface Candidate {
  id: string;
  kind: string;
  src: string;
  score_cv: number;
  admits_slots: number[];
  peak_frames: string[];
  peak_urls: string[];
  [key: string]: unknown;
}

export interface CandidatesPayload {
  candidates: Candidate[];
}

export interface SelectionAttempt {
  attempt: number;
  status: string;
  usage: unknown;
  cost_usd: number;
  error?: string;
  system_prompt: string;
  user_prompt: string;
  output?: unknown;
}

export interface SelectionPayload {
  attempts: SelectionAttempt[];
}

export interface EdlClip {
  slot: number;
  role: string;
  src: string;
  in_s: number;
  out_s: number;
  timeline_start_f: number;
  timeline_end_f: number;
  layout: string;
  warnings: string[];
}

export interface Edl {
  target: unknown;
  clips: EdlClip[];
  audio: unknown;
}
