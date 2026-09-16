import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fileUrl, reelUrl } from "../api";
import HookPicker from "../components/HookPicker";
import LowCandidatesPause from "../components/LowCandidatesPause";
import MusicPicker from "../components/MusicPicker";
import RegenerateForm from "../components/RegenerateForm";
import StageRail from "../components/StageRail";
import StartForm from "../components/StartForm";
import VerificationPause from "../components/VerificationPause";
import type { Config, SessionDetail } from "../types";

export default function Session() {
  const { name = "" } = useParams();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
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

  if (!session || !config) return <p>Loading&hellip;</p>;

  const { job } = session;
  const allPending = Object.values(session.stage_statuses).every((s) => s === "pending");

  return (
    <>
      <h2>{name}</h2>
      <StageRail
        name={name}
        stages={session.stages}
        stageStatuses={session.stage_statuses}
        detail={job?.detail}
      />

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

      {!job?.awaiting_confirmation && job === null && allPending && (
        <StartForm name={name} config={config} onStarted={refresh} />
      )}

      {!job?.awaiting_confirmation && (job === null || (job.done && !job.error)) && !allPending && (
        <>
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
          {job?.check_results && job.check_results.length > 0 && (
            <>
              <h3>Render checks</h3>
              <pre>{job.check_results.join("\n")}</pre>
            </>
          )}
          {session.reel_b_exists && (
            <>
              <h3>Variant B</h3>
              <video className="reel-player" controls src={fileUrl(name, "reel_b.mp4")} />
              <p>
                <a href={fileUrl(name, "reel_b.mp4")} download>
                  Download reel_b.mp4
                </a>
              </p>
              {job?.check_results_b && job.check_results_b.length > 0 && (
                <>
                  <h3>Render checks (B)</h3>
                  <pre>{job.check_results_b.join("\n")}</pre>
                </>
              )}
            </>
          )}
          <RegenerateForm
            name={name}
            config={config}
            defaultFromStage={session.default_from_stage}
            onStarted={refresh}
          />
        </>
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
    </>
  );
}
