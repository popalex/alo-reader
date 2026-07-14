// The list header's actions collapsed into a single overflow menu on mobile
// (refresh, mark-all-read, theme) so the top app bar stays `☰ · title · ⋯`.
// Desktop keeps the inline controls; this trigger is CSS-hidden there.

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, CheckCheck, MoreVertical, RefreshCw } from "lucide-react";

import { useTheme, type ThemeChoice } from "../../app/theme";
import { THEME_OPTIONS } from "../../app/themeOptions";
import styles from "./MobileActionsMenu.module.css";

export function MobileActionsMenu({
  onRefresh,
  onMarkAllRead,
  canMarkAllRead,
}: {
  onRefresh: () => void;
  onMarkAllRead: () => void;
  canMarkAllRead: boolean;
}) {
  const [theme, setTheme] = useTheme();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className={styles.trigger} aria-label="More actions">
          <MoreVertical size={18} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className={styles.content} align="end" sideOffset={6}>
          <DropdownMenu.Item className={styles.item} onSelect={onRefresh}>
            <RefreshCw size={15} /> Refresh
          </DropdownMenu.Item>
          <DropdownMenu.Item
            className={styles.item}
            disabled={!canMarkAllRead}
            onSelect={onMarkAllRead}
          >
            <CheckCheck size={15} /> Mark all read
          </DropdownMenu.Item>
          <DropdownMenu.Separator className={styles.sep} />
          <DropdownMenu.Label className={styles.label}>Theme</DropdownMenu.Label>
          <DropdownMenu.RadioGroup
            value={theme}
            onValueChange={(v) => setTheme(v as ThemeChoice)}
          >
            {THEME_OPTIONS.map(({ value, Icon, label }) => (
              <DropdownMenu.RadioItem key={value} className={styles.item} value={value}>
                <Icon size={15} /> {label}
                <DropdownMenu.ItemIndicator className={styles.indicator}>
                  <Check size={14} />
                </DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
