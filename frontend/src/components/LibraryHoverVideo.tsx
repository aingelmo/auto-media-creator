import { useEffect, useRef } from "react";

/** Currently playing hover preview across all tiles. Module-level so
 * entering one tile pauses any other without prop drilling (#4.3). */
let activePreview: HTMLVideoElement | null = null;

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function playPreview(video: HTMLVideoElement): void {
  if (reducedMotion()) return;
  if (activePreview && activePreview !== video) {
    activePreview.pause();
    activePreview.currentTime = 0;
  }
  activePreview = video;
  const attempt = video.play();
  if (attempt) attempt.catch(() => {});
}

function stopPreview(video: HTMLVideoElement): void {
  video.pause();
  video.currentTime = 0;
  if (activePreview === video) activePreview = null;
}

/** Inline hover-play preview for a library contact-sheet tile. Muted +
 * playsInline + preload="metadata"; plays on hover/focus, resets to the
 * first frame on leave/blur, toggles on tap. Autoplay-policy rejections
 * are swallowed; prefers-reduced-motion disables playback entirely. */
export default function LibraryHoverVideo({ src, label }: { src: string; label: string }) {
  const ref = useRef<HTMLVideoElement | null>(null);

  useEffect(
    () => () => {
      if (ref.current && activePreview === ref.current) {
        ref.current.pause();
        activePreview = null;
      }
    },
    [],
  );

  return (
    <video
      ref={(v) => {
        ref.current = v;
        if (v) v.muted = true;
      }}
      muted
      playsInline
      disablePictureInPicture
      preload="metadata"
      loop
      src={src}
      tabIndex={0}
      aria-label={`Preview ${label}`}
      onMouseEnter={(e) => playPreview(e.currentTarget)}
      onMouseLeave={(e) => stopPreview(e.currentTarget)}
      onFocus={(e) => playPreview(e.currentTarget)}
      onBlur={(e) => stopPreview(e.currentTarget)}
      onClick={(e) => {
        const v = e.currentTarget;
        if (v.paused) playPreview(v);
        else stopPreview(v);
      }}
    />
  );
}
