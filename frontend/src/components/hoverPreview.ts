/** Shared hover-playback handoff for library contact-sheet tiles (#4.3).
 * One module-level slot tracks the currently playing preview across the
 * /new picker, the / library tiles, and the preview modal, so entering
 * any tile pauses whatever else is playing. */

/** Currently playing hover preview across all grids. */
let activePreview: HTMLVideoElement | null = null;

/** True when the user prefers reduced motion: hover previews stay still. */
export function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Start hover playback on a tile video, pausing any other tile first so
 * only one preview plays at a time.
 *
 * Args:
 *   video: The tile `<video>` element to play. Must already carry the
 *     `muted` attribute in markup plus `playsInline`; callers keep
 *     `preload="metadata"` and play on demand (no preload-all).
 *
 * Note: Reduced-motion opts out entirely (no-op), and autoplay-policy
 * rejections from `play()` are swallowed.
 */
export function playHoverPreview(video: HTMLVideoElement): void {
  if (reducedMotion()) return;
  if (activePreview && activePreview !== video) {
    activePreview.pause();
    activePreview.currentTime = 0;
  }
  activePreview = video;
  const attempt = video.play();
  if (attempt) attempt.catch(() => {});
}

/** Pause a hover preview and reset it to its first frame.
 *
 * Args:
 *   video: The tile `<video>` element to stop. Clears the shared active
 *     slot when it points at this element.
 */
export function stopHoverPreview(video: HTMLVideoElement): void {
  video.pause();
  video.currentTime = 0;
  if (activePreview === video) activePreview = null;
}
