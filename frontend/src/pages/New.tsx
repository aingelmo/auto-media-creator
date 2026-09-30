import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  CHUNKED_THRESHOLD_SINGLE,
  CHUNKED_THRESHOLD_TOTAL,
  createSessionWithProgress,
  uploadFileChunked,
  type ChunkedUploadRef,
} from "../api";
import { api } from "../api";
import { getFormMemory, saveFormMemory } from "../formMemory";
import { clearDraft, loadDraft, suggestName, useCreateDraft } from "../useCreateDraft";
import type { Config } from "../types";
import BrandFieldset from "../components/BrandFieldset";
import { useConfirm } from "../components/confirm";
import CreateSummary, { type CreateStats } from "../components/CreateSummary";
import DescribeFields from "../components/DescribeFields";
import ApiKeyHint from "../components/ApiKeyHint";
import FormSteps from "../components/FormSteps";
import MediaLibraryPicker from "../components/MediaLibraryPicker";
import ProviderModelFields from "../components/ProviderModelFields";

const STEPS = ["Media", "Describe", "Style & launch"] as const;
const NAME_RE = /^[A-Za-z0-9_-]+$/;

function formatMb(bytes: number) {
  return (bytes / 1e6).toFixed(1);
}

function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

/** Live chunked-upload state; rendered every second so a pause shows
 * "waiting Ns" (working, slow) instead of a frozen percentage. */
interface UploadProgress {
  done: number;
  total: number;
  fileName: string;
  fileIdx: number;
  fileCount: number;
  rateBps: number | null;
  lastActivity: number;
  note: string;
}

function formatProgress(p: UploadProgress, nowMs: number): string {
  const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 100;
  const rate = p.rateBps != null && p.rateBps > 0 ? ` · ${(p.rateBps / 1e6).toFixed(1)} MB/s` : "";
  const eta =
    p.rateBps != null && p.rateBps > 0 && p.done < p.total
      ? ` · ETA ${formatEta((p.total - p.done) / p.rateBps)}`
      : "";
  const agoS = Math.max(0, Math.round((nowMs - p.lastActivity) / 1000));
  const wait = agoS >= 5 ? ` · waiting ${agoS}s` : "";
  return (
    `Uploading ${p.fileIdx + 1}/${p.fileCount}: ${p.fileName} — ` +
    `${formatMb(p.done)} / ${formatMb(p.total)} MB (${pct}%)${rate}${eta}${wait}`
  );
}

function fileKey(kind: string, f: File) {
  return `${kind}:${f.name}:${f.size}:${f.lastModified}`;
}

