// Dates via the built-in Intl APIs — no date library (DESIGN.md §1.2).
// Relative time for the list rows, absolute time for the tooltip.

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto", style: "narrow" });

const UNITS: ReadonlyArray<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["week", 604_800],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
  ["second", 1],
];

/** e.g. "3h ago", "yesterday", "now" — from an ISO timestamp. */
export function relativeTime(iso: string): string {
  const deltaSec = (new Date(iso).getTime() - Date.now()) / 1000; // negative in the past
  const abs = Math.abs(deltaSec);
  for (const [unit, secs] of UNITS) {
    if (abs >= secs || unit === "second") {
      return rtf.format(Math.round(deltaSec / secs), unit);
    }
  }
  return rtf.format(0, "second");
}

const dtf = new Intl.DateTimeFormat(undefined, { dateStyle: "full", timeStyle: "short" });

/** Absolute, locale-formatted timestamp for tooltips. */
export function formatDateTime(iso: string): string {
  return dtf.format(new Date(iso));
}
