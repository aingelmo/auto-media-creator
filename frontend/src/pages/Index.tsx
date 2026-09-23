import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, fileUrl, previewUrl, reelUrl } from "../api";
import { useConfirm } from "../components/confirm";
import LibraryPreview from "../components/LibraryPreview";
import TrackPlayer from "../components/TrackPlayer";
import { isDisplayableImage } from "../components/mediaMeta";
import {
  clipSecs,
  durationLabel,
  extOf,
  formatAge,
  formatSecs,
  formatSize,
} from "../components/mediaMeta";
import { notifyTrashChanged } from "../trash";
import type { MediaEntry, SessionListEntry } from "../types";

const TRACK_SHOWN = 4;

const CLIP_CAP = 12;

/**Tiles shown in the Clips preview bed: always whole grid rows. Column
 * capacity comes from the grid's live geometry (content width and column
 * gap from computed style, tile minimum from the same breakpoints as
 * CSS), so the count stays a multiple of the real column count at any
 * viewport width. Overflow waits behind "Browse all N clips". */
function useClipPageSize(gridRef: React.RefObject<HTMLDivElement | null>, total: number): number {
  const [shown, setShown] = useState(Math.min(total, 8));
  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el || total <= 0) return;
    const compute = () => {
      const cs = getComputedStyle(el);
      const gap = parseFloat(cs.columnGap) || 0;
      const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
      const content = Math.max(0, el.clientWidth - pad);
      const vw = window.innerWidth;
      const minTile = vw >= 1400 ? 132 : vw <= 640 ? 96 : 110;
      const cols = Math.max(1, Math.floor((content + gap) / (minTile + gap)));
      // Whole rows only, so no half-filled trailing row leaves a blank
      // slab. Fewer clips than columns fill one auto-fit-stretched row.
      setShown(
        total <= cols ? total : Math.max(1, Math.floor(Math.min(total, CLIP_CAP) / cols)) * cols,
      );
    };
    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, [gridRef, total]);
  return shown;
}

