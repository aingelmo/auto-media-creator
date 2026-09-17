import { useEffect, useRef } from "react";

/** Wraps children in a native `<dialog>` so Escape/backdrop-click close for free.
 * Stays mounted across open/close so form inputs inside it (e.g. file pickers)
 * don't lose their value when the dialog closes. */
export default function Modal({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (open) ref.current?.showModal();
    else ref.current?.close();
  }, [open]);

  return (
    <dialog ref={ref} className="stage-modal" onClose={onClose}>
      <button type="button" className="stage-modal-close" onClick={onClose} aria-label="Close">
        &times;
      </button>
      {children}
    </dialog>
  );
}
