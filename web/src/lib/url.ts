// Guard for URLs that came from a feed.
//
// The ingest parser now drops anything but http(s) before storing an entry (api PR
// #69), but rows ingested before that are still in the database, and React only
// refuses a javascript: href in development builds — a production build emits the
// attribute and the click runs the script in this origin. window.open is worse: it
// executes in a document that inherits the opener's origin.
//
// So the render sites guard too, which also covers anything a future backend change
// lets through.

const SAFE_SCHEMES = ["http:", "https:"];

/** The URL if it is safe to navigate to, otherwise undefined. */
export function safeExternalUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    // Resolved against the page, so a relative URL keeps working and a scheme-bearing
    // one is judged on its own scheme.
    const parsed = new URL(url, window.location.href);
    return SAFE_SCHEMES.includes(parsed.protocol) ? url : undefined;
  } catch {
    return undefined; // unparseable: not something to hand to the browser
  }
}
