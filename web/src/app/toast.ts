// Minimal toast store. Query/mutation errors push here via the QueryClient's
// cache handler, so it's a plain external store (not a hook) that non-React code
// can call. The <Toaster/> component (Toaster.tsx) subscribes and renders it;
// keeping the store here — free of JSX — is what lets both live without
// tripping react-refresh's component-only-module rule.

export type ToastTone = "error" | "info";
export interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

const DISMISS_MS = 6000;

let toasts: Toast[] = [];
const listeners = new Set<() => void>();
let nextId = 1;

function emit(): void {
  for (const l of listeners) l();
}

export function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function snapshot(): Toast[] {
  return toasts;
}

export function pushToast(message: string, tone: ToastTone = "error"): number {
  const id = nextId++;
  toasts = [...toasts, { id, message, tone }];
  emit();
  window.setTimeout(() => dismissToast(id), DISMISS_MS);
  return id;
}

export function dismissToast(id: number): void {
  const next = toasts.filter((t) => t.id !== id);
  if (next.length !== toasts.length) {
    toasts = next;
    emit();
  }
}
