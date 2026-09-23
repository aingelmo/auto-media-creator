import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { fileUrl, previewUrl } from "../api";
import type { MediaEntry } from "../types";
import {
  dimsLabel,
  durationLabel,
  extOf,
  formatAge,
  formatSize,
  isDisplayableImage,
} from "./mediaMeta";

/** Lightbox preview for one library clip: playable media plus the spec
 *  row that answers "what is this video about / can I cut with it". */
export default function LibraryPreview({
  clip,
  onClose,
}: {
  clip: MediaEntry;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
    };
  }, []);

  const showImg = clip.kind === "image" && isDisplayableImage(clip.filename);
  const placeholder =
    clip.kind === "image" && !isDisplayableImage(clip.filename)
      ? `${extOf(clip.filename).slice(1).toUpperCase()} still`
      : null;

  return (
    <dialog ref={dialogRef} className="library-modal" aria-label={clip.filename} onClose={onClose}>
      <div className="library-modal-header">
        <strong>{clip.filename}</strong>
        <form method="dialog">
          <button type="submit" autoFocus aria-label="Close preview">
            ✕
          </button>
        </form>
      </div>
      {showImg ? (
        <img src={fileUrl(clip.session, clip.path)} alt={clip.filename} />
      ) : clip.kind === "image" ? (
        <div className="media-placeholder" aria-hidden="true">
          {placeholder ?? "still"}
        </div>
      ) : (
        <video controls autoPlay src={previewUrl(clip)} />
      )}
      {clip.kind === "video" && clip.proxy_path && (
        <p className="library-proxy-note">
          Proxy preview (silent, low-res)
          {clip.proxy_verified === false && " · unverified"} ·{" "}
          <a href={fileUrl(clip.session, clip.path)} download>
            original {extOf(clip.filename).slice(1).toUpperCase()}
          </a>
        </p>
      )}
      <dl className="library-specs">
        <div>
          <dt>From</dt>
          <dd>
            <Link to={`/sessions/${clip.session}`}>{clip.session}</Link> · {formatAge(clip.mtime)}
          </dd>
        </div>
        <div>
          <dt>Length</dt>
          <dd>{durationLabel(clip.duration_s, clip.kind)}</dd>
        </div>
        <div>
          <dt>Frame</dt>
          <dd>{dimsLabel(clip.w, clip.h) || "—"}</dd>
        </div>
        <div>
          <dt>Size</dt>
          <dd>
            {formatSize(clip.size)} · {extOf(clip.filename).slice(1).toUpperCase() || "—"}
          </dd>
        </div>
      </dl>
      <p className="library-modal-actions">
        <Link to="/new">Use in new session →</Link>
      </p>
    </dialog>
  );
}
