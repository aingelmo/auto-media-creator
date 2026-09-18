import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fileUrl, reelUrl } from "../api";
import HookPicker from "../components/HookPicker";
import LowCandidatesPause from "../components/LowCandidatesPause";
import Modal from "../components/Modal";
import MusicPicker from "../components/MusicPicker";
import PunchPreview from "../components/PunchPreview";
import RegenerateForm from "../components/RegenerateForm";
import RegenHistory from "../components/RegenHistory";
import StageRail from "../components/StageRail";
import StartForm from "../components/StartForm";
import VerificationPause from "../components/VerificationPause";
import type { Config, SessionDetail, StageName } from "../types";
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

export default function Session() {
  const { name = "" } = useParams();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [viewStage, setViewStage] = useState<StageName | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    const detail = await api.getSession(name);
    setSession(detail);
    return detail;
  }, [name]);

  useEffect(() => {
    refresh();
    api.getConfig().then(setConfig);
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [refresh]);

  // Poll /status every 3s while a job is running with no live data needed
  // beyond stage progress; on completion or a new pause, refetch the full
  // session (status alone doesn't carry hooks/music_candidates/reel flags).
  // oxlint-disable react-hooks/exhaustive-deps, react/exhaustive-effect-dependencies --
  // deps are intentionally narrowed to primitive fields so the poll timer
  // isn't torn down and restarted on every tick (job's object identity
  // changes each time status is fetched).
  useEffect(() => {
    if (!session?.job || session.job.done || session.job.awaiting_confirmation) return;

    let cancelled = false;
    async function poll() {
      const status = await api.getStatus(name);
      if (cancelled) return;
      if (status.done || status.awaiting_confirmation) {
        await refresh();
      } else {
        setSession((prev) =>
          prev && prev.job
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

  if (!session || !config) return <p>Loading&hellip;</p>;

  const { job } = session;
  const allPending = Object.values(session.stage_statuses).every((s) => s === "pending");

  return (
    <div className="session-page">
      <h2>
        {name} <span className="cost-badge">${session.total_cost_usd.toFixed(4)}</span>
      </h2>
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
            <Modal open onClose={() => setViewStage(null)}>
              <StageView />
            </Modal>
          );
        })()}

      {job && job.awaiting_confirmation && job.pause_kind === "music_choice" && (
        <MusicPicker name={name} candidates={job.music_candidates} onDone={refresh} />
      )}

      {job && job.awaiting_confirmation && job.pause_kind === "verification" && (
        <VerificationPause
          name={name}
          unverifiedSources={job.unverified_sources}
          onDone={refresh}
        />
      )}

      {job && job.awaiting_confirmation && job.pause_kind === "low_candidates" && (
        <LowCandidatesPause name={name} lowCandidates={job.low_candidates} onDone={refresh} />
      )}

      {job && job.awaiting_confirmation && job.pause_kind === "hook_choice" && (
        <HookPicker name={name} hooks={job.hooks} hookSlot={job.hook_slot} onDone={refresh} />
      )}

      {job && job.awaiting_confirmation && job.pause_kind === "punch_preview" && (
        <PunchPreview name={name} punchIn={job.punch_in} onDone={refresh} />
      )}

      {!job?.awaiting_confirmation && job === null && allPending && (
        <StartForm name={name} config={config} onStarted={refresh} />
      )}

      {!job?.awaiting_confirmation && (job === null || (job.done && !job.error)) && !allPending && (
        <div className="session-result">
          <div className="session-result-video">
            <div className="reel-variant">
              {session.reel_exists ? (
                <>
                  <video className="reel-player" controls src={reelUrl(name)} />
                  <p>
                    <a href={reelUrl(name)} download>
                      Download reel.mp4
                    </a>
                  </p>
                </>
              ) : (
                <p>Server restarted mid-run. Pick the next stage below to resume.</p>
              )}
            </div>
            {session.reel_b_exists && (
              <div className="reel-variant">
                <h3>Variant B</h3>
                <video className="reel-player" controls src={fileUrl(name, "reel_b.mp4")} />
                <p>
                  <a href={fileUrl(name, "reel_b.mp4")} download>
                    Download reel_b.mp4
                  </a>
                </p>
              </div>
            )}
          </div>
          <div className="session-result-regen">
            <RegenerateForm
              name={name}
              config={config}
              defaultFromStage={session.default_from_stage}
              onStarted={refresh}
            />
            <RegenHistory entries={session.history} />
            {((job?.check_results && job.check_results.length > 0) ||
              (job?.check_results_b && job.check_results_b.length > 0)) && (
              <details className="render-checks">
                <summary>render checks</summary>
                {job?.check_results && job.check_results.length > 0 && (
                  <>
                    <h3>Render checks</h3>
                    <pre>{job.check_results.join("\n")}</pre>
                  </>
                )}
                {job?.check_results_b && job.check_results_b.length > 0 && (
                  <>
                    <h3>Render checks (B)</h3>
                    <pre>{job.check_results_b.join("\n")}</pre>
                  </>
                )}
              </details>
            )}
          </div>
        </div>
      )}

      {!job?.awaiting_confirmation && job?.error && (
        <>
          <p className="status-failed">Failed</p>
          <pre>{job.error}</pre>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await api.retrySession(name);
              refresh();
            }}
          >
            <button type="submit" className="primary">
              Retry (resume from last completed stage)
            </button>
          </form>
        </>
      )}

      {!job?.awaiting_confirmation && job && !job.done && !job.error && (
        <p className="status-running">Running&hellip;</p>
      )}
    </div>
  );
}
