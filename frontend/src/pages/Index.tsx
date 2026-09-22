import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, fileUrl, reelUrl } from "../api";
import LibraryPreview from "../components/LibraryPreview";
import TrackPlayer from "../components/TrackPlayer";
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

const CLIP_SHOWN = 10;
const TRACK_SHOWN = 4;

function newestOf(clips: MediaEntry[], music: MediaEntry[]): MediaEntry | null {
  const c = clips[0] ?? null;
  const m = music[0] ?? null;
  if (c && m) return m.mtime > c.mtime ? m : c;
  return c ?? m;
}

function entryRef(e: MediaEntry): string {
  return `${e.session}/${e.path}`;
}

export default function Index() {
  const [sessions, setSessions] = useState<SessionListEntry[] | null>(null);
  const [clips, setClips] = useState<MediaEntry[] | null>(null);
  const [music, setMusic] = useState<MediaEntry[] | null>(null);
  const [preview, setPreview] = useState<MediaEntry | null>(null);
  const [allClips, setAllClips] = useState(false);
  const [allTracks, setAllTracks] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [libError, setLibError] = useState<string | null>(null);

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

  async function refreshLibrary() {
    const [freshSessions, lib] = await Promise.all([api.listSessions(), api.getMedia()]);
    setSessions(freshSessions);
    setClips(lib.clips);
    setMusic(lib.music);
  }

  async function handleDeleteSelected() {
    const refs = [...selected];
    if (refs.length === 0) return;
    const ok = window.confirm(
      `Delete ${refs.length} selected file${refs.length === 1 ? "" : "s"}? This unlinks ` +
        `each file, removes it from its manifest, and clears downstream results so the ` +
        `next run rebuilds. This cannot be undone.`,
    );
    if (!ok) return;
    setBulkDeleting(true);
    setLibError(null);
    const failed: string[] = [];
    for (const ref of refs) {
      try {
        await api.deleteMedia(ref);
      } catch (err) {
        failed.push(`${ref}: ${err instanceof ApiError ? err.detail : "Delete failed."}`);
      }
    }
    if (preview && selected.has(entryRef(preview))) setPreview(null);
    setSelected(new Set());
    try {
      await refreshLibrary();
    } catch {
      setLibError("Deleted, but refreshing the library failed — reload the page.");
    } finally {
      setBulkDeleting(false);
    }
    if (failed.length > 0) {
      setLibError(
        `Deleted ${refs.length - failed.length} of ${refs.length}. ` +
          `Failed: ${failed.join("; ")}`,
      );
    }
  }

  function toggleSelect(ref: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });
  }

  function selectAll() {
    const all = new Set<string>();
    for (const c of clips ?? []) all.add(entryRef(c));
    for (const m of music ?? []) all.add(entryRef(m));
    setSelected(all);
  }

  async function handleDelete(entry: MediaEntry) {
    const ref = entryRef(entry);
    const ok = window.confirm(
      `Delete ${entry.filename} from session ${entry.session}? This unlinks the file, ` +
        `removes it from the manifest, and clears downstream results so the next run ` +
        `rebuilds. This cannot be undone.`,
    );
    if (!ok) return;
    setDeleting(ref);
    setLibError(null);
    try {
      await api.deleteMedia(ref);
      if (preview && entryRef(preview) === ref) setPreview(null);
      await refreshLibrary();
    } catch (err) {
      setLibError(err instanceof ApiError ? err.detail : "Delete failed.");
    } finally {
      setDeleting(null);
    }
  }

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
        {libError && <p className="status-failed">{libError}</p>}
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

            <p>
              <button type="button" onClick={selectAll}>
                Select all
              </button>{" "}
              <button
                type="button"
                onClick={() => setSelected(new Set())}
                disabled={selected.size === 0}
              >
                Clear
              </button>{" "}
              {selected.size > 0 && (
                <button
                  type="button"
                  onClick={() => void handleDeleteSelected()}
                  disabled={bulkDeleting}
                >
                  {bulkDeleting ? "Deleting…" : `Delete selected (${selected.size})`}
                </button>
              )}
            </p>

            {clips.length > 0 && (
              <>
                <h4>Clips</h4>
                <div className="contact-sheet contact-sheet--compact">
                  {(allClips ? clips : clips.slice(0, CLIP_SHOWN)).map((c) => (
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
                        <label>
                          <input
                            type="checkbox"
                            checked={selected.has(`${c.session}/${c.path}`)}
                            onChange={() => toggleSelect(`${c.session}/${c.path}`)}
                            disabled={bulkDeleting}
                            aria-label={`Select ${c.filename}`}
                          />
                          {c.filename} · {c.session} · {formatAge(c.mtime)}
                        </label>
                        <br />
                        <button
                          type="button"
                          onClick={() => void handleDelete(c)}
                          disabled={deleting === `${c.session}/${c.path}` || bulkDeleting}
                          aria-label={`Delete ${c.filename} from ${c.session}`}
                        >
                          {deleting === `${c.session}/${c.path}` ? "Deleting…" : "Delete"}
                        </button>
                      </figcaption>
                    </figure>
                  ))}
                </div>
                {clips.length > CLIP_SHOWN && (
                  <p>
                    <button type="button" onClick={() => setAllClips((v) => !v)}>
                      {allClips ? "Show less" : `Show all ${clips.length} clips`}
                    </button>
                  </p>
                )}
              </>
            )}

            {music.length > 0 && (
              <>
                <h4>Tracks</h4>
                <ul className="media-list library-tracks">
                  {(allTracks ? music : music.slice(0, TRACK_SHOWN)).map((m) => (
                    <li key={`${m.session}/${m.path}`}>
                      <span className="track-meta">
                        <label>
                          <input
                            type="checkbox"
                            checked={selected.has(`${m.session}/${m.path}`)}
                            onChange={() => toggleSelect(`${m.session}/${m.path}`)}
                            disabled={bulkDeleting}
                            aria-label={`Select ${m.filename}`}
                          />
                          {m.filename} · {formatSize(m.size)} · {m.session} · {formatAge(m.mtime)}
                        </label>
                      </span>
                      <TrackPlayer
                        src={fileUrl(m.session, m.path)}
                        label={m.filename}
                        peaksRef={`${m.session}/${m.path}`}
                        durationHint={m.duration_s}
                      />
                      <button
                        type="button"
                        onClick={() => void handleDelete(m)}
                        disabled={deleting === `${m.session}/${m.path}` || bulkDeleting}
                        aria-label={`Delete ${m.filename} from ${m.session}`}
                      >
                        {deleting === `${m.session}/${m.path}` ? "Deleting…" : "Delete"}
                      </button>
                    </li>
                  ))}
                </ul>
                {music.length > TRACK_SHOWN && (
                  <p>
                    <button type="button" onClick={() => setAllTracks((v) => !v)}>
                      {allTracks ? "Show less" : `Show all ${music.length} tracks`}
                    </button>
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
