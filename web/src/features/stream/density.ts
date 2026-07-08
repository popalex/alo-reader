// List density preference (compact vs expanded rows), persisted in
// localStorage. Small external store so the choice survives navigation.

import { useSyncExternalStore } from "react";

export type Density = "list" | "expanded";

const STORAGE_KEY = "alo-density";
const listeners = new Set<() => void>();

function read(): Density {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "list" || v === "expanded") return v;
  } catch {
    /* localStorage unavailable */
  }
  return "list";
}

let density: Density = read();

function getDensity(): Density {
  return density;
}

function setDensity(next: Density): void {
  density = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function useDensity(): readonly [Density, (next: Density) => void] {
  const value = useSyncExternalStore(subscribe, getDensity, getDensity);
  return [value, setDensity] as const;
}
