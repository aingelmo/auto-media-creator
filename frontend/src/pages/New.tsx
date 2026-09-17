import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, createSessionWithProgress } from "../api";
import { api } from "../api";
import BrandFieldset from "../components/BrandFieldset";
import FormSteps from "../components/FormSteps";
import MediaLibraryPicker from "../components/MediaLibraryPicker";
import ProviderModelFields from "../components/ProviderModelFields";
import ThemeAudienceFields from "../components/ThemeAudienceFields";
import { saveFormMemory } from "../formMemory";
import type { Config } from "../types";

const STEPS = ["Media", "Content", "Look", "Review"] as const;

function formatMb(bytes: number) {
  return (bytes / 1e6).toFixed(1);
}

function fileName(ref: string) {
  return ref.split("/").pop() ?? ref;
}

interface ReviewData {
  name: string;
  clips: string;
  music: string;
  theme: string;
  audience: string;
  brief: string;
  model: string;
  logo: string;
  handle: string;
  line: string;
}

export default function New() {
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState("");
  const [source, setSource] = useState<"upload" | "library">("upload");
  const [clipRefs, setClipRefs] = useState<string[]>([]);
  const [musicRef, setMusicRef] = useState("");
  const [step, setStep] = useState(0);
  const [review, setReview] = useState<ReviewData | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const stepRefs = useRef<(HTMLDivElement | null)[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    api.getConfig().then(setConfig);
  }, []);

  // Uncontrolled form: snapshot the review-step values only when it's shown.
  useEffect(() => {
    const form = formRef.current;
    if (step !== 3 || !form) return;
    const field = <T extends Element>(name: string) => form.elements.namedItem(name) as T | null;
    const clipsInput = field<HTMLInputElement>("clips");
    const musicInput = field<HTMLInputElement>("music");
    const logoInput = field<HTMLInputElement>("logo");
    setReview({
      name: field<HTMLInputElement>("name")?.value || "—",
      clips:
        source === "library"
          ? `${clipRefs.length} picked`
          : `${clipsInput?.files?.length ?? 0} file(s)`,
      music:
        source === "library"
          ? musicRef
            ? fileName(musicRef)
            : "—"
          : (musicInput?.files?.[0]?.name ?? "—"),
      theme: field<HTMLSelectElement>("theme")?.selectedOptions[0]?.textContent ?? "—",
      audience: field<HTMLSelectElement>("audience")?.selectedOptions[0]?.textContent ?? "—",
      brief: field<HTMLInputElement>("brief")?.value || "—",
      model: field<HTMLSelectElement>("provider")?.selectedOptions[0]?.textContent ?? "—",
      logo: logoInput?.files?.[0]?.name ?? "none",
      handle: field<HTMLInputElement>("handle")?.value || "—",
      line: field<HTMLInputElement>("line")?.value || "—",
    });
  }, [step, source, clipRefs, musicRef]);

  /** True if every required input/select visible in step `i` is filled in.
   * Reports the first invalid one so the browser's native bubble shows up
   * (only meaningful while that step is on screen). */
  function stepValid(i: number): boolean {
    const el = stepRefs.current[i];
    if (!el) return true;
    for (const c of el.querySelectorAll<HTMLInputElement>("input, select")) {
      if (!c.checkValidity()) {
        c.reportValidity();
        return false;
      }
    }
    return true;
  }

  function goTo(next: number) {
    if (next > step && !stepValid(step)) return;
    setError(null);
    setStep(next);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!formRef.current) return;

    for (let i = 0; i < STEPS.length; i++) {
      if (!stepValid(i)) {
        setStep(i);
        return;
      }
    }
    if (source === "library" && (clipRefs.length === 0 || !musicRef)) {
      setStep(0);
      setError("Pick at least one clip and a music track from the library.");
      return;
    }

    setUploading(true);
    setError(null);
    setStatus("Uploading...");
    const formData = new FormData(formRef.current);
    if (source === "library") {
      formData.delete("clips");
      formData.delete("music");
      for (const ref of clipRefs) formData.append("clip_refs", ref);
      formData.set("music_ref", musicRef);
    }
    saveFormMemory(formData);
    try {
      const { name } = await createSessionWithProgress(formData, (loaded, total) => {
        const pct = Math.round((loaded / total) * 100);
        setStatus(`Uploading: ${formatMb(loaded)} / ${formatMb(total)} MB (${pct}%)`);
        if (loaded === total) {
          setStatus("Upload complete, saving session and launching pipeline...");
        }
      });
      navigate(`/sessions/${name}`);
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
      {error && <p className="status-failed">{error}</p>}
      <FormSteps steps={STEPS} current={step} onJump={goTo} />
      <form ref={formRef} onSubmit={handleSubmit}>
        <div
          className="form-grid"
          hidden={step !== 0}
          ref={(el) => {
            stepRefs.current[0] = el;
          }}
        >
          <label htmlFor="new-name">
            Session name
            <input id="new-name" type="text" name="name" required pattern="[A-Za-z0-9_-]+" />
          </label>
          <fieldset>
            <legend>Clips &amp; music</legend>
            <div className="source-toggle">
              <button
                type="button"
                disabled={source === "upload"}
                onClick={() => setSource("upload")}
              >
                Upload files
              </button>
              <button
                type="button"
                disabled={source === "library"}
                onClick={() => setSource("library")}
              >
                Pick from past sessions
              </button>
            </div>
            {source === "upload" ? (
              <div className="form-grid">
                <label htmlFor="new-clips">
                  Clips / photos
                  <input id="new-clips" type="file" name="clips" multiple required />
                </label>
                <label htmlFor="new-music">
                  Music track (mp3, wav, or mp4/m4a)
                  <input
                    id="new-music"
                    type="file"
                    name="music"
                    accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,video/mp4"
                    required
                  />
                </label>
              </div>
            ) : (
              <MediaLibraryPicker onClipsChange={setClipRefs} onMusicChange={setMusicRef} />
            )}
          </fieldset>
        </div>

        <div
          className="form-grid"
          hidden={step !== 1}
          ref={(el) => {
            stepRefs.current[1] = el;
          }}
        >
          <ThemeAudienceFields idPrefix="new" />
        </div>

        <div
          className="form-grid"
          hidden={step !== 2}
          ref={(el) => {
            stepRefs.current[2] = el;
          }}
        >
          <p>Provider, model &amp; brand (remembered from last run)</p>
          <ProviderModelFields
            providers={config.providers}
            defaultModels={config.default_models}
            idPrefix="new"
          />
          <BrandFieldset
            idPrefix="new"
            legend="Brand (optional; no logo = no watermark / end card)"
          />
        </div>

        <div
          className="form-grid"
          hidden={step !== 3}
          ref={(el) => {
            stepRefs.current[3] = el;
          }}
        >
          {review && (
            <dl className="review-list">
              <dt>Session name</dt>
              <dd className={review.name === "—" ? "is-empty" : undefined}>{review.name}</dd>
              <dt>Clips</dt>
              <dd>{review.clips}</dd>
              <dt>Music</dt>
              <dd className={review.music === "—" ? "is-empty" : undefined}>{review.music}</dd>
              <dt>Theme</dt>
              <dd>{review.theme}</dd>
              <dt>Audience</dt>
              <dd>{review.audience}</dd>
              <dt>Brief</dt>
              <dd className={review.brief === "—" ? "is-empty" : undefined}>{review.brief}</dd>
              <dt>Model</dt>
              <dd>{review.model}</dd>
              <dt>Logo</dt>
              <dd className={review.logo === "none" ? "is-empty" : undefined}>{review.logo}</dd>
              <dt>Handle</dt>
              <dd className={review.handle === "—" ? "is-empty" : undefined}>{review.handle}</dd>
              <dt>Second line</dt>
              <dd className={review.line === "—" ? "is-empty" : undefined}>{review.line}</dd>
            </dl>
          )}
        </div>

        <p>
          {step > 0 && (
            <button type="button" onClick={() => goTo(step - 1)}>
              Back
            </button>
          )}
          {step < STEPS.length - 1 && (
            <button type="button" onClick={() => goTo(step + 1)}>
              Next
            </button>
          )}
          {step === STEPS.length - 1 && (
            <button type="submit" disabled={uploading}>
              Start run
            </button>
          )}
        </p>
        <p id="upload-status">{status}</p>
      </form>
    </>
  );
}
