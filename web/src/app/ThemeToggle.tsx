// Light / Dark / System segmented control. Sits in the list-pane header.

import styles from "./ThemeToggle.module.css";
import { useTheme } from "./theme";
import { THEME_OPTIONS } from "./themeOptions";

export function ThemeToggle() {
  const [choice, setChoice] = useTheme();
  return (
    <div className={styles.toggle} role="group" aria-label="Colour theme">
      {THEME_OPTIONS.map(({ value, Icon, label }) => (
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
