// Light / Dark / System segmented control. Sits in the list-pane header.

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";

import styles from "./ThemeToggle.module.css";
import { useTheme, type ThemeChoice } from "./theme";

const OPTIONS: ReadonlyArray<{ value: ThemeChoice; Icon: LucideIcon; label: string }> = [
  { value: "light", Icon: Sun, label: "Light" },
  { value: "dark", Icon: Moon, label: "Dark" },
  { value: "system", Icon: Monitor, label: "System" },
];

export function ThemeToggle() {
  const [choice, setChoice] = useTheme();
  return (
    <div className={styles.toggle} role="group" aria-label="Colour theme">
      {OPTIONS.map(({ value, Icon, label }) => (
        <button
          key={value}
          type="button"
          className={styles.option}
          data-active={choice === value}
          aria-pressed={choice === value}
          aria-label={`${label} theme`}
          title={`${label} theme`}
          onClick={() => setChoice(value)}
        >
          <Icon size={15} />
        </button>
      ))}
    </div>
  );
}
