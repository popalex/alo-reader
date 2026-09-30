// The feeds/folders sidebar as an off-canvas drawer on mobile (Radix Dialog gives
// the focus trap, scrim, Escape and scroll-lock). It reuses the exact same
// <Sidebar/> as desktop — only the container changes. Content mounts only while
// open, so on desktop (drawer never opened) there's a single Sidebar instance.

import * as Dialog from "@radix-ui/react-dialog";

import { Sidebar } from "../sidebar/Sidebar";
import styles from "./MobileSidebar.module.css";

export function MobileSidebar({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.drawer} aria-describedby={undefined}>
          <Dialog.Title className="sr-only">Feeds and folders</Dialog.Title>
          <Sidebar />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