/**True on touch-first screens: clip tiles defer video bytes until tapped. */
function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(
    () => window.matchMedia?.("(pointer: coarse)").matches ?? false,
  );
  useEffect(() => {
    const mq = window.matchMedia("(pointer: coarse)");
    const onChange = () => setCoarse(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return coarse;
}

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
  const [clipsOpen, setClipsOpen] = useState(false);
  const [allTracks, setAllTracks] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [deletingSession, setDeletingSession] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [libError, setLibError] = useState<string | null>(null);
  const clipsDialogRef = useRef<HTMLDialogElement>(null);
  const clipsGridRef = useRef<HTMLDivElement>(null);
  const clipShown = useClipPageSize(clipsGridRef, clips?.length ?? 0);
  const coarsePointer = useCoarsePointer();
  const confirm = useConfirm();

  useEffect(() => {
    if (!clipsOpen) return;
    const dialog = clipsDialogRef.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
    };
  }, [clipsOpen]);

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
    const count = refs.length;
    const ok = await confirm({
      title: `Move ${count} file${count === 1 ? "" : "s"} to the trash?`,
      body: (
        <>
          <p>
            Each file leaves its session's library and manifest, and downstream results clear so the
            next run rebuilds.
          </p>
          <p className="confirm-note">Moves to Trash · restorable for 30 days.</p>
        </>
      ),
      confirmLabel: `Move ${count} to trash`,
      tone: "danger",
    });
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
    notifyTrashChanged();
    try {
      await refreshLibrary();
    } catch {
      setLibError("Moved, but refreshing the library failed — reload the page.");
    } finally {
      setBulkDeleting(false);
    }
    if (failed.length > 0) {
      setLibError(`Moved ${count - failed.length} of ${count}. Failed: ${failed.join("; ")}`);
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
    const ok = await confirm({
      title: `Move ${entry.filename} to the trash?`,
      body: (
        <>
          <p>
            It leaves session {entry.session}'s library and manifest, and downstream results clear
            so the next run rebuilds.
          </p>
          <p className="confirm-note">Moves to Trash · restorable for 30 days.</p>
        </>
      ),
      confirmLabel: "Move to trash",
      tone: "danger",
    });
    if (!ok) return;
    setDeleting(ref);
    setLibError(null);
    try {
      await api.deleteMedia(ref);
      if (preview && entryRef(preview) === ref) setPreview(null);
      notifyTrashChanged();
      await refreshLibrary();
    } catch (err) {
      setLibError(err instanceof ApiError ? err.detail : "Delete failed.");
    } finally {
      setDeleting(null);
    }
  }

  async function handleDeleteSession(session: SessionListEntry) {
    const ok = await confirm({
      title: `Move ${session.name} to the trash?`,
      body: (
        <>
          <p>
            The whole session — {session.clip_count} clip
            {session.clip_count === 1 ? "" : "s"}, its reel, and its cost ledger — leaves the bench.
          </p>
          <p className="confirm-note">Moves to Trash · restorable for 30 days.</p>
        </>
      ),
      confirmLabel: "Move to trash",
      tone: "danger",
    });
    if (!ok) return;
    setDeletingSession(session.name);
    setLibError(null);
    try {
      await api.deleteSession(session.name);
      notifyTrashChanged();
      await refreshLibrary();
    } catch (err) {
      setLibError(err instanceof ApiError ? err.detail : "Could not move the session.");
    } finally {
      setDeletingSession(null);
    }
  }

  function renderClipTile(c: MediaEntry) {
    return (
      <figure key={`${c.session}/${c.path}`}>
        <button
          type="button"
          className="library-tile"
          onClick={() => setPreview(c)}
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
              <video muted preload={coarsePointer ? "none" : "metadata"} src={previewUrl(c)} />
            )}
            <span className="library-badge">{durationLabel(c.duration_s, c.kind)}</span>
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
            {c.filename} · {formatAge(c.mtime)}
          </label>
          <button
            type="button"
            className="tile-delete"
            onClick={() => void handleDelete(c)}
            disabled={deleting === `${c.session}/${c.path}` || bulkDeleting}
            aria-label={`Delete ${c.filename} from ${c.session}`}
          >
            {deleting === `${c.session}/${c.path}` ? "…" : "✕"}
          </button>
        </figcaption>
      </figure>
    );
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
                <div ref={clipsGridRef} className="contact-sheet contact-sheet--compact">
                  {clips.slice(0, clipShown).map((c) => renderClipTile(c))}
                </div>
                {clips.length > clipShown && (
                  <p>
                    <button type="button" className="primary" onClick={() => setClipsOpen(true)}>
                      {`Browse all ${clips.length} clips`}
                    </button>
                  </p>
                )}
                {clipsOpen && (
                  <dialog
                    ref={clipsDialogRef}
                    className="library-modal library-modal--wide"
                    aria-label={`All ${clips.length} clips`}
                    onClose={() => setClipsOpen(false)}
                  >
                    <div className="library-modal-header">
                      <strong>{`All ${clips.length} clips`}</strong>
                      <form method="dialog">
                        <button type="submit" autoFocus aria-label="Close clips viewer">
                          ✕
                        </button>
                      </form>
                    </div>
                    <div className="contact-sheet contact-sheet--compact">
                      {clips.map((c) => renderClipTile(c))}
                    </div>
                  </dialog>
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
                          {m.filename} · {formatSize(m.size)} · {formatAge(m.mtime)}
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
        <div className="table-scroll">
          <table className="session-list">
            <thead>
              <tr>
                <th>Session</th>
                <th className="num">Clips</th>
                <th>Music</th>
                <th className="num">Cost</th>
                <th>Updated</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {sessions === null ? (
                <tr>
                  <td colSpan={7}>Loading…</td>
                </tr>
              ) : sessions.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    No sessions yet. <Link to="/new">Start one</Link> — drop clips plus a music
                    track and the bench cuts the reel.
                  </td>
                </tr>
              ) : (
                sessions.map((s) => (
                  <tr key={s.name}>
                    <td>
                      {s.reel_exists && (
                        <video
                          aria-hidden="true"
                          tabIndex={-1}
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
                    <td className="session-actions-cell">
                      <button
                        type="button"
                        className="danger-text session-trash"
                        onClick={() => void handleDeleteSession(s)}
                        disabled={deletingSession === s.name}
                        aria-label={`Move ${s.name} to the trash`}
                      >
                        {deletingSession === s.name ? "…" : "Trash"}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
