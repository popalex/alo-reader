// The `?` help overlay. Every row is generated from bindings.ts — never
// hand-written — so it always matches the live keymap (a unit test enforces
// this). Radix Dialog supplies the focus trap, Escape-to-close, and focus
// return that WP-12's accessibility bar requires.

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { groupedBindings } from "./bindings";
import styles from "./KeyboardHelp.module.css";

function keyLabel(key: string): string {
  if (key === " ") return "Space";
  return key;
}

function Combo({ combo }: { combo: string[] }) {
  return (
    <span className={styles.combo}>
      {combo.map((key, i) => (
        <kbd key={i} className={styles.kbd}>
          {keyLabel(key)}
        </kbd>
      ))}
    </span>
  );
}

export function KeyboardHelp({
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
        <Dialog.Content className={styles.content} aria-describedby={undefined}>
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>Keyboard shortcuts</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className={styles.close} aria-label="Close">
                <X size={16} />
              </button>
            </Dialog.Close>
          </div>
          <div className={styles.groups}>
            {groupedBindings().map(({ group, bindings }) => (
              <section key={group} className={styles.group}>
                <h3 className={styles.groupTitle}>{group}</h3>
                <dl className={styles.list}>
                  {bindings.map((b) => (
                    <div key={b.id} className={styles.item}>
                      <dt className={styles.keys}>
                        {b.combos.map((combo, i) => (
                          <span key={i} className={styles.alt}>
                            {i > 0 ? <span className={styles.or}>or</span> : null}
                            <Combo combo={combo} />
                          </span>
                        ))}
                      </dt>
                      <dd className={styles.label}>{b.label}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
