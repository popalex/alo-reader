// DOMPurify, loaded on first use instead of at startup.
//
// It is only needed once an article is open, and it is 28 kB of startup JS
// otherwise. Until it has loaded, the reader has no sanitizer and renders no
// content at all, so unsanitized HTML cannot reach the DOM on the way in.

import { useEffect, useState } from "react";

import { whenIdle } from "./whenIdle";

export type Sanitize = (html: string) => string;

let sanitizer: Sanitize | undefined;
let loading: Promise<Sanitize> | undefined;

export function loadSanitizer(): Promise<Sanitize> {
  loading ??= import("dompurify").then(
    ({ default: purify }) => (sanitizer = (html) => purify.sanitize(html)),
    (error: unknown) => {
      loading = undefined; // let the next attempt retry the import
      throw error;
    },
  );
  return loading;
}

whenIdle(() => void loadSanitizer().catch(() => undefined));

/** The sanitizer once loaded; `failed` if the chunk could not be fetched. */
export function useSanitizer(): { sanitize: Sanitize | undefined; failed: boolean } {
  const [sanitize, setSanitize] = useState<Sanitize | undefined>(() => sanitizer);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (sanitize) return;
    let live = true;
    loadSanitizer().then(
      (fn) => live && setSanitize(() => fn),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [sanitize]);
  return { sanitize, failed };
}
