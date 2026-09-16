import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { SessionListEntry } from "../types";

export default function Index() {
  const [sessions, setSessions] = useState<SessionListEntry[] | null>(null);

  useEffect(() => {
    api.listSessions().then(setSessions);
  }, []);

  return (
    <>
      <p>
        <Link to="/new">+ New session</Link>
      </p>
      <table className="session-list">
        <thead>
          <tr>
            <th>Session</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {sessions === null ? (
            <tr>
              <td colSpan={2}>Loading&hellip;</td>
            </tr>
          ) : sessions.length === 0 ? (
            <tr>
              <td colSpan={2}>No sessions yet.</td>
            </tr>
          ) : (
            sessions.map((s) => (
              <tr key={s.name}>
                <td>
                  <Link to={`/sessions/${s.name}`}>{s.name}</Link>
                </td>
                <td className={`status-${s.status}`}>{s.status}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </>
  );
}
