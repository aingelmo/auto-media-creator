import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Hooks as HooksPayload } from "../types";

export default function Hooks() {
  const { name = "" } = useParams();
  const [hooks, setHooks] = useState<HooksPayload | null>(null);

  useEffect(() => {
    api.getHooks(name).then(setHooks);
  }, [name]);

  if (!hooks) return <p>Loading&hellip;</p>;

  return (
    <>
      <h2>
        <Link to={`/sessions/${name}`}>{name}</Link> &mdash; hooks
      </h2>
      {hooks.hook_line && <p>chosen: {hooks.hook_line}</p>}
      {hooks.evidence && hooks.evidence.length > 0 && (
        <p>
          evidence: {hooks.evidence.join(", ")} (source: {hooks.source})
        </p>
      )}
      {hooks.rejected && <p className="status-failed">rejected: {hooks.rejected}</p>}
      {hooks.hooks.map((h, i) => (
        <div key={i}>
          <h3>[{h.angle}]</h3>
          <p>{h.hook_line}</p>
        </div>
      ))}
      {hooks.dropped !== undefined && (
        <details>
          <summary>dropped</summary>
          <pre>{JSON.stringify(hooks.dropped, null, 2)}</pre>
        </details>
      )}
    </>
  );
}
