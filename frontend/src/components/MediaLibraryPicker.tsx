import { useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, previewUrl } from "../api";
import type { MediaEntry } from "../types";
import { basenameOf, fetchUsage, type UsageMap } from "./clipUsage";
import CoverageMeter from "./CoverageMeter";
import type { CreateStats } from "./CreateSummary";
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
        fetchUsage(
          sessions.map((s) => s.name),
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
    const next = new Set(clips.map(refOf));
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

  const visibleClips = useMemo(() => {
    const list = [...clips];
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
            mergeClips(dropFiles(e.dataTransfer.files, CLIP_EXTS));
          }}
        >
          <label htmlFor="new-clips">
            Drop clips / photos here or browse
            <input
              id="new-clips"
              ref={clipsInput}
              type="file"
              name="clips"
              multiple
              accept={CLIP_EXTS.join(",")}
              onChange={(e) => setUploadedClips(Array.from(e.target.files ?? []))}
            />
          </label>
        </div>

        {uploadedClips.length > 0 && (
          <div className="contact-sheet contact-sheet--compact" aria-label="Uploads">
            {uploadedClips.map((f, i) => {
              const key = fileKey(f);
              const m = upMeta[key];
              const isImg = IMAGE_EXTS.includes(extOf(f.name));
              const showImg = isImg && isDisplayableImage(f.name);
              return (
                <figure key={key}>
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
                  <figcaption>
                    {f.name} ·{" "}
                    {m
                      ? `${m.dur != null ? `${Math.round(m.dur)}s` : "still"}${dimsLabel(m.w, m.h) ? ` · ${dimsLabel(m.w, m.h)}` : ""}`
                      : formatSize(f.size)}
                    <br />
                    <button type="button" onClick={() => removeClip(i)}>
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
                return (
                  <figure key={ref}>
                    {c.kind === "image" && !isDisplayableImage(c.filename) ? (
                      <div className="media-placeholder" aria-hidden="true">
                        {extOf(c.filename).slice(1).toUpperCase()} still
                      </div>
                    ) : c.kind === "image" ? (
                      <img src={fileUrl(c.session, c.path)} alt={c.filename} loading="lazy" />
                    ) : (
                      <video muted preload="metadata" src={previewUrl(c)} />
                    )}
                    <figcaption>
                      <label>
                        <input
                          type="checkbox"
                          checked={selectedClips.has(ref)}
                          onChange={() => toggleClip(ref)}
                        />
                        {c.filename} · {durationLabel(c.duration_s, c.kind)}
                        {dimsLabel(c.w, c.h) && ` · ${dimsLabel(c.w, c.h)}`} · {formatSize(c.size)}
                      </label>
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
          className={`dropzone${dragMusic ? " is-dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragMusic(true);
          }}
          onDragLeave={() => setDragMusic(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragMusic(false);
            const [f] = dropFiles(e.dataTransfer.files, MUSIC_EXTS);
            if (f) setMusicFile(f);
          }}
        >
          <label htmlFor="new-music">
            Drop a track here or browse (mp3, wav, or mp4/m4a)
            <input
              id="new-music"
              ref={musicInput}
              type="file"
              name="music"
              accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,video/mp4"
              onChange={(e) => setMusicFile(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>

        {uploadedMusic && musicUrl && (
          <ul className="media-list">
            <li>
              <label>
                {uploadedMusic.name} · {formatSize(uploadedMusic.size)} (uploaded)
              </label>
              <TrackPlayer
                src={musicUrl}
                label={uploadedMusic.name}
                preload="metadata"
                onDuration={(d) => setUpMusicDur(d)}
              />
              <button type="button" onClick={() => setMusicFile(null)}>
                Remove
              </button>
            </li>
          </ul>
        )}

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
