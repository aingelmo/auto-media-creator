import { useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, previewUrl } from "../api";
import type { MediaEntry } from "../types";
import { basenameOf, fetchUsage, type UsageMap } from "./clipUsage";
import CoverageMeter from "./CoverageMeter";
import type { CreateStats } from "./CreateSummary";
import LibraryHoverVideo from "./LibraryHoverVideo";
import TrackPlayer from "./TrackPlayer";
import {
  IMAGE_FOOTAGE_S,
  clipSecs,
  dimsLabel,
  durationLabel,
  extOf,
  formatSize,
  isDisplayableImage,
} from "./mediaMeta";

const CLIP_PAGE = 24;
const MUSIC_PAGE = 20;
const CLIP_EXTS = [".mov", ".mp4", ".m4v", ".jpg", ".jpeg", ".png", ".heic", ".heif"];
const MUSIC_EXTS = [".mp3", ".wav", ".mp4", ".m4a"];
const IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".heic", ".heif"];

function fileKey(f: File): string {
  return `${f.name}:${f.size}:${f.lastModified}`;
}

function refOf(c: MediaEntry): string {
  return `${c.session}/${c.path}`;
}

function fileName(ref: string): string {
  return ref.split("/").pop() ?? ref;
}

interface UpMeta {
  dur: number | null;
  w: number | null;
  h: number | null;
}

function putInputFiles(input: HTMLInputElement | null, files: File[]) {
  if (!input) return;
  const dt = new DataTransfer();
  for (const f of files) dt.items.add(f);
  input.files = dt.files;
}

function dropFiles(list: FileList | File[], allowed: string[]): File[] {
  const out: File[] = [];
  for (const f of Array.from(list)) {
    if (allowed.includes(extOf(f.name))) out.push(f);
  }
  return out;
}

/** Clips left after the sort / "unused only" filter: the same list
 * the contact-sheet renders, so "Select all" picks what the user sees. */
function filteredClips(
  all: MediaEntry[],
  usage: UsageMap | null,
  usageSort: "newest" | "most" | "least",
  unusedOnly: boolean,
): MediaEntry[] {
  const list = [...all];
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
    list.sort((a, b) => (usageSort === "most" ? countOf(b) - countOf(a) : countOf(a) - countOf(b)));
  }
  return list;
}

/** Clips & music for the new-session form: library contact-sheet plus a
 * drag-drop zone for fresh uploads, with a live coverage meter on top. */
