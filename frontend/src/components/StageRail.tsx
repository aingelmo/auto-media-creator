import type { StageName, StageStatus } from "../types";

const VIEWABLE_STAGES: ReadonlySet<StageName> = new Set([
  "ingest",
  "candidates",
  "selection",
  "hooks",
  "planner",
] satisfies StageName[]);

/** `(n/m)` in a stage's detail text drives its progress bar, e.g. "encoding (12/19)". */
const PROGRESS_RE = /\((\d+)\/(\d+)\)/;

export default function StageRail({
  stages,
  stageStatuses,
  detail,
  onView,
}: {
  stages: readonly StageName[];
  stageStatuses: Record<StageName, StageStatus>;
  detail?: Record<StageName, string>;
  onView: (stage: StageName) => void;
}) {
  const list = (
    <ul className="stage-rail">
      {stages.map((s) => {
        const status = stageStatuses[s];
        const text = detail?.[s] ?? "";
        const progress = text.match(PROGRESS_RE);
        return (
          <li key={s} className={`status-${status}`}>
            <span className="stage-mark" aria-hidden="true" />
            <span className="stage-name">{s}</span>
            <span className="stage-detail">
              {status}
              {text ? ` — ${text}` : ""}
              {(status === "done" || status === "failed") && VIEWABLE_STAGES.has(s) && (
                <>
                  {" — "}
                  <button type="button" className="link-button" onClick={() => onView(s)}>
                    view
                  </button>
                </>
              )}
            </span>
            {progress && Number(progress[2]) > 0 && (
              <progress max={Number(progress[2])} value={Number(progress[1])} />
            )}
          </li>
        );
      })}
    </ul>
  );

  // All done is the common, low-information state once a session is
  // revisited to iterate — collapse it so the video/regenerate form (what
  // you actually look at) isn't pushed down by 7 identical "done" rows.
  const allDone = stages.every((s) => stageStatuses[s] === "done");
  if (!allDone) return list;

  return (
    <details className="stage-rail-collapsed">
      <summary>
        pipeline done — {stages.length}/{stages.length} stages
      </summary>
      {list}
    </details>
  );
}
