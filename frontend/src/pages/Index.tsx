import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, fileUrl, previewUrl, reelUrl } from "../api";
import { useConfirm } from "../components/confirm";
import LibraryPreview from "../components/LibraryPreview";
import TrackPlayer from "../components/TrackPlayer";
import { basenameOf, fetchUsage, type UsageMap } from "../components/clipUsage";
import { isDisplayableImage } from "../components/mediaMeta";
import { durationLabel, extOf, formatAge, formatSize } from "../components/mediaMeta";
import { notifyTrashChanged } from "../trash";
import type { MediaEntry, SessionListEntry } from "../types";

const TRACK_SHOWN = 4;

const CLIP_CAP = 12;

const STATUS_ORDER: Record<SessionListEntry["status"], number> = {
  new: 0,
  running: 1,
  done: 2,
  failed: 3,
};

/**Tiles shown in the Clips preview bed: always whole grid rows. Column
 * capacity comes from the grid's live geometry (content width and column
 * gap from computed style, tile minimum from the same breakpoints as
 * CSS), so the count stays a multiple of the real column count at any
 * viewport width. Overflow waits behind "Show all N clips". */
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
  const [usage, setUsage] = useState<UsageMap | null>(null);
  const [usageSort, setUsageSort] = useState<"newest" | "most" | "least">("newest");
  const [unusedOnly, setUnusedOnly] = useState(false);
  const [sessionQuery, setSessionQuery] = useState("");
  const [sessionStatus, setSessionStatus] = useState<"all" | SessionListEntry["status"]>("all");
  const [reelOnly, setReelOnly] = useState(false);
  const [sessionSortKey, setSessionSortKey] = useState<
    "name" | "clips" | "music" | "cost" | "updated" | "status"
  >("updated");
  const [sessionSortDir, setSessionSortDir] = useState<"asc" | "desc">("desc");
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

  useEffect(() => {
    if (!sessions) return;
    let live = true;
    fetchUsage(
      sessions.map((s) => s.name),
      (name) => api.getPlanner(name),
    ).then((map) => {
      if (live) setUsage(map);
    });
    return () => {
      live = false;
    };
  }, [sessions]);

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

  function selectAllClips() {
    setSelected(new Set((clips ?? []).map((c) => entryRef(c))));
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
    const u = usage?.[c.filename] ?? usage?.[basenameOf(c.filename)] ?? null;
    const usageTitle =
      usage === null
        ? "Loading reuse…"
        : u
          ? `Used ×${u.count} in ${u.sessions.join(", ")}`
          : "Unused in any final reel yet";
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
            <span
              className={`library-badge library-badge--usage${u ? "" : " library-badge--unused"}`}
              title={usageTitle}
            >
              {usage === null ? "…" : u ? `×${u.count}` : "unused"}
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
  const videoCount = (clips ?? []).filter((c) => c.kind === "video").length;
  const stillCount = (clips ?? []).filter((c) => c.kind === "image").length;
  const trackCount = music?.length ?? 0;
  const clipCount = clips?.length ?? 0;

  const visibleClips = useMemo(() => {
    const list = [...(clips ?? [])];
    if (unusedOnly) {
      return list.filter((c) => {
        const u = usage?.[c.filename] ?? usage?.[basenameOf(c.filename)];
        return !u;
      });
    }
    if (usageSort === "most" || usageSort === "least") {
      const countOf = (c: MediaEntry): number => {
        if (usage == null) return 0;
        const key = c.filename in usage ? c.filename : basenameOf(c.filename);
        return usage[key]?.count ?? 0;
      };
      list.sort((a, b) =>
        usageSort === "most" ? countOf(b) - countOf(a) : countOf(a) - countOf(b),
      );
    }
    return list;
  }, [clips, usage, usageSort, unusedOnly]);

  function toggleSessionSort(key: typeof sessionSortKey) {
    if (key !== sessionSortKey) {
      setSessionSortKey(key);
      setSessionSortDir(key === "name" || key === "music" || key === "status" ? "asc" : "desc");
    } else {
      setSessionSortDir((d) => (d === "asc" ? "desc" : "asc"));
    }
  }

  const visibleSessions = useMemo(() => {
    const q = sessionQuery.trim().toLowerCase();
    const list = (sessions ?? []).filter((s) => {
      if (sessionStatus !== "all" && s.status !== sessionStatus) return false;
      if (reelOnly && !s.reel_exists) return false;
      if (q && !`${s.name} ${s.music_name}`.toLowerCase().includes(q)) return false;
      return true;
    });
    const dir = sessionSortDir === "asc" ? 1 : -1;
    list.sort((a, b) => {
      switch (sessionSortKey) {
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "clips":
          return (a.clip_count - b.clip_count) * dir;
        case "music":
          return (a.music_name || "").localeCompare(b.music_name || "") * dir;
        case "cost":
          return (a.total_cost_usd - b.total_cost_usd) * dir;
        case "status":
          return (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) * dir;
        case "updated":
        default:
          return (a.mtime - b.mtime) * dir;
      }
    });
    return list;
  }, [sessions, sessionQuery, sessionStatus, reelOnly, sessionSortKey, sessionSortDir]);

  const sessionsFiltered = sessions !== null && visibleSessions.length !== sessions.length;

  function clearSessionFilters() {
    setSessionQuery("");
    setSessionStatus("all");
    setReelOnly(false);
  }

  const previewUsage =
    preview != null
      ? (usage?.[preview.filename] ?? usage?.[basenameOf(preview.filename)] ?? null)
      : null;

  return (
    <>
      <h2>Cutting bench</h2>
      {sessions === null || clips === null || music === null ? (
        <p>Loading…</p>
      ) : (
        <div className="dashboard-cards">
          <div className="dashboard-card">
            <span className="dashboard-card-value">{sessions.length}</span>
            <span className="dashboard-card-label">Sessions</span>
          </div>
          <div className="dashboard-card">
            <span className="dashboard-card-value">{reelCount}</span>
            <span className="dashboard-card-label">Reels</span>
          </div>
          <div className="dashboard-card" title={`${videoCount} videos + ${stillCount} stills`}>
            <span className="dashboard-card-value">{clipCount}</span>
            <span className="dashboard-card-label">Clips</span>
          </div>
          <div className="dashboard-card">
            <span className="dashboard-card-value">{trackCount}</span>
            <span className="dashboard-card-label">Tracks</span>
          </div>
          <Link to="/new" className="dashboard-new">
            + New session
          </Link>
        </div>
      )}

      <section aria-label="Library">
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
            {clips.length > 0 && (
              <>
                <div className="library-clips-header">
                  <h3>
                    Clips <span className="library-count">{clips.length}</span>
                  </h3>
                  <div className="library-clips-tools">
                    <label>
                      Sort
                      <select
                        value={usageSort}
                        onChange={(e) =>
                          setUsageSort(e.target.value as "newest" | "most" | "least")
                        }
                        aria-label="Sort clips by reuse"
                      >
                        <option value="newest">newest</option>
                        <option value="most">most used</option>
                        <option value="least">least used</option>
                      </select>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={unusedOnly}
                        onChange={(e) => setUnusedOnly(e.target.checked)}
                      />
                      unused only
                    </label>
                  </div>
                </div>
                <div className="library-bulk-bar">
                  <button
                    type="button"
                    onClick={selectAllClips}
                    disabled={clips.length === 0 || bulkDeleting}
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelected(new Set())}
                    disabled={selected.size === 0}
                  >
                    Clear
                  </button>
                  {selected.size > 0 && (
                    <button
                      type="button"
                      className="danger-text"
                      onClick={() => void handleDeleteSelected()}
                      disabled={bulkDeleting}
                    >
                      {bulkDeleting ? "Deleting…" : `Delete selected (${selected.size})`}
                    </button>
                  )}
                </div>
                {visibleClips.length === 0 ? (
                  <p>Every clip has a final reel credit — clear “unused only” to browse all.</p>
                ) : (
                  <div ref={clipsGridRef} className="contact-sheet contact-sheet--compact">
                    {visibleClips.slice(0, clipShown).map((c) => renderClipTile(c))}
                  </div>
                )}
                {visibleClips.length > clipShown && (
                  <p className="library-more">
                    <button type="button" onClick={() => setClipsOpen(true)} aria-haspopup="dialog">
                      {`Show all ${visibleClips.length} clips`}
                    </button>
                  </p>
                )}
                {clipsOpen && (
                  <dialog
                    ref={clipsDialogRef}
                    className="library-modal library-modal--wide"
                    aria-label={`All ${visibleClips.length} clips`}
                    onClose={() => setClipsOpen(false)}
                  >
                    <div className="library-modal-header">
                      <strong>{`All ${visibleClips.length} clips`}</strong>
                      <form method="dialog">
                        <button type="submit" autoFocus aria-label="Close clips viewer">
                          ✕
                        </button>
                      </form>
                    </div>
                    <div className="library-modal-tools">
                      <div className="library-clips-tools">
                        <label>
                          Sort
                          <select
                            value={usageSort}
                            onChange={(e) =>
                              setUsageSort(e.target.value as "newest" | "most" | "least")
                            }
                            aria-label="Sort clips in viewer by reuse"
                          >
                            <option value="newest">newest</option>
                            <option value="most">most used</option>
                            <option value="least">least used</option>
                          </select>
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={unusedOnly}
                            onChange={(e) => setUnusedOnly(e.target.checked)}
                          />
                          unused only
                        </label>
                      </div>
                    </div>
                    <div className="contact-sheet contact-sheet--compact">
                      {visibleClips.map((c) => renderClipTile(c))}
                    </div>
                  </dialog>
                )}
              </>
            )}

            {music.length > 0 && (
              <>
                <h3>Tracks</h3>
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
                  <p className="library-more">
                    <button
                      type="button"
                      onClick={() => setAllTracks((v) => !v)}
                      aria-expanded={allTracks}
                    >
                      {allTracks ? "Show less" : `Show all ${music.length} tracks`}
                    </button>
                  </p>
                )}
              </>
            )}
          </>
        )}
      </section>
      {preview && (
        <LibraryPreview
          clip={preview}
          usage={previewUsage}
          usageLoading={usage === null}
          onClose={() => setPreview(null)}
        />
      )}

      <section aria-label="Sessions">
        <div className="sessions-header">
          <h3>
            Sessions{" "}
            {sessions !== null && sessions.length > 0 && (
              <span className="library-count">{visibleSessions.length}</span>
            )}
          </h3>
          {sessions !== null && sessions.length > 0 && (
            <div className="sessions-tools">
              <label className="sessions-search">
                <span className="visually-hidden">Search sessions</span>
                <input
                  type="search"
                  value={sessionQuery}
                  onChange={(e) => setSessionQuery(e.target.value)}
                  placeholder="Search name or track…"
                  aria-label="Search sessions by name or track"
                />
              </label>
              <label>
                Status
                <select
                  value={sessionStatus}
                  onChange={(e) => setSessionStatus(e.target.value as typeof sessionStatus)}
                  aria-label="Filter sessions by status"
                >
                  <option value="all">all</option>
                  <option value="new">new</option>
                  <option value="running">running</option>
                  <option value="done">done</option>
                  <option value="failed">failed</option>
                </select>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={reelOnly}
                  onChange={(e) => setReelOnly(e.target.checked)}
                />
                reel ready
              </label>
              {sessionsFiltered && (
                <button type="button" onClick={clearSessionFilters}>
                  Clear
                </button>
              )}
            </div>
          )}
        </div>
        {sessions !== null && sessionsFiltered && (
          <p className="sessions-count" aria-live="polite">
            Showing {visibleSessions.length} of {sessions.length} sessions
          </p>
        )}
        <div className="table-scroll">
          <table className="session-list">
            <thead>
              <tr>
                <th
                  aria-sort={
                    sessionSortKey === "name"
                      ? sessionSortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="th-sort"
                    onClick={() => toggleSessionSort("name")}
                    aria-label={`Sort by session name, currently ${sessionSortKey === "name" ? sessionSortDir : "unsorted"}`}
                  >
                    Session
                    <span
                      className={`sort-mark${sessionSortKey === "name" ? ` is-active is-${sessionSortDir}` : ""}`}
                      aria-hidden="true"
                    />
                  </button>
                </th>
                <th
                  className="num"
                  aria-sort={
                    sessionSortKey === "clips"
                      ? sessionSortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="th-sort th-sort--num"
                    onClick={() => toggleSessionSort("clips")}
                    aria-label={`Sort by clip count, currently ${sessionSortKey === "clips" ? sessionSortDir : "unsorted"}`}
                  >
                    Clips
                    <span
                      className={`sort-mark${sessionSortKey === "clips" ? ` is-active is-${sessionSortDir}` : ""}`}
                      aria-hidden="true"
                    />
                  </button>
                </th>
                <th
                  aria-sort={
                    sessionSortKey === "music"
                      ? sessionSortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="th-sort"
                    onClick={() => toggleSessionSort("music")}
                    aria-label={`Sort by music, currently ${sessionSortKey === "music" ? sessionSortDir : "unsorted"}`}
                  >
                    Music
                    <span
                      className={`sort-mark${sessionSortKey === "music" ? ` is-active is-${sessionSortDir}` : ""}`}
                      aria-hidden="true"
                    />
                  </button>
                </th>
                <th
                  className="num"
                  aria-sort={
                    sessionSortKey === "cost"
                      ? sessionSortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="th-sort th-sort--num"
                    onClick={() => toggleSessionSort("cost")}
                    aria-label={`Sort by cost, currently ${sessionSortKey === "cost" ? sessionSortDir : "unsorted"}`}
                  >
                    Cost
                    <span
                      className={`sort-mark${sessionSortKey === "cost" ? ` is-active is-${sessionSortDir}` : ""}`}
                      aria-hidden="true"
                    />
                  </button>
                </th>
                <th
                  aria-sort={
                    sessionSortKey === "updated"
                      ? sessionSortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="th-sort"
                    onClick={() => toggleSessionSort("updated")}
                    aria-label={`Sort by updated, currently ${sessionSortKey === "updated" ? sessionSortDir : "unsorted"}`}
                  >
                    Updated
                    <span
                      className={`sort-mark${sessionSortKey === "updated" ? ` is-active is-${sessionSortDir}` : ""}`}
                      aria-hidden="true"
                    />
                  </button>
                </th>
                <th
                  aria-sort={
                    sessionSortKey === "status"
                      ? sessionSortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    className="th-sort"
                    onClick={() => toggleSessionSort("status")}
                    aria-label={`Sort by status, currently ${sessionSortKey === "status" ? sessionSortDir : "unsorted"}`}
                  >
                    Status
                    <span
                      className={`sort-mark${sessionSortKey === "status" ? ` is-active is-${sessionSortDir}` : ""}`}
                      aria-hidden="true"
                    />
                  </button>
                </th>
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
              ) : visibleSessions.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    No sessions match these filters.{" "}
                    <button type="button" className="danger-text" onClick={clearSessionFilters}>
                      Clear search and filters
                    </button>
                  </td>
                </tr>
              ) : (
                visibleSessions.map((s) => (
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
                    <td title={new Date(s.mtime * 1000).toLocaleString()}>{formatAge(s.mtime)}</td>
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