export default function New() {
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState("");
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [step, setStep] = useState(0);
  const [draftNotice, setDraftNotice] = useState(false);
  const [stats, setStats] = useState<CreateStats>({
    clipCount: 0,
    clipSecs: 0,
    musicName: "",
    musicSecs: null,
  });
  const [clipRefs, setClipRefs] = useState<string[]>(() => loadDraft()?.clipRefs ?? []);
  const [musicRef, setMusicRef] = useState(() => loadDraft()?.musicRef ?? "");
  const [musicOffset, setMusicOffset] = useState<number | null>(
    () => loadDraft()?.musicOffset ?? null,
  );
  const [musicDuration, setMusicDuration] = useState<number | null>(
    () => loadDraft()?.musicDuration ?? null,
  );
  const [name, setName] = useState(() => loadDraft()?.name ?? "");
  const [brief, setBrief] = useState(() => loadDraft()?.brief ?? "");
  const [theme, setTheme] = useState(
    () => loadDraft()?.theme || getFormMemory("theme") || "training",
  );
  const [audience, setAudience] = useState(
    () => loadDraft()?.audience || getFormMemory("audience") || "prospects",
  );
  const [handle, setHandle] = useState(() => loadDraft()?.handle ?? getFormMemory("handle") ?? "");
  const formRef = useRef<HTMLFormElement>(null);
  const navigate = useNavigate();
  const confirm = useConfirm();
  // Staging-dir reuse across Start retries on the same files: file key ->
  // upload_id. A failed submit keeps the component mounted, so a retry
  // resumes the existing staging dir (via GET status) instead of
  // orphaning it with a fresh init.
  const uploadIds = useRef(new Map<string, string>());

  useEffect(() => {
    api.getConfig().then(setConfig);
  }, []);

  useEffect(() => {
    if (loadDraft()) setDraftNotice(true);
  }, []);

  // Tick while uploading so the progress line's "waiting Ns" and rate
  // stay live even when no chunk completes for a while.
  useEffect(() => {
    if (!uploading) return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [uploading]);

  useCreateDraft({
    name,
    brief,
    theme,
    audience,
    handle,
    clipRefs,
    musicRef,
    musicOffset,
    musicDuration,
  });

  function mediaError(): string | null {
    if (!name) return "Give the session a name — or hit Suggest.";
    if (!NAME_RE.test(name))
      return "Session name may only use letters, numbers, _ and - (no spaces).";
    if (stats.clipCount === 0)
      return "Add at least one clip or photo — drop files or reuse library.";
    if (!stats.musicName) return "Pick a music track — a track is required for the cut.";
    return null;
  }

  async function discardDraft() {
    const ok = await confirm({
      title: "Discard this draft?",
      body: (
        <p>
          Clears the saved name, brief, and library picks for this form. Uploaded files are not
          touched. This cannot be undone.
        </p>
      ),
      confirmLabel: "Discard draft",
      tone: "danger",
    });
    if (!ok) return;
    clearDraft();
    setDraftNotice(false);
    setName("");
    setBrief("");
    setClipRefs([]);
    setMusicRef("");
    setMusicOffset(null);
    setMusicDuration(null);
    setHandle(getFormMemory("handle") ?? "");
  }

  function goTo(next: number) {
    if (next > step) {
      if (step === 0) {
        const err = mediaError();
        if (err) {
          setError(err);
          return;
        }
      }
    }
    setError(null);
    setStep(next);
    window.scrollTo({ top: 0 });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!formRef.current) return;
    const mediaErr = mediaError();
    if (mediaErr) {
      setStep(0);
      setError(mediaErr);
      return;
    }
    const formData = new FormData(formRef.current);
    const hasClipFile = formData
      .getAll("clips")
      .some((v) => v instanceof File && v.size > 0 && v.name !== "");
    const hasMusicFile = formData
      .getAll("music")
      .some((v) => v instanceof File && v.size > 0 && v.name !== "");
    const missingClips = clipRefs.length === 0 && !hasClipFile;
    const missingMusic = !musicRef && !hasMusicFile;
    if (missingClips || missingMusic) {
      setStep(0);
      const lostUploads =
        (missingMusic && stats.musicName !== "") ||
        (missingClips && stats.clipCount > clipRefs.length);
      if (lostUploads) {
        setError(
          "Your uploaded file(s) didn't reach the form — the browser dropped them. " +
            "Drop or browse them again on the Media step; library picks are kept.",
        );
      } else if (missingClips && missingMusic) {
        setError(
          "Add at least one clip or photo and pick a music track — drop files or reuse the library.",
        );
      } else if (missingClips) {
        setError("Add at least one clip or photo — drop files or reuse the library.");
      } else {
        setError("Pick a music track — drop one or reuse the library.");
      }
      return;
    }

    setUploading(true);
    setError(null);
    setStatus("Uploading...");
    for (const ref of clipRefs) formData.append("clip_refs", ref);
    formData.set("music_ref", musicRef);
    if (musicOffset != null && musicDuration != null) {
      formData.set("music_offset", String(musicOffset));
      formData.set("music_duration", String(musicDuration));
    }
    saveFormMemory(formData);
    try {
      const clipFiles = formData
        .getAll("clips")
        .filter((v): v is File => v instanceof File && v.size > 0 && v.name !== "");
      const musicFile =
        formData
          .getAll("music")
          .find((v): v is File => v instanceof File && v.size > 0 && v.name !== "") ?? null;
      const logoFile =
        formData
          .getAll("logo")
          .find((v): v is File => v instanceof File && v.size > 0 && v.name !== "") ?? null;
      const freshFiles = [
        ...clipFiles,
        ...(musicFile ? [musicFile] : []),
        ...(logoFile ? [logoFile] : []),
      ];
      const totalBytes = freshFiles.reduce((acc, f) => acc + f.size, 0);
      const maxSingle = freshFiles.reduce((acc, f) => Math.max(acc, f.size), 0);
      const useChunked =
        totalBytes > CHUNKED_THRESHOLD_TOTAL || maxSingle > CHUNKED_THRESHOLD_SINGLE;
      if (useChunked) {
        // Chunked path: files go up strictly one at a time in 2 MB PUTs
        // (parallel multi-MB PUTs stall the cloudflared origin conn),
        // then the session is created with only upload-ids + refs + text
        // fields (tiny body).
        const sizes = [
          ...clipFiles.map((f) => f.size),
          ...(musicFile ? [musicFile.size] : []),
          ...(logoFile ? [logoFile.size] : []),
        ];
        const loaded = sizes.map(() => 0);
        const names = [
          ...clipFiles.map((f) => f.name),
          ...(musicFile ? [musicFile.name] : []),
          ...(logoFile ? [logoFile.name] : []),
        ];
        const samples: { t: number; b: number }[] = [];
        let curIdx = 0;
        let note = "";
        const report = () => {
          const done = loaded.reduce((a, b) => a + b, 0);
          const total = sizes.reduce((a, b) => a + b, 0);
          const now = Date.now();
          samples.push({ t: now, b: done });
          while (samples.length > 2 && now - samples[0].t > 15_000) samples.shift();
          const span = samples.length > 1 ? (now - samples[0].t) / 1000 : 0;
          const rateBps = span >= 2 && done > samples[0].b ? (done - samples[0].b) / span : null;
          setProgress({
            done,
            total,
            fileName: names[curIdx] ?? "",
            fileIdx: curIdx,
            fileCount: sizes.length,
            rateBps,
            lastActivity: now,
            note,
          });
        };
        const noteIt = (msg: string) => {
          note = msg;
          report();
        };
        report();
        const clipRefs2: ChunkedUploadRef[] = [];
        for (let i = 0; i < clipFiles.length; i++) {
          const f = clipFiles[i];
          const key = fileKey("clip", f);
          curIdx = i;
          const upNote = (msg: string) => noteIt(`${f.name}: ${msg}`);
          const u = await uploadFileChunked(
            f,
            "clip",
            name,
            (l) => {
              loaded[i] = l;
              report();
            },
            { uploadId: uploadIds.current.get(key), onNote: upNote },
          );
          uploadIds.current.set(key, u.upload_id);
          clipRefs2.push(u);
        }
        let musicDone: ChunkedUploadRef | null = null;
        if (musicFile) {
          const idx = clipFiles.length;
          const key = fileKey("music", musicFile);
          curIdx = idx;
          const upNote = (msg: string) => noteIt(`${musicFile.name}: ${msg}`);
          musicDone = await uploadFileChunked(
            musicFile,
            "music",
            name,
            (l) => {
              loaded[idx] = l;
              report();
            },
            { uploadId: uploadIds.current.get(key), onNote: upNote },
          );
          uploadIds.current.set(key, musicDone.upload_id);
        }
        let logoDone: ChunkedUploadRef | null = null;
        if (logoFile) {
          const idx = clipFiles.length + (musicFile ? 1 : 0);
          const key = fileKey("logo", logoFile);
          curIdx = idx;
          const upNote = (msg: string) => noteIt(`${logoFile.name}: ${msg}`);
          logoDone = await uploadFileChunked(
            logoFile,
            "logo",
            name,
            (l) => {
              loaded[idx] = l;
              report();
            },
            { uploadId: uploadIds.current.get(key), onNote: upNote },
          );
          uploadIds.current.set(key, logoDone.upload_id);
        }
        const tiny = new FormData();
        for (const [key, value] of formData.entries()) {
          // Re-added explicitly below (plus upload ids); copying them here
          // would duplicate every library ref.
          if (typeof value !== "string") continue;
          if (key === "clip_refs" || key === "music_ref") continue;
          if (key === "music_offset" || key === "music_duration") continue;
          tiny.append(key, value);
        }
        for (const ref of clipRefs) tiny.append("clip_refs", ref);
        tiny.set("music_ref", musicRef);
        if (musicOffset != null && musicDuration != null) {
          tiny.set("music_offset", String(musicOffset));
          tiny.set("music_duration", String(musicDuration));
        }
        for (const u of clipRefs2) tiny.append("clip_upload_ids", u.upload_id);
        if (musicDone) tiny.set("music_upload_id", musicDone.upload_id);
        if (logoDone) tiny.set("logo_upload_id", logoDone.upload_id);
        saveFormMemory(tiny);
        setProgress(null);
        setStatus("Upload complete, saving session and launching pipeline...");
        const res = await fetch("/api/sessions", { method: "POST", body: tiny });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new ApiError(res.status, body.detail ?? res.statusText);
        }
        const { name: created } = (await res.json()) as { name: string };
        clearDraft();
        navigate(`/studio/${created}`);
        return;
      }
      const { name: created } = await createSessionWithProgress(formData, (loaded, total) => {
        const pct = Math.round((loaded / total) * 100);
        setStatus(`Uploading: ${formatMb(loaded)} / ${formatMb(total)} MB (${pct}%)`);
        if (loaded === total) {
          setStatus("Upload complete, saving session and launching pipeline...");
        }
      });
      clearDraft();
      navigate(`/studio/${created}`);
    } catch (err) {
      setUploading(false);
      if (err instanceof ApiError) {
        setError(err.detail);
        setStatus("");
      } else {
        setStatus(err instanceof Error ? err.message : "Upload failed.");
      }
    }
  }

  if (!config) return <p>Loading&hellip;</p>;

  return (
    <>
      <h2>New session</h2>
      {draftNotice && (
        <p className="draft-banner">
          Draft restored — text and library picks are back; fresh files need re-adding.{" "}
          <button type="button" className="link-button" onClick={() => void discardDraft()}>
            Discard draft
          </button>
        </p>
      )}
      {error && (
        <p className="status-failed" role="alert">
          {error}
        </p>
      )}
      <FormSteps steps={STEPS} current={step} onJump={goTo} />
      <div className="create-layout">
        <form
          ref={formRef}
          onSubmit={handleSubmit}
          className="create-form"
          onInput={(e) => {
            const t = e.target as HTMLInputElement;
            if (t.name === "handle") setHandle(t.value);
          }}
        >
          {/* All steps stay mounted (inactive ones `hidden`) so file inputs,
              picks, and named fields are all in the submitted FormData. */}
          <section aria-label="Media" hidden={step !== 0}>
            <label htmlFor="new-name">
              Session name
              <span className="name-row">
                <input
                  id="new-name"
                  type="text"
                  name="name"
                  required
                  pattern="[A-Za-z0-9_\-]+"
                  title="Letters, numbers, _ and - only (no spaces)"
                  placeholder="reel-20260922-42"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
                <button type="button" onClick={() => setName(suggestName())}>
                  Suggest
                </button>
              </span>
            </label>
            <MediaLibraryPicker
              onClipsChange={setClipRefs}
              onMusicChange={setMusicRef}
              onStatsChange={setStats}
              onMusicPinChange={(o, d) => {
                setMusicOffset(o);
                setMusicDuration(d);
              }}
              initialClips={clipRefs}
              initialMusic={musicRef}
              initialMusicOffset={musicOffset}
              initialMusicDuration={musicDuration}
            />
          </section>

          <section aria-label="Describe" hidden={step !== 1}>
            <DescribeFields
              brief={brief}
              theme={theme}
              audience={audience}
              onBrief={setBrief}
              onTheme={setTheme}
              onAudience={setAudience}
            />
          </section>

          <section aria-label="Style and launch" hidden={step !== 2}>
            <BrandFieldset
              idPrefix="new"
              legend="Brand (optional; no logo = no watermark / end card)"
            />
            <details className="advanced-panel">
              <summary>Advanced: model</summary>
              <ProviderModelFields
                providers={config.providers}
                defaultModels={config.default_models}
                idPrefix="new"
              />
              <p className="field-hint">
                The model plans the cut. Defaults are fine — change only if you know why.
              </p>
              <ApiKeyHint />
            </details>
          </section>

          <p className="create-nav">
            {step > 0 && (
              <button type="button" onClick={() => goTo(step - 1)}>
                Back
              </button>
            )}
            {step < STEPS.length - 1 && (
              <button type="button" className="primary" onClick={() => goTo(step + 1)}>
                {step === 0 && stats.clipCount > 0 && stats.musicName
                  ? `Continue · ${stats.clipCount} clips`
                  : "Next"}
              </button>
            )}
            {step === STEPS.length - 1 && (
              <button type="submit" className="primary" disabled={uploading}>
                {uploading ? "Uploading…" : "Start run"}
              </button>
            )}
          </p>
          <p id="upload-status" aria-live="polite">
            {progress ? formatProgress(progress, nowMs) : status}
          </p>
          {progress?.note ? (
            <p className="field-hint" aria-live="polite">
              {progress.note}
            </p>
          ) : null}
        </form>
        <CreateSummary
          stats={stats}
          brief={brief}
          theme={theme}
          audience={audience}
          handle={handle}
          step={step}
          onEdit={goTo}
          musicOffset={musicOffset}
          musicDuration={musicDuration}
        />
      </div>
    </>
  );
}
