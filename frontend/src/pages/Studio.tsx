import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fileUrl, reelUrl } from "../api";
import MusicPicker from "../components/MusicPicker";
import StageRail from "../components/StageRail";
import TimelineStrip from "../components/TimelineStrip";
import type { SessionDetail, StageName, TimelinePayload } from "../types";
import Candidates from "./Candidates";
import Hooks from "./Hooks";
import Ingest from "./Ingest";
import Planner from "./Planner";
import Selection from "./Selection";

const STAGE_VIEWS: Partial<Record<StageName, React.ComponentType>> = {
  ingest: Ingest,
  candidates: Candidates,
  selection: Selection,
  hooks: Hooks,
  planner: Planner,
};

export default function Studio() {
  const { name = "" } = useParams();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelinePayload | null>(null);
  const [hookText, setHookText] = useState("");
  const [flash, setFlash] = useState(false);
  const [punch, setPunch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [viewStage, setViewStage] = useState<StageName | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    const detail = await api.getSession(name);
    setSession(detail);
    if (detail.job) {
      setFlash(detail.job.hook_flash);
      setPunch(detail.job.punch_in);
      setHookText(detail.job.hook_choice ?? "");
    }
    try {
      setTimeline(await api.getTimeline(name));
    } catch {
      setTimeline(null);
    }
    try {
      const payload = await api.getCandidates(name);
      const map: Record<string, string> = {};
      for (const c of payload.candidates) {
        if (c.peak_urls.length > 0) map[c.id] = c.peak_urls[0];
      }
      setThumbs(map);
    } catch {
      setThumbs({});
    }
    return detail;
  }, [name]);

  useEffect(() => {
    refresh();
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [refresh]);

  // Poll /status every 3s while a job is running; deps narrowed so the
  // timer isn't torn down each tick (mirrors Session.tsx).
  // oxlint-disable react-hooks/exhaustive-deps, react/exhaustive-effect-dependencies --
  // deps are intentionally narrowed to primitive fields so the poll timer
  // isn't torn down and restarted on every tick.
  useEffect(() => {
    if (!session?.job || session.job.done || session.job.awaiting_confirmation) {
      return;
    }
    let cancelled = false;
    async function poll() {
      const status = await api.getStatus(name);
      if (cancelled) return;
      if (status.done || status.awaiting_confirmation) {
        await refresh();
      } else {
        setSession((prev) =>
          prev?.job
            ? {
                ...prev,
                stage_statuses: status.stages,
                job: { ...prev.job, stages: status.stages, detail: status.detail },
              }
            : prev,
        );
        pollTimer.current = setTimeout(poll, 3000);
      }
    }
    pollTimer.current = setTimeout(poll, 3000);
    return () => {
      cancelled = true;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [session?.job?.done, session?.job?.awaiting_confirmation, name, refresh]);
  // oxlint-enable react-hooks/exhaustive-deps, react/exhaustive-effect-dependencies

  if (!session) return <p>Loading&hellip;</p>;
  const { job } = session;
  const musicGate = job?.awaiting_confirmation && job.pause_kind === "music_choice";
  const running = job && !job.done && !job.error && !job.awaiting_confirmation;

  async function handleReorder(order: number[]) {
    setBusy(true);
    setError(null);
    try {
      setTimeline(await api.reorderDevelops(name, order));
      setNotice("Clip order saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Swap failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveHook() {
    setBusy(true);
    setError(null);
    try {
      setTimeline(await api.setHookText(name, hookText));
      setNotice("Hook saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hook save failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveEffects() {
    setBusy(true);
    setError(null);
    try {
      setTimeline(await api.setEffects(name, flash, punch));
      await refresh();
      setNotice("Effects saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Effects save failed.");
    } finally {
      setBusy(false);
    }
  }

  const previewSrc = timeline?.preview_path ? fileUrl(name, timeline.preview_path) : null;

  return (
    <div className="session-page">
      <h2>
        {name} <span className="cost-badge">${session.total_cost_usd.toFixed(4)}</span>
      </h2>
      <p className="field-hint">
        <Link to={`/sessions/${encodeURIComponent(name)}`}>← Back to session</Link>
        {" — swaps and saves apply instantly; to render, go back and Regenerate from "}
        <em>render</em>.
      </p>
      {error && (
        <p className="status-failed" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <output className="status-done" aria-live="polite">
          {notice}
        </output>
      )}
      <StageRail
        stages={session.stages}
        stageStatuses={session.stage_statuses}
        detail={job?.detail}
        onView={setViewStage}
      />
      {viewStage &&
        STAGE_VIEWS[viewStage] &&
        (() => {
          const StageView = STAGE_VIEWS[viewStage];
          return (
            <section className="stage-detail-panel" aria-label={`${viewStage} details`}>
              <div className="stage-detail-panel-header">
                <h3>{viewStage}</h3>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Close ${viewStage} details`}
                  onClick={() => setViewStage(null)}
                >
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path
                      d="M2 2l12 12M14 2L2 14"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              </div>
              <StageView />
            </section>
          );
        })()}
      {job?.notices && job.notices.length > 0 && (
        <ul className="studio-notices" aria-label="Auto decisions">
          {job.notices.map((n, i) => (
            <li key={`${n.kind}-${i}`}>
              {n.message} <span className="notice-kind">({n.kind})</span>
            </li>
          ))}
        </ul>
      )}
      {musicGate && job && (
        <MusicPicker name={name} candidates={job.music_candidates} onDone={refresh} />
      )}
      <div className="studio-grid">
        <section className="studio-main" aria-label="Preview">
          <h3>Preview</h3>
          {session.reel_exists ? (
            <video
              className="reel-player studio-preview-video"
              controls
              preload="metadata"
              src={reelUrl(name)}
              aria-label="Finished reel"
            />
          ) : previewSrc ? (
            <video
              className="reel-player studio-preview-video"
              controls
              preload="metadata"
              src={previewSrc}
              aria-label="Draft preview"
            />
          ) : (
            <p>{running ? "Rendering preview…" : "Preview appears here."}</p>
          )}
        </section>
        <section className="studio-side" aria-label="Refine">
          <h3>Refine</h3>
          <label>
            Hook text (manual, empty = none)
            <input
              type="text"
              value={hookText}
              maxLength={40}
              onChange={(e) => setHookText(e.target.value)}
              placeholder="Write the hook overlay…"
            />
          </label>
          <button type="button" disabled={busy} onClick={saveHook}>
            Save hook
          </button>
          <label>
            <input type="checkbox" checked={flash} onChange={(e) => setFlash(e.target.checked)} />
            Hook flash
          </label>
          <label>
            <input type="checkbox" checked={punch} onChange={(e) => setPunch(e.target.checked)} />
            Punch-in on develops
          </label>
          <button type="button" disabled={busy} onClick={saveEffects}>
            Save effects
          </button>
          <p className="field-hint">
            Hook and close stay locked to the LLM pick; only develop slots swap.
          </p>
        </section>
      </div>
      <section aria-label="Timeline">
        <h3>Timeline</h3>
        {timeline ? (
          <TimelineStrip
            clips={timeline.clips}
            thumbUrls={thumbs}
            disabled={busy}
            onReorder={handleReorder}
          />
        ) : (
          <p>Timeline appears once planning finishes.</p>
        )}
      </section>
      {running && (
        <output className="status-running" aria-live="polite">
          Running&hellip;
        </output>
      )}
      {job?.error && (
        <div role="alert">
          <p className="status-failed">Render failed — {job.error}</p>
        </div>
      )}
    </div>
  );
}
