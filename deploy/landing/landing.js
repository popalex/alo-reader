// Landing page, returning-visitor path.
//
// A reader who already has a session should not be shown a signup pitch, so if a
// Clerk session cookie is present the two "Create an account" links become "Open
// alo reader". Cookie presence is a hint, not authentication: it decides wording
// only, and /app resolves the real session with Clerk.
//
// Served as a file rather than inlined because the CSP is `script-src 'self'`
// with no 'unsafe-inline' (deploy/Caddyfile).
(function () {
  "use strict";
  // Clerk sets __session on the app's own domain; the __client_uat timestamp is
  // readable even when __session is httpOnly, which is why both are checked.
  // __client_uat is the time of the last sign-in, and "0" once signed out: Clerk
  // keeps the cookie after sign-out, so its presence alone said "signed in" to
  // someone who had just signed out (caught by e2e-clerk).
  var cookies = document.cookie;
  var signedIn =
    /(^|;\s*)__session=[^;]/.test(cookies) || /(^|;\s*)__client_uat=[1-9]/.test(cookies);
  if (!signedIn) return;

  var links = document.querySelectorAll('a[href="/app/"]');
  for (var i = 0; i < links.length; i++) {
    var a = links[i];
    if (a.textContent.trim() === "Sign in") continue;
    a.textContent = "Open alo reader";
  }
  var reassure = document.querySelector(".reassure");
  if (reassure) reassure.textContent = "You are already signed in.";
})();
