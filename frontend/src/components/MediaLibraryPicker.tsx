import { useEffect, useState } from "react";
import { api, fileUrl } from "../api";
import type { MediaEntry } from "../types";
import Modal from "./Modal";

function formatKb(bytes: number): string {
  return `${(bytes / 1000).toFixed(0)} KB`;
}

/** Lets the new-session form pick clips/music already on disk from past sessions. */
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
    setMusicOpen(false);
  }

  const selectedMusicEntry = music.find((m) => `${m.session}/${m.path}` === selectedMusic);

  return (
    <div className="media-library-picker">
      <fieldset>
        <legend>Clips</legend>
        {clips.length === 0 ? (
          <p>No clips from past sessions yet.</p>
        ) : (
          <p>
            <button type="button" onClick={() => setClipsOpen(true)}>
              Select clips&hellip; ({selectedClips.size} of {clips.length} chosen)
            </button>
          </p>
        )}
        {clipsOpen && (
          <Modal onClose={() => setClipsOpen(false)}>
            <p>
              <button type="button" onClick={selectAllClips}>
                Select all
              </button>{" "}
              <button type="button" onClick={clearClips}>
                Clear
              </button>
            </p>
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
          </Modal>
        )}
      </fieldset>
      <fieldset>
        <legend>Music</legend>
        {music.length === 0 ? (
          <p>No music from past sessions yet.</p>
        ) : (
          <p>
            <button type="button" onClick={() => setMusicOpen(true)}>
              Select track&hellip;
            </button>{" "}
            {selectedMusicEntry ? selectedMusicEntry.filename : "(none chosen)"}
          </p>
        )}
        {selectedMusicEntry && (
          <audio
            controls
            preload="none"
            src={fileUrl(selectedMusicEntry.session, selectedMusicEntry.path)}
          />
        )}
        {musicOpen && (
          <Modal onClose={() => setMusicOpen(false)}>
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
          </Modal>
        )}
      </fieldset>
    </div>
  );
}
