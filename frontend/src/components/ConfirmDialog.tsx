import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ConfirmContext, type ConfirmFn, type ConfirmOptions } from "./confirm";

/** One modal for every destructive action in the app. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const [typed, setTyped] = useState("");
  const resolver = useRef<((value: boolean) => void) | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const confirm = useCallback<ConfirmFn>((next) => {
    resolver.current?.(false); // an earlier prompt the caller abandoned
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
      setTyped("");
      setOptions(next);
    });
  }, []);

  const settle = useCallback((value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setOptions(null);
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (options && !dialog.open) dialog.showModal();
    if (!options && dialog.open) dialog.close();
  }, [options]);

  const canConfirm = !options?.requireText || typed === options.requireText;

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {options && (
        <dialog
          ref={dialogRef}
          className="library-modal confirm-modal"
          aria-label={options.title}
          onClose={() => settle(false)}
          onCancel={(event) => {
            event.preventDefault();
            settle(false);
          }}
        >
          <h2 className="confirm-title">{options.title}</h2>
          {options.body && <div className="confirm-body">{options.body}</div>}
          {options.requireText && (
            <label className="confirm-typed">
              {`Type ${options.requireText} to confirm`}
              <input
                type="text"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                autoComplete="off"
                autoFocus
              />
            </label>
          )}
          <div className="confirm-actions">
            <button type="button" autoFocus={!options.requireText} onClick={() => settle(false)}>
              {options.cancelLabel ?? "Cancel"}
            </button>
            <button
              type="button"
              className={options.tone === "danger" ? "danger" : "primary"}
              disabled={!canConfirm}
              onClick={() => settle(true)}
            >
              {options.confirmLabel ?? "Confirm"}
            </button>
          </div>
        </dialog>
      )}
    </ConfirmContext.Provider>
  );
}
