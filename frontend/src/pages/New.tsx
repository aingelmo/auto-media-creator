import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, createSessionWithProgress } from "../api";
import { api } from "../api";
import BrandFieldset from "../components/BrandFieldset";
import ProviderModelFields from "../components/ProviderModelFields";
import ThemeAudienceFields from "../components/ThemeAudienceFields";
import type { Config } from "../types";

export default function New() {
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.getConfig().then(setConfig);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!formRef.current) return;
    setUploading(true);
    setError(null);
    setStatus("Uploading...");
    const formData = new FormData(formRef.current);
    try {
      const { name } = await createSessionWithProgress(formData, (loaded, total) => {
        const mb = (n: number) => (n / 1e6).toFixed(1);
        const pct = Math.round((loaded / total) * 100);
        setStatus(`Uploading: ${mb(loaded)} / ${mb(total)} MB (${pct}%)`);
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
      <form ref={formRef} onSubmit={handleSubmit}>
        <label htmlFor="new-name">
          Session name
          <input
            id="new-name"
            type="text"
            name="name"
            required
            pattern="[A-Za-z0-9_-]+"
          />
        </label>
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
        <ProviderModelFields
          providers={config.providers}
          defaultModels={config.default_models}
          idPrefix="new"
        />
        <ThemeAudienceFields idPrefix="new" />
        <BrandFieldset idPrefix="new" legend="Brand (optional; no logo = no watermark / end card)" />
        <p>
          <button type="submit" disabled={uploading}>
            Start run
          </button>
        </p>
        <p id="upload-status">{status}</p>
      </form>
    </>
  );
}
