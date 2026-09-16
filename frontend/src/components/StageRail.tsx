import { Link } from "react-router-dom";
import { fileUrl } from "../api";
import type { StageName, StageStatus } from "../types";

const STAGE_ROUTES: Partial<Record<StageName, string>> = {
  ingest: "ingest",
  candidates: "candidates",
  selection: "selection",
  planner: "planner",
};

/** `(n/m)` in a stage's detail text drives its progress bar, e.g. "encoding (12/19)". */
const PROGRESS_RE = /\((\d+)\/(\d+)\)/;

function StageLink({
  name,
  stage,
}: {
  name: string;
  stage: StageName;
}) {
  if (stage === "hooks") {
    return (
      <a href={fileUrl(name, "hooks.json")}>
        view
      </a>
    );
  }
  const route = STAGE_ROUTES[stage];
  if (!route) return null;
  return <Link to={`/sessions/${name}/${route}`}>view</Link>;
}

export default function StageRail({
  name,
  stages,
  stageStatuses,
  detail,
}: {
  name: string;
  stages: readonly StageName[];
  stageStatuses: Record<StageName, StageStatus>;
  detail?: Record<StageName, string>;
}) {
  return (
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
              {(status === "done" || status === "failed") && (
                <>
                  {" — "}
                  <StageLink name={name} stage={s} />
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
}
