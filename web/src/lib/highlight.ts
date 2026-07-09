// Render a ts_headline search snippet safely. The API returns text with only
// <b>…</b> match markers (its StartSel/StopSel); the surrounding text is raw feed
// content and must never be trusted as HTML. So: escape everything, then re-allow
// exactly the <b> markers. Because escaping runs first, any literal "<b>" that was
// in the content is neutralised (its "&" becomes "&amp;") and can't be restored —
// only the API's own markers round-trip.

const ESCAPE: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };

export function highlightSnippet(snippet: string): string {
  const escaped = snippet.replace(/[&<>]/g, (c) => ESCAPE[c]);
  return escaped.replaceAll("&lt;b&gt;", "<b>").replaceAll("&lt;/b&gt;", "</b>");
}
