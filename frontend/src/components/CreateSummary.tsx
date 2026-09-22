import { formatSecs } from "./mediaMeta";

export interface CreateStats {
  clipCount: number;
  clipSecs: number;
  musicName: string;
  musicSecs: number | null;
}

/** Persistent summary rail beside the new-session form: what the run will
 * use, live. Every row jumps back to its step so Review is edit-in-place
 * instead of a separate read-only screen. */
export default function CreateSummary({
  stats,
  brief,
  theme,
  audience,
  handle,
  step,
  onEdit,
}: {
  stats: CreateStats;
  brief: string;
  theme: string;
  audience: string;
  handle: string;
  step: number;
  onEdit: (step: number) => void;
}) {
  const ready =
    stats.clipCount > 0 &&
    stats.musicName !== "" &&
    stats.musicSecs != null &&
    stats.clipSecs >= stats.musicSecs;
  return (
    <aside className="create-summary" aria-label="Session summary">
      <h3>Summary</h3>
      <dl>
        <div>
          <dt>Footage</dt>
          <dd>
            {stats.clipCount === 0 ? (
              <span className="is-empty">No clips yet</span>
            ) : (
              `${stats.clipCount} clips · ~${formatSecs(stats.clipSecs)}`
            )}{" "}
            <button type="button" className="link-button" onClick={() => onEdit(0)}>
              Edit
            </button>
          </dd>
        </div>
        <div>
          <dt>Music</dt>
          <dd>
            {stats.musicName ? (
              <>
                {stats.musicName}
                {stats.musicSecs != null && ` · ${formatSecs(stats.musicSecs)}`}
              </>
            ) : (
              <span className="is-empty">No track yet</span>
            )}{" "}
            <button type="button" className="link-button" onClick={() => onEdit(0)}>
              Edit
            </button>
          </dd>
        </div>
        <div>
          <dt>Brief</dt>
          <dd className={brief ? undefined : "is-empty"}>
            {brief || "—"}{" "}
            <button type="button" className="link-button" onClick={() => onEdit(1)}>
              Edit
            </button>
          </dd>
        </div>
        <div>
          <dt>Theme · Audience</dt>
          <dd>
            {theme} · {audience}{" "}
            <button type="button" className="link-button" onClick={() => onEdit(1)}>
              Edit
            </button>
          </dd>
        </div>
        <div>
          <dt>Brand</dt>
          <dd className={handle ? undefined : "is-empty"}>
            {handle || "No watermark"}{" "}
            <button type="button" className="link-button" onClick={() => onEdit(2)}>
              Edit
            </button>
          </dd>
        </div>
      </dl>
      {step === 2 && (
        <p className={ready ? "status-running" : "status-failed"}>
          {ready
            ? "Footage covers the track — ready to launch."
            : "Check footage vs. track length before launching."}
        </p>
      )}
    </aside>
  );
}
