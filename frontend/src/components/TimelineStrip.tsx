import { useState } from "react";
import type { TimelineClip } from "../types";

function baseName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

export default function TimelineStrip({
  clips,
  thumbUrls = {},
  onReorder,
  disabled,
}: {
  clips: TimelineClip[];
  thumbUrls?: Record<string, string>;
  onReorder: (order: number[]) => void;
  disabled: boolean;
}) {
  // Develop slots in timeline order; `order` for the backend is this
  // list permuted so position i holds footage from slot order[i].
  const develops = clips.filter((c) => c.role === "develop").toSorted((a, b) => a.slot - b.slot);
  const orderedSlots = develops.map((c) => c.slot);

  const [dragged, setDragged] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<number | null>(null);

  function move(from: number, to: number) {
    if (from === to) return;
    const next = [...orderedSlots];
    const [slot] = next.splice(from, 1);
    next.splice(to, 0, slot);
    onReorder(next);
  }

  function handleDrop(to: number) {
    if (dragged !== null) move(dragged, to);
    setDragged(null);
    setDropTarget(null);
  }

  return (
    <ol className="timeline-strip" aria-label="Reel timeline — reorder develop clips">
      {clips.map((clip, pos) => {
        const locked = clip.locked;
        const devIdx = locked ? -1 : orderedSlots.indexOf(clip.slot);
        const thumb = clip.candidate_id ? thumbUrls[clip.candidate_id] : undefined;
        const name = clip.candidate_id || baseName(clip.src);
        const draggable = !locked && !disabled && develops.length > 1;
        const classes = [
          "timeline-slot",
          locked ? "is-locked" : "is-develop",
          dragged === devIdx && devIdx !== -1 ? "is-dragging" : "",
          dropTarget === devIdx && devIdx !== -1 ? "is-drop-target" : "",
        ]
          .filter(Boolean)
          .join(" ");
        // Drag handlers live on the card itself; keyboard users get the
        // equivalent ← → buttons below, so this is progressive enhancement.
        return (
          // oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
          <li
            key={clip.slot}
            className={classes}
            draggable={draggable}
            onDragStart={() => setDragged(devIdx)}
            onDragOver={(e) => {
              if (dragged === null || locked) return;
              e.preventDefault();
              setDropTarget(devIdx);
            }}
            onDragLeave={() => setDropTarget(null)}
            onDrop={() => handleDrop(devIdx)}
            onDragEnd={() => {
              setDragged(null);
              setDropTarget(null);
            }}
            title={clip.src}
          >
            <span className="timeline-pos" aria-label={`Position ${pos + 1}`}>
              {pos + 1}
            </span>
            {thumb ? (
              <img className="timeline-thumb" src={thumb} alt="" loading="lazy" />
            ) : (
              <span className="timeline-thumb is-empty" aria-hidden="true" />
            )}
            <span className="timeline-meta">
              <span className="timeline-role">
                {clip.role}
                {locked ? " · locked" : ""}
              </span>
              <span className="timeline-src">{name}</span>
            </span>
            {!locked && develops.length > 1 && (
              <span className="timeline-actions">
                <button
                  type="button"
                  disabled={disabled || devIdx <= 0}
                  onClick={() => move(devIdx, devIdx - 1)}
                  aria-label={`Move clip ${pos + 1} earlier`}
                >
                  ←
                </button>
                <button
                  type="button"
                  disabled={disabled || devIdx >= develops.length - 1}
                  onClick={() => move(devIdx, devIdx + 1)}
                  aria-label={`Move clip ${pos + 1} later`}
                >
                  →
                </button>
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
