import { useEffect, useRef } from "react";

/** Wraps children in a native `<dialog>` so Escape/backdrop-click close for free. */
export default function Modal({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  return (
    <dialog ref={ref} className="stage-modal" onClose={onClose}>
      <button type="button" className="stage-modal-close" onClick={onClose} aria-label="Close">
        &times;
      </button>
      {children}
    </dialog>
  );
}