export default function MediaLibraryPicker({
  onClipsChange,
  onMusicChange,
  onStatsChange,
  initialClips = [],
  initialMusic = "",
}: {
  onClipsChange: (refs: string[]) => void;
  onMusicChange: (ref: string) => void;
  onStatsChange?: (stats: CreateStats) => void;
  initialClips?: string[];
  initialMusic?: string;
}) {
  const [clips, setClips] = useState<MediaEntry[]>([]);
  const [music, setMusic] = useState<MediaEntry[]>([]);
  const [selectedClips, setSelectedClips] = useState<Set<string>>(new Set(initialClips));
  const [selectedMusic, setSelectedMusic] = useState(initialMusic);
  const [uploadedClips, setUploadedClips] = useState<File[]>([]);
  const [uploadedMusic, setUploadedMusic] = useState<File | null>(null);
  const [upMeta, setUpMeta] = useState<Record<string, UpMeta>>({});
  const [upMusicDur, setUpMusicDur] = useState<number | null>(null);
  const [allClips, setAllClips] = useState(false);
  const [allMusic, setAllMusic] = useState(false);
  const [usage, setUsage] = useState<UsageMap | null>(null);
  const [usageSort, setUsageSort] = useState<"newest" | "most" | "least">("newest");
  const [unusedOnly, setUnusedOnly] = useState(false);
  const [dragClips, setDragClips] = useState(false);
  const [dragMusic, setDragMusic] = useState(false);
  const [dropNotice, setDropNotice] = useState<string | null>(null);
  const clipsInput = useRef<HTMLInputElement>(null);
  const musicInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .getMedia()
      .then((lib) => {
        setClips(lib.clips);
        setMusic(lib.music);
      })
      .catch(() => {});
    let live = true;
    api
      .listSessions()
      .then((sessions) =>
        // Skip `status === "new"` sessions (no `edl.json` yet):
        // avoids 404-spam in the console (see Index.tsx).
        fetchUsage(
          sessions.filter((s) => s.status !== "new").map((s) => s.name),
          (name) => api.getPlanner(name),
        ),
      )
      .then((map) => {
        if (live) setUsage(map);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const clipUrls = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of uploadedClips) m.set(fileKey(f), URL.createObjectURL(f));
    return m;
  }, [uploadedClips]);
  useEffect(
    () => () => {
      for (const u of clipUrls.values()) URL.revokeObjectURL(u);
    },
    [clipUrls],
  );
  const musicUrl = useMemo(
    () => (uploadedMusic ? URL.createObjectURL(uploadedMusic) : null),
    [uploadedMusic],
  );
  useEffect(
    () => () => {
      if (musicUrl) URL.revokeObjectURL(musicUrl);
    },
    [musicUrl],
  );

  function mergeClips(files: File[]) {
    const seen = new Set(uploadedClips.map(fileKey));
    const merged = [...uploadedClips];
    for (const f of files) {
      if (!seen.has(fileKey(f))) {
        seen.add(fileKey(f));
        merged.push(f);
      }
    }
    putInputFiles(clipsInput.current, merged);
    setUploadedClips(merged);
  }

  function removeClip(i: number) {
    const merged = uploadedClips.filter((_, j) => j !== i);
    putInputFiles(clipsInput.current, merged);
    setUploadedClips(merged);
  }

  function setMusicFile(f: File | null) {
    putInputFiles(musicInput.current, f ? [f] : []);
    setUploadedMusic(f);
    setUpMusicDur(null);
  }

  /** Browse handler for clips: the `accept` hint is advisory, so filter
   * here and say what was skipped instead of counting a file the
   * server will ignore. */
  function onClipsBrowse(files: FileList | null) {
    const incoming = Array.from(files ?? []);
    const kept = dropFiles(incoming, CLIP_EXTS);
    if (kept.length < incoming.length) {
      setDropNotice(
        `Skipped ${incoming.length - kept.length} file(s) — clips accept ${CLIP_EXTS.join(", ")}.`,
      );
    } else {
      setDropNotice(null);
    }
    putInputFiles(clipsInput.current, kept);
    setUploadedClips(kept);
  }

  /** Browse handler for music: reject unsupported formats at pick time
   * with the supported list, instead of failing after upload. */
  function onMusicBrowse(files: FileList | null) {
    const f = files?.[0] ?? null;
    if (f && !MUSIC_EXTS.includes(extOf(f.name))) {
      setDropNotice(
        `“${f.name}” isn't a supported track — music accepts ${MUSIC_EXTS.join(", ")}.`,
      );
      return;
    }
    setDropNotice(null);
    setMusicFile(f);
  }

  function recordClipMeta(key: string, dur: number | null, w: number | null, h: number | null) {
    setUpMeta((prev) => (prev[key] ? prev : { ...prev, [key]: { dur, w, h } }));
  }

  function toggleClip(ref: string) {
    const next = new Set(selectedClips);
    if (next.has(ref)) next.delete(ref);
    else next.add(ref);
    setSelectedClips(next);
    onClipsChange([...next]);
  }

  function selectAllClips() {
    const next = new Set(filteredClips(clips, usage, usageSort, unusedOnly).map(refOf));
    setSelectedClips(next);
    onClipsChange([...next]);
  }

  function clearClips() {
    setSelectedClips(new Set());
    onClipsChange([]);
  }

  function pickMusic(ref: string) {
    setSelectedMusic(ref);
    onMusicChange(ref);
  }

  const byRef = useMemo(() => new Map(clips.map((c) => [refOf(c), c])), [clips]);
  const musicByRef = useMemo(() => new Map(music.map((m) => [refOf(m), m])), [music]);

  const videoCount = clips.filter((c) => c.kind === "video").length;
  const stillCount = clips.filter((c) => c.kind === "image").length;

  const usedCount = useMemo(() => {
    if (usage == null) return null;
    let n = 0;
    for (const c of clips) {
      if (usage[c.filename] ?? usage[basenameOf(c.filename)]) n += 1;
    }
    return n;
  }, [clips, usage]);

  const visibleClips = useMemo(
    () => filteredClips(clips, usage, usageSort, unusedOnly),
    [clips, usage, usageSort, unusedOnly],
  );

  const libClipSecs = [...selectedClips].reduce((acc, r) => {
    const c = byRef.get(r);
    return acc + (c ? clipSecs(c) : 0);
  }, 0);
  const upClipSecs = uploadedClips.reduce((acc, f) => {
    const m = upMeta[fileKey(f)];
    if (m?.dur != null) return acc + m.dur;
    return acc + (IMAGE_EXTS.includes(extOf(f.name)) ? IMAGE_FOOTAGE_S : 0);
  }, 0);
  const musicEntry = selectedMusic ? musicByRef.get(selectedMusic) : undefined;
  const musicSecs = uploadedMusic ? upMusicDur : (musicEntry?.duration_s ?? null);
  const musicName = uploadedMusic?.name ?? (selectedMusic ? fileName(selectedMusic) : "");

  useEffect(() => {
    onStatsChange?.({
      clipCount: selectedClips.size + uploadedClips.length,
      clipSecs: libClipSecs + upClipSecs,
      musicName,
      musicSecs,
    });
  }, [selectedClips, uploadedClips, libClipSecs, upClipSecs, musicName, musicSecs, onStatsChange]);

  return (
    <div className="media-library-picker">
      <CoverageMeter
        clipCount={selectedClips.size + uploadedClips.length}
        clipSecs={libClipSecs + upClipSecs}
        musicName={uploadedMusic?.name ?? (selectedMusic ? fileName(selectedMusic) : "")}
        musicSecs={musicSecs}
      />
      {dropNotice && (
        <p className="warning is-error" role="alert">
          {dropNotice}
        </p>
      )}

      <fieldset>
        <legend>
          Clips / photos ({selectedClips.size} picked
          {uploadedClips.length > 0 && `, ${uploadedClips.length} uploaded`})
        </legend>
        <div
          className={`dropzone${dragClips ? " is-dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragClips(true);
          }}
          onDragLeave={() => setDragClips(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragClips(false);
            const incoming = Array.from(e.dataTransfer.files);
            const kept = dropFiles(incoming, CLIP_EXTS);
            if (kept.length < incoming.length) {
              setDropNotice(
                `Skipped ${incoming.length - kept.length} file(s) — clips accept ${CLIP_EXTS.join(", ")}.`,
              );
            } else {
              setDropNotice(null);
            }
            mergeClips(kept);
          }}
        >
          <div className="dropzone-empty">
            <p className="dropzone-hint">Drop clips / photos here or browse</p>
            <label className="dropzone-browse" htmlFor="new-clips">
              Browse files
            </label>
          </div>
          <input
            id="new-clips"
            ref={clipsInput}
            className="dropzone-input"
            type="file"
            name="clips"
            multiple
            accept={CLIP_EXTS.join(",")}
            onChange={(e) => onClipsBrowse(e.target.files)}
          />
        </div>

        {uploadedClips.length > 0 && (
          <div className="contact-sheet contact-sheet--compact" aria-label="Uploads">
            {uploadedClips.map((f, i) => {
              const key = fileKey(f);
              const m = upMeta[key];
              const isImg = IMAGE_EXTS.includes(extOf(f.name));
              const showImg = isImg && isDisplayableImage(f.name);
              const badge = m?.dur != null ? `${Math.round(m.dur)}s` : isImg ? "STILL" : "…";
              const dims = m && dimsLabel(m.w, m.h);
              const tip = `${f.name}${m?.dur != null ? ` · ${Math.round(m.dur)}s` : isImg ? " · still" : ""}${dims ? ` · ${dims}` : ""} · ${formatSize(f.size)}`;
              return (
                <figure key={key}>
                  <span className="clip-thumb">
                    {showImg ? (
                      <img
                        src={clipUrls.get(key)}
                        alt={f.name}
                        onLoad={(e) =>
                          recordClipMeta(
                            key,
                            null,
                            e.currentTarget.naturalWidth || null,
                            e.currentTarget.naturalHeight || null,
                          )
                        }
                      />
                    ) : isImg ? (
                      <div className="media-placeholder" aria-hidden="true">
                        {extOf(f.name).slice(1).toUpperCase()} still
                      </div>
                    ) : (
                      <video
                        muted
                        preload="metadata"
                        src={clipUrls.get(key)}
                        onLoadedMetadata={(e) =>
                          recordClipMeta(
                            key,
                            Number.isFinite(e.currentTarget.duration)
                              ? e.currentTarget.duration
                              : null,
                            e.currentTarget.videoWidth || null,
                            e.currentTarget.videoHeight || null,
                          )
                        }
                      />
                    )}
                    <span className="clip-dur" aria-hidden="true">
                      {badge}
                    </span>
                  </span>
                  <figcaption title={tip}>
                    <span className="clip-name">{f.name}</span>
                    <span className="clip-meta">{formatSize(f.size)}</span>
                    <button type="button" className="clip-remove" onClick={() => removeClip(i)}>
                      Remove
                    </button>
                  </figcaption>
                </figure>
              );
            })}
          </div>
        )}

        <div className="library-clips-header">
          <span
            className="library-count"
            title={`${videoCount} videos + ${stillCount} stills${usedCount !== null ? ` · ${usedCount} of ${clips.length} used in final reels` : ""}`}
            aria-live="polite"
          >
            {clips.length} in library · {videoCount} videos + {stillCount} stills
            {usedCount !== null && ` · ${usedCount} used · ${clips.length - usedCount} unused`}
          </span>
          {clips.length > 0 && (
            <div className="library-clips-tools">
              <label>
                Sort
                <select
                  value={usageSort}
                  onChange={(e) => setUsageSort(e.target.value as "newest" | "most" | "least")}
                  aria-label="Sort library clips by reuse"
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
          )}
        </div>
        <p>
          {clips.length > 0 && (
            <>
              <button type="button" onClick={selectAllClips}>
                Select all
              </button>{" "}
              <button type="button" onClick={clearClips}>
                Clear
              </button>
            </>
          )}
        </p>
        {clips.length === 0 ? (
          <p>No clips from past sessions yet — drop some above.</p>
        ) : visibleClips.length === 0 ? (
          <p>Every clip has a final reel credit — clear “unused only” to browse all.</p>
        ) : (
          <>
            <div className="contact-sheet contact-sheet--compact">
              {(allClips ? visibleClips : visibleClips.slice(0, CLIP_PAGE)).map((c) => {
                const ref = refOf(c);
                const dur = c.kind === "image" ? "STILL" : durationLabel(c.duration_s, c.kind);
                const dims = dimsLabel(c.w, c.h);
                const tip = `${c.filename} · ${durationLabel(c.duration_s, c.kind)}${dims ? ` · ${dims}` : ""} · ${formatSize(c.size)}`;
                return (
                  <figure key={ref} className={selectedClips.has(ref) ? "is-selected" : undefined}>
                    <span className="clip-thumb">
                      {c.kind === "image" && !isDisplayableImage(c.filename) ? (
                        <div className="media-placeholder" aria-hidden="true">
                          {extOf(c.filename).slice(1).toUpperCase()} still
                        </div>
                      ) : c.kind === "image" ? (
                        <img src={fileUrl(c.session, c.path)} alt={c.filename} loading="lazy" />
                      ) : (
                        <LibraryHoverVideo src={previewUrl(c)} label={c.filename} />
                      )}
                      <span className="clip-dur" aria-hidden="true">
                        {dur}
                      </span>
                    </span>
                    <figcaption title={tip}>
                      <label className="clip-pick">
                        <input
                          type="checkbox"
                          checked={selectedClips.has(ref)}
                          onChange={() => toggleClip(ref)}
                        />
                        <span className="clip-name">{c.filename}</span>
                      </label>
                      <span className="clip-meta">{formatSize(c.size)}</span>
                    </figcaption>
                  </figure>
                );
              })}
            </div>
            {visibleClips.length > CLIP_PAGE && (
              <p className="library-more">
                <button
                  type="button"
                  onClick={() => setAllClips((v) => !v)}
                  aria-expanded={allClips}
                >
                  {allClips ? "Show less" : `Show all ${visibleClips.length} clips`}
                </button>
              </p>
            )}
          </>
        )}
      </fieldset>

      <fieldset>
        <legend>
          Music{" "}
          {uploadedMusic
            ? uploadedMusic.name
            : selectedMusic
              ? fileName(selectedMusic)
              : "(none chosen)"}
        </legend>
        <div
          className={`dropzone dropzone--track${dragMusic ? " is-dragging" : ""}${uploadedMusic ? " is-filled" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragMusic(true);
          }}
          onDragLeave={() => setDragMusic(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragMusic(false);
            const incoming = Array.from(e.dataTransfer.files);
            const [f] = dropFiles(incoming, MUSIC_EXTS);
            if (!f && incoming.length > 0) {
              setDropNotice(
                `Skipped ${incoming.length} file(s) — music accepts ${MUSIC_EXTS.join(", ")}.`,
              );
              return;
            }
            setDropNotice(null);
            if (f) setMusicFile(f);
          }}
        >
          {uploadedMusic && musicUrl ? (
            <div className="drop-track">
              <div className="drop-track-head">
                <span
                  className="drop-track-meta"
                  title={`${uploadedMusic.name} · ${formatSize(uploadedMusic.size)}`}
                >
                  <span className="clip-name">{uploadedMusic.name}</span>
                  <span className="clip-meta">
                    {formatSize(uploadedMusic.size)} · uploaded — drop to replace
                  </span>
                </span>
                <label className="dropzone-browse" htmlFor="new-music">
                  Replace
                </label>
                <button
                  type="button"
                  className="drop-track-remove"
                  onClick={() => setMusicFile(null)}
                >
                  Remove
                </button>
              </div>
              <TrackPlayer
                src={musicUrl}
                label={uploadedMusic.name}
                preload="metadata"
                computePeaks
                onDuration={(d) => setUpMusicDur(d)}
              />
            </div>
          ) : (
            <div className="dropzone-empty">
              <p className="dropzone-hint">Drop a track here or browse (mp3, wav, or mp4/m4a)</p>
              <label className="dropzone-browse" htmlFor="new-music">
                Browse files
              </label>
            </div>
          )}
          <input
            id="new-music"
            ref={musicInput}
            className="dropzone-input"
            type="file"
            name="music"
            accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,video/mp4"
            onChange={(e) => onMusicBrowse(e.target.files)}
          />
        </div>

        {music.length === 0 ? (
          <p>No music from past sessions yet — drop a track above.</p>
        ) : (
          <>
            <ul className="media-list">
              {(allMusic ? music : music.slice(0, MUSIC_PAGE)).map((m) => {
                const ref = refOf(m);
                return (
                  <li key={ref}>
                    <label>
                      <input
                        type="radio"
                        name="media-library-music"
                        checked={selectedMusic === ref}
                        onChange={() => pickMusic(ref)}
                      />
                      {m.filename} · {formatSize(m.size)}
                    </label>
                    <TrackPlayer
                      src={fileUrl(m.session, m.path)}
                      label={m.filename}
                      peaksRef={ref}
                      durationHint={m.duration_s}
                    />
                  </li>
                );
              })}
            </ul>
            {music.length > MUSIC_PAGE && (
              <p className="library-more">
                <button
                  type="button"
                  onClick={() => setAllMusic((v) => !v)}
                  aria-expanded={allMusic}
                >
                  {allMusic ? "Show less" : `Show all ${music.length} tracks`}
                </button>
              </p>
            )}
          </>
        )}
      </fieldset>
    </div>
  );
}
