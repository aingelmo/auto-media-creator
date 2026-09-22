import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, createSessionWithProgress } from "../api";
import { api } from "../api";
import { getFormMemory, saveFormMemory } from "../formMemory";
import { clearDraft, loadDraft, suggestName, useCreateDraft } from "../useCreateDraft";
import type { Config } from "../types";
import BrandFieldset from "../components/BrandFieldset";
import CreateSummary, { type CreateStats } from "../components/CreateSummary";
import DescribeFields from "../components/DescribeFields";
import FormSteps from "../components/FormSteps";
import MediaLibraryPicker from "../components/MediaLibraryPicker";
import ProviderModelFields from "../components/ProviderModelFields";

const STEPS = ["Media", "Describe", "Style & launch"] as const;
const NAME_RE = /^[A-Za-z0-9_-]+$/;

function formatMb(bytes: number) {
  return (bytes / 1e6).toFixed(1);
}

export default function New() {
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState("");
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

  useEffect(() => {
    api.getConfig().then(setConfig);
  }, []);

  useEffect(() => {
    if (loadDraft()) setDraftNotice(true);
  }, []);

  useCreateDraft({ name, brief, theme, audience, handle, clipRefs, musicRef });

  function mediaError(): string | null {
    if (!name) return "Give the session a name — or hit Suggest.";
    if (!NAME_RE.test(name))
      return "Session name may only use letters, numbers, _ and - (no spaces).";
    if (stats.clipCount === 0)
      return "Add at least one clip or photo — drop files or reuse library.";
    if (!stats.musicName) return "Pick a music track — a track is required for the cut.";
    return null;
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
    const hasClipUpload = (formData.get("clips") as File | null)?.size;
    const hasMusicUpload = (formData.get("music") as File | null)?.size;
    if ((clipRefs.length === 0 && !hasClipUpload) || (!musicRef && !hasMusicUpload)) {
      setStep(0);
      setError("Pick or upload at least one clip and a music track.");
      return;
    }

    setUploading(true);
    setError(null);
    setStatus("Uploading...");
    for (const ref of clipRefs) formData.append("clip_refs", ref);
    formData.set("music_ref", musicRef);
    saveFormMemory(formData);
    try {
      const { name: created } = await createSessionWithProgress(formData, (loaded, total) => {
        const pct = Math.round((loaded / total) * 100);
        setStatus(`Uploading: ${formatMb(loaded)} / ${formatMb(total)} MB (${pct}%)`);
        if (loaded === total) {
          setStatus("Upload complete, saving session and launching pipeline...");
        }
      });
      clearDraft();
      navigate(`/sessions/${created}`);
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
          <button
            type="button"
            className="link-button"
            onClick={() => {
              clearDraft();
              setDraftNotice(false);
              setName("");
              setBrief("");
              setClipRefs([]);
              setMusicRef("");
              setHandle(getFormMemory("handle") ?? "");
            }}
          >
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
              initialClips={clipRefs}
              initialMusic={musicRef}
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
            {status}
          </p>
        </form>
        <CreateSummary
          stats={stats}
          brief={brief}
          theme={theme}
          audience={audience}
          handle={handle}
          step={step}
          onEdit={goTo}
        />
      </div>
    </>
  );
}
