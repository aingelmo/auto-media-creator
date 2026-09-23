import { useEffect, useRef } from "react";
import { playHoverPreview, stopHoverPreview } from "./hoverPreview";

/** Inline hover-play preview for a library contact-sheet tile. Muted +
 * playsInline + preload="metadata"; plays on hover/focus, resets to the
 * first frame on leave/blur, toggles on tap. Autoplay-policy rejections
 * are swallowed; prefers-reduced-motion disables playback entirely. */
export default function LibraryHoverVideo({ src, label }: { src: string; label: string }) {
  const ref = useRef<HTMLVideoElement | null>(null);

  useEffect(
    () => () => {
      if (ref.current) stopHoverPreview(ref.current);
    },
    [],
  );

  return (
    <video
      ref={(v) => {
        ref.current = v;
        if (v) {
          // React omits the muted *attribute* on <video> (known
          // facebook/react#10389), so set property + attribute together:
          // the property silences playback, the attribute preserves the
          // muted-in-markup contract for parsers and scrapers.
          v.muted = true;
          v.setAttribute("muted", "");
        }
      }}
      muted
      playsInline
      disablePictureInPicture
      preload="metadata"
      loop
      src={src}
      tabIndex={0}
      aria-label={`Preview ${label}`}
      onMouseEnter={(e) => playHoverPreview(e.currentTarget)}
      onMouseLeave={(e) => stopHoverPreview(e.currentTarget)}
      onFocus={(e) => playHoverPreview(e.currentTarget)}
      onBlur={(e) => stopHoverPreview(e.currentTarget)}
      onClick={(e) => {
        const v = e.currentTarget;
        if (v.paused) playHoverPreview(v);
        else stopHoverPreview(v);
      }}
    />
  );
}
