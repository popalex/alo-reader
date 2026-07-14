// Compact / expanded row-density segmented control, shown in the list header.

import { List as ListIcon, Rows3 } from "lucide-react";

import type { Density } from "./density";
import styles from "./EntryList.module.css";

export function DensityToggle({ value, onChange }: { value: Density; onChange: (d: Density) => void }) {
  return (
    <div className={styles.density} role="group" aria-label="List density">
      <button
        type="button"
        className={styles.densityOpt}
        data-active={value === "list"}
        aria-pressed={value === "list"}
        aria-label="Compact rows"
        title="Compact rows"
        onClick={() => onChange("list")}
      >
        <ListIcon size={15} />
      </button>
      <button
        type="button"
        className={styles.densityOpt}
        data-active={value === "expanded"}
        aria-pressed={value === "expanded"}
        aria-label="Expanded rows"
        title="Expanded rows"
        onClick={() => onChange("expanded")}
      >
        <Rows3 size={15} />
      </button>
    </div>
  );
}
