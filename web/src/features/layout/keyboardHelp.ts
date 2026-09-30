// Opens the keyboard shortcut sheet that AppLayout owns: the list's "?" key and the
// sidebar footer's "Keyboard shortcuts" button both use it. The button is how people
// find out the shortcuts exist; "?" alone was only discoverable by those who already
// knew. JSX-free, so it stays HMR-safe.

import { createContext, useContext } from "react";

interface KeyboardHelpApi {
  openKeyboardHelp: () => void;
}

export const KeyboardHelpContext = createContext<KeyboardHelpApi>({ openKeyboardHelp: () => {} });

export function useKeyboardHelp(): KeyboardHelpApi {
  return useContext(KeyboardHelpContext);
}
