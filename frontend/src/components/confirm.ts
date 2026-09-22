import { createContext, useContext, type ReactNode } from "react";

export interface ConfirmOptions {
  title: string;
  /** Body copy describing exactly what will happen. */
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** `"danger"` paints the confirm action and note in the Fail hue. */
  tone?: "danger" | "default";
  /**
   * When set, the confirm action stays disabled until the user types this
   * string. Reserved for irreversible purges, so friction scales with
   * reversibility: a soft delete asks once, deleting forever makes you type.
   */
  requireText?: string;
}

export type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

export const ConfirmContext = createContext<ConfirmFn | null>(null);

/**
 * Ask for confirmation; resolves `true` only when the user confirms.
 * Rendered by `<ConfirmProvider>`, which owns the single modal instance.
 */
export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm must be used within <ConfirmProvider>");
  return confirm;
}
