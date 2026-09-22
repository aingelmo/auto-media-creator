import { useEffect, useState } from "react";
import { api, fileUrl } from "../api";
import type { MediaEntry } from "../types";

function formatKb(bytes: number): string {
  return `${(bytes / 1000).toFixed(0)} KB`;
}

function fileName(ref: string): string {
  return ref.split("/").pop() ?? ref;
}

/** Clips & music for the new-session form: pick from past sessions and/or
 * upload fresh files, both visible together so it's obvious when nothing
 * on file matches and an upload is needed. */
export default function MediaLibraryPicker({
  onClipsChange,
  onMusicChange,
}: {
  onClipsChange: (refs: string[]) => void;
  onMusicChange: (ref: string) => void;
}) {
  const [clips, setClips] = useState<MediaEntry[]>([]);
  const [music, setMusic] = useState<MediaEntry[]>([]);
  const [selectedClips, setSelectedClips] = useState<Set<string>>(new Set());
  const [selectedMusic, setSelectedMusic] = useState("");
  const [clipsOpen, setClipsOpen] = useState(false);
  const [musicOpen, setMusicOpen] = useState(false);
  const [uploadedClipsCount, setUploadedClipsCount] = useState(0);
  const [uploadedMusicName, setUploadedMusicName] = useState("");

  useEffect(() => {
    api.getMedia().then((lib) => {
      setClips(lib.clips);
      setMusic(lib.music);
    });
  }, []);

  function toggleClip(ref: string) {
    const next = new Set(selectedClips);
    if (next.has(ref)) next.delete(ref);
    else next.add(ref);
    setSelectedClips(next);
    onClipsChange([...next]);
  }

  function selectAllClips() {
    const next = new Set(clips.map((c) => `${c.session}/${c.path}`));
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

  return (
    <div className="media-library-picker">
      <fieldset>
        <legend>Clips / photos</legend>
        <p>
          <button
            type="button"
            aria-expanded={clipsOpen}
            aria-controls="clips-panel"
            onClick={() => setClipsOpen((v) => !v)}
          >
            {clipsOpen ? "Hide clips" : "Select clips"}&hellip; ({selectedClips.size} picked
            {uploadedClipsCount > 0 && `, ${uploadedClipsCount} uploaded`})
          </button>
        </p>
        {clipsOpen && (
          <div id="clips-panel" className="library-panel">
            <p>
              {clips.length > 0 && (
                <>
                  <button type="button" onClick={selectAllClips}>
                    Select all
                  </button>{" "}
                  <button type="button" onClick={clearClips}>
                    Clear
                  </button>{" "}
                </>
              )}
              <label htmlFor="new-clips">
                Upload {clips.length > 0 ? "more clips" : "clips"}
                <input
                  id="new-clips"
                  type="file"
                  name="clips"
                  multiple
                  onChange={(e) => setUploadedClipsCount(e.target.files?.length ?? 0)}
                />
              </label>
            </p>
            {clips.length === 0 ? (
              <p>No clips from past sessions yet.</p>
            ) : (
              <div className="contact-sheet contact-sheet--compact">
                {clips.map((c) => {
                  const ref = `${c.session}/${c.path}`;
                  return (
                    <figure key={ref}>
                      <video muted preload="metadata" src={fileUrl(c.session, c.path)} />
                      <figcaption>
                        <label>
                          <input
                            type="checkbox"
                            checked={selectedClips.has(ref)}
                            onChange={() => toggleClip(ref)}
                          />
                          {c.filename} &middot; {formatKb(c.size)}
                        </label>
                      </figcaption>
                    </figure>
                  );
                })}
              </div>
            )}
            <p>
              <button type="button" onClick={() => setClipsOpen(false)}>
                Done
              </button>
            </p>
          </div>
        )}
      </fieldset>
      <fieldset>
        <legend>Music</legend>
        <p>
          <button
            type="button"
            aria-expanded={musicOpen}
            aria-controls="music-panel"
            onClick={() => setMusicOpen((v) => !v)}
          >
            {musicOpen ? "Hide music" : "Select music"}&hellip;{" "}
            {uploadedMusicName
              ? uploadedMusicName
              : selectedMusic
                ? fileName(selectedMusic)
                : "(none chosen)"}
          </button>
        </p>
        {musicOpen && (
          <div id="music-panel" className="library-panel">
            <p>
              <label htmlFor="new-music">
                Upload {music.length > 0 ? "a different track" : "a track"} (mp3, wav, or mp4/m4a)
                <input
                  id="new-music"
                  type="file"
                  name="music"
                  accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,video/mp4"
                  onChange={(e) => setUploadedMusicName(e.target.files?.[0]?.name ?? "")}
                />
              </label>
            </p>
            {music.length === 0 ? (
              <p>No music from past sessions yet.</p>
            ) : (
              <ul className="media-list">
                {music.map((m) => {
                  const ref = `${m.session}/${m.path}`;
                  return (
                    <li key={ref}>
                      <label>
                        <input
                          type="radio"
                          name="media-library-music"
                          checked={selectedMusic === ref}
                          onChange={() => pickMusic(ref)}
                        />
                        {m.filename} &middot; {formatKb(m.size)}
                      </label>
                      <audio controls preload="none" src={fileUrl(m.session, m.path)} />
                    </li>
                  );
                })}
              </ul>
            )}
            <p>
              <button type="button" onClick={() => setMusicOpen(false)}>
                Done
              </button>
            </p>
          </div>
        )}
      </fieldset>
    </div>
  );
}
