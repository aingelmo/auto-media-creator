import type { TimelineClip } from "../types";

export default function TimelineStrip({
  clips,
  onSwap,
  disabled,
}: {
  clips: TimelineClip[];
  onSwap: (a: number, b: number) => void;
  disabled: boolean;
}) {
  const develops = clips.filter((c) => c.role === "develop").map((c) => c.slot);
  return (
    <ol className="timeline-strip" aria-label="Reel timeline">
      {clips.map((clip) => (
        <li key={clip.slot} className={clip.locked ? "timeline-slot is-locked" : "timeline-slot"}>
          <span className="timeline-role">
            {clip.role}
            {clip.locked ? " · locked" : ""}
          </span>
          <span className="timeline-src" title={clip.src}>
            {clip.candidate_id || clip.src}
          </span>
          {!clip.locked && develops.length > 1 && (
            <span className="timeline-actions">
              {develops
                .filter((s) => s !== clip.slot)
                .map((other) => (
                  <button
                    key={other}
                    type="button"
                    disabled={disabled}
                    onClick={() => onSwap(clip.slot, other)}
                    aria-label={`Swap slot ${clip.slot} with slot ${other}`}
                  >
                    ⇄ {other}
                  </button>
                ))}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
