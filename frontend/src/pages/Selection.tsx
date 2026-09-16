import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { SelectionAttempt } from "../types";

export default function Selection() {
  const { name = "" } = useParams();
  const [attempts, setAttempts] = useState<SelectionAttempt[] | null>(null);

  useEffect(() => {
    api.getSelection(name).then((p) => setAttempts(p.attempts));
  }, [name]);

  if (!attempts) return <p>Loading&hellip;</p>;

  return (
    <>
      <h2>
        <Link to={`/sessions/${name}`}>{name}</Link> &mdash; selection
      </h2>
      {attempts.map((a) => (
        <div key={a.attempt}>
          <h3>
            Attempt {a.attempt} &mdash; {a.status}
          </h3>
          <p>
            usage: {JSON.stringify(a.usage)} &mdash; cost_usd: {a.cost_usd}
          </p>
          {a.error && <p className="status-failed">{a.error}</p>}
          <details>
            <summary>Prompt sent</summary>
            <h4>System</h4>
            <pre>{a.system_prompt}</pre>
            <h4>User</h4>
            <pre>{a.user_prompt}</pre>
          </details>
          {a.output !== undefined && (
            <>
              <h4>Output</h4>
              <pre>{JSON.stringify(a.output, null, 2)}</pre>
            </>
          )}
        </div>
      ))}
    </>
  );
}
