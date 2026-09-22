import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fileUrl, reelUrl } from "../api";
import { isDisplayableImage } from "../components/mediaMeta";
import type { MediaEntry, SessionListEntry } from "../types";

function formatSecs(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  return `${m}m${Math.round(s % 60)}s`;
}

function clipSecs(c: MediaEntry): number {
  if (c.duration_s != null) return c.duration_s;
  return c.kind === "image" ? 3 : 0;
}

function dimsLabel(c: MediaEntry): string {
  if (c.w == null || c.h == null) return "";
  const orient = c.w === c.h ? "square" : c.h > c.w ? "portrait" : "landscape";
  return `${c.w}×${c.h} ${orient}`;
}

export default function Index() {
  const [sessions, setSessions] = useState<SessionListEntry[] | null>(null);
  const [clips, setClips] = useState<MediaEntry[] | null>(null);
  const [trackCount, setTrackCount] = useState(0);

  useEffect(() => {
    api.listSessions().then(setSessions);
    api
      .getMedia()
      .then((lib) => {
        setClips(lib.clips);
        setTrackCount(lib.music.length);
      })
      .catch(() => {
        setClips([]);
        setTrackCount(0);
      });
  }, []);

  const reelCount = sessions?.filter((s) => s.reel_exists).length ?? 0;
  const footageSecs = (clips ?? []).reduce((acc, c) => acc + clipSecs(c), 0);

  return (
    <>
      <h2>Cutting bench</h2>
      <p className="dashboard-stats">
        {sessions === null || clips === null ? (
          "Loading…"
        ) : (
          <>
            {sessions.length} sessions · {reelCount} reels · {clips.length} clips (~
            {formatSecs(footageSecs)} footage) · {trackCount} tracks ·{" "}
            <Link to="/new">+ New session</Link>
          </>
        )}
      </p>

      {clips !== null && clips.length > 0 && (
        <section aria-label="Recent media">
          <h3>Recent media</h3>
          <div className="contact-sheet contact-sheet--compact">
            {clips.slice(0, 8).map((c) => (
              <figure key={`${c.session}/${c.path}`}>
                {c.kind === "image" && !isDisplayableImage(c.filename) ? (
                  <div className="media-placeholder" aria-hidden="true">
                    still
                  </div>
                ) : c.kind === "image" ? (
                  <img src={fileUrl(c.session, c.path)} alt={c.filename} loading="lazy" />
                ) : (
                  <video muted preload="metadata" src={fileUrl(c.session, c.path)} />
                )}
                <figcaption>
                  {c.filename} · {c.duration_s != null ? formatSecs(c.duration_s) : "still"}
                  {dimsLabel(c) && ` · ${dimsLabel(c)}`}
                </figcaption>
              </figure>
            ))}
          </div>
          <p>
            <Link to="/new">Pick clips for a new session →</Link>
          </p>
        </section>
      )}

      <section aria-label="Sessions">
        <h3>Sessions</h3>
        <table className="session-list">
          <thead>
            <tr>
              <th>Session</th>
              <th className="num">Clips</th>
              <th>Music</th>
              <th className="num">Cost</th>
              <th>Updated</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {sessions === null ? (
              <tr>
                <td colSpan={6}>Loading…</td>
              </tr>
            ) : sessions.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  No sessions yet. <Link to="/new">Start one</Link> — drop clips plus a music track
                  and the bench cuts the reel.
                </td>
              </tr>
            ) : (
              sessions.map((s) => (
                <tr key={s.name}>
                  <td>
                    {s.reel_exists && (
                      <video
                        className="session-reel-thumb"
                        muted
                        preload="metadata"
                        src={`${reelUrl(s.name)}#t=0.1`}
                      />
                    )}
                    <Link to={`/sessions/${s.name}`}>{s.name}</Link>
                  </td>
                  <td className="num">{s.clip_count}</td>
                  <td>{s.music_name || "—"}</td>
                  <td className="num">${s.total_cost_usd.toFixed(4)}</td>
                  <td>{new Date(s.mtime * 1000).toLocaleDateString()}</td>
                  <td className={`status-${s.status}`}>{s.status}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
