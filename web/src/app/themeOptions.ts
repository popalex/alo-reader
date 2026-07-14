// The Light / Dark / System options, shared by the desktop ThemeToggle and the
// mobile overflow menu so the two can't drift. Kept out of theme.ts to leave that
// store free of component (lucide) imports.

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";

import type { ThemeChoice } from "./theme";

export const THEME_OPTIONS: ReadonlyArray<{ value: ThemeChoice; Icon: LucideIcon; label: string }> = [
  { value: "light", Icon: Sun, label: "Light" },
  { value: "dark", Icon: Moon, label: "Dark" },
  { value: "system", Icon: Monitor, label: "System" },
];
