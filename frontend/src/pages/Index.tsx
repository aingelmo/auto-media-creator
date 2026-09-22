import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fileUrl, reelUrl } from "../api";
import LibraryPreview from "../components/LibraryPreview";
import { isDisplayableImage } from "../components/mediaMeta";
import {
  clipSecs,
  dimsLabel,
  durationLabel,
  extOf,
  formatAge,
  formatSecs,
  formatSize,
} from "../components/mediaMeta";
import type { MediaEntry, SessionListEntry } from "../types";

const CLIP_SHOWN = 8;
const TRACK_SHOWN = 4;

function newestOf(clips: MediaEntry[], music: MediaEntry[]): MediaEntry | null {
  const c = clips[0] ?? null;
  const m = music[0] ?? null;
  if (c && m) return m.mtime > c.mtime ? m : c;
  return c ?? m;
}

export default function Index() {
  const [sessions, setSessions] = useState<SessionListEntry[] | null>(null);
  const [clips, setClips] = useState<MediaEntry[] | null>(null);
  const [music, setMusic] = useState<MediaEntry[] | null>(null);
  const [preview, setPreview] = useState<MediaEntry | null>(null);

  useEffect(() => {
    api.listSessions().then(setSessions);
    api
      .getMedia()
      .then((lib) => {
        setClips(lib.clips);
        setMusic(lib.music);
      })
      .catch(() => {
        setClips([]);
        setMusic([]);
      });
  }, []);

  const reelCount = sessions?.filter((s) => s.reel_exists).length ?? 0;
  const footageSecs = (clips ?? []).reduce((acc, c) => acc + clipSecs(c), 0);
  const videoCount = (clips ?? []).filter((c) => c.kind === "video").length;
  const stillCount = (clips ?? []).filter((c) => c.kind === "image").length;
  const trackCount = music?.length ?? 0;
  const newest = clips && music ? newestOf(clips, music) : null;

  return (
    <>
      <h2>Cutting bench</h2>
      <p className="dashboard-stats">
        {sessions === null || clips === null || music === null ? (
          "Loading…"
        ) : (
          <>
            {sessions.length} sessions · {reelCount} reels · {clips.length} clips (~
            {formatSecs(footageSecs)} footage) · {trackCount} tracks ·{" "}
            <Link to="/new">+ New session</Link>
          </>
        )}
      </p>

      <section aria-label="Library">
        <h3>Library</h3>
        {clips === null || music === null ? (
          <p>Loading…</p>
        ) : clips.length === 0 && music.length === 0 ? (
          <p>
            No library yet. <Link to="/new">Start a session</Link> — drop clips plus a music track
            and the bench cuts the reel.
          </p>
        ) : (
          <>
            <p className="library-summary">
              {videoCount} videos + {stillCount} stills ≈ {formatSecs(footageSecs)} footage ·{" "}
              {trackCount} tracks
              {newest && (
                <>
                  {" "}
                  · newest: {newest.filename} from {newest.session}, {formatAge(newest.mtime)}
                </>
              )}
            </p>

            {clips.length > 0 && (
              <>
                <h4>Clips</h4>
                <div className="contact-sheet contact-sheet--compact">
                  {clips.slice(0, CLIP_SHOWN).map((c) => (
                    <figure key={`${c.session}/${c.path}`}>
                      <button
                        type="button"
                        className="library-tile"
                        onClick={() => setPreview(c)}
                        title={`${c.filename} · ${durationLabel(c.duration_s, c.kind)}${dimsLabel(c.w, c.h) ? ` · ${dimsLabel(c.w, c.h)}` : ""} · ${formatSize(c.size)} — preview`}
                        aria-label={`Preview ${c.filename}`}
                      >
                        <span className="library-thumb" aria-hidden="true">
                          {c.kind === "image" && !isDisplayableImage(c.filename) ? (
                            <span className="media-placeholder">
                              {extOf(c.filename).slice(1).toUpperCase()} still
                            </span>
                          ) : c.kind === "image" ? (
                            <img src={fileUrl(c.session, c.path)} alt="" loading="lazy" />
                          ) : (
                            <video muted preload="metadata" src={fileUrl(c.session, c.path)} />
                          )}
                          <span className="library-badge">
                            {durationLabel(c.duration_s, c.kind)}
                          </span>
                        </span>
                      </button>
                      <figcaption>
                        {c.filename} · {c.session} · {formatAge(c.mtime)}
                      </figcaption>
                    </figure>
                  ))}
                </div>
                {clips.length > CLIP_SHOWN && (
                  <p className="library-more">
                    + {clips.length - CLIP_SHOWN} more in{" "}
                    <Link to="/new">the new-session picker</Link>
                  </p>
                )}
              </>
            )}

            {music.length > 0 && (
              <>
                <h4>Tracks</h4>
                <ul className="media-list library-tracks">
                  {music.slice(0, TRACK_SHOWN).map((m) => (
                    <li key={`${m.session}/${m.path}`}>
                      <span>
                        {m.filename} · {m.duration_s != null ? formatSecs(m.duration_s) : "—"} ·{" "}
                        {formatSize(m.size)} · {m.session} · {formatAge(m.mtime)}
                      </span>
                      <audio controls preload="none" src={fileUrl(m.session, m.path)} />
                    </li>
                  ))}
                </ul>
                {music.length > TRACK_SHOWN && (
                  <p className="library-more">
                    + {music.length - TRACK_SHOWN} more in{" "}
                    <Link to="/new">the new-session picker</Link>
                  </p>
                )}
              </>
            )}

            <p>
              <Link to="/new">Pick clips for a new session →</Link>
            </p>
          </>
        )}
      </section>
      {preview && <LibraryPreview clip={preview} onClose={() => setPreview(null)} />}

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
