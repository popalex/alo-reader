// What kind of instance the app is running on, from /config at boot. A module value
// rather than a context: it is set once before the first render and never changes.
//
// Clerk mode is the public service with its website (landing page, /legal, the
// "Moving from ..." guides); none mode is a self-hosted reader, where those pages
// answer 404, so the app must not link to them.

let authMode = "none";

export function setAuthMode(mode: string): void {
  authMode = mode;
}

/** True when the instance serves the public website pages next to the app. */
export function hasPublicSite(): boolean {
  return authMode === "clerk";
}
