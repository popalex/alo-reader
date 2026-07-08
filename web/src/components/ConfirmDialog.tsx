// A small confirm dialog built on Radix (focus trap, Escape, focus return).
// WP-12 uses it to guard the destructive "mark all as read" — reachable both
// from the toolbar and the `A` shortcut, which is a single keypress and so
// easy to fire by accident. The confirm button is auto-focused so the whole
// flow (open → Enter) is keyboard-only.

import * as Dialog from "@radix-ui/react-dialog";

import styles from "./ConfirmDialog.module.css";

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content}>
          <Dialog.Title className={styles.title}>{title}</Dialog.Title>
          <Dialog.Description className={styles.body}>{body}</Dialog.Description>
          <div className={styles.actions}>
            <Dialog.Close asChild>
              <button type="button" className={styles.cancel}>
                Cancel
              </button>
            </Dialog.Close>
            <button
              type="button"
              className={styles.confirm}
              autoFocus
              onClick={() => {
                onConfirm();
                onOpenChange(false);
              }}
            >
              {confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
