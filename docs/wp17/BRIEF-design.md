# Design brief — WP-17 landing page

## The job

Design the static page at `/`, and the signed-out screen at `/app`, inside the design
system this app already has. **You are not choosing a look.** That decision is made and
shipped: Studio in light, Nocturne in dark, one calm teal-green accent, Inter.
`wireframe/aligned.html` is the source of truth and `web/src/styles/tokens.css` is its
implementation. Your job is to extend it to page types the app does not have.

Do the copy pass first ([`BRIEF-copy.md`](BRIEF-copy.md)) and design around real
sentences. The headline decides whether the hero is one column or two; a hero built
around placeholder text will be rebuilt once the real words arrive.

## What is actually missing

The app has no marketing surfaces at all, so everything here is new:

- **A hero.** The app's densest screen is a three-pane reader; nothing in it suggests
  how a full-width statement should look in this system.
- **Section rhythm** down a long scrolling page — vertical spacing, where rules or
  background shifts separate sections, how much air the trust section gets relative to
  the proof points.
- **Screenshot framing.** The product's whole argument is visual calm, so the screenshot
  is the strongest asset on the page. Decide: browser chrome or none, shadow or border,
  full width or inset, one image or a light/dark pair, and how it degrades at 360px.
- **CTA treatment.** The accent is used sparingly in the app, and a primary button on a
  marketing page is the loudest element in the system. Work out how it is loud enough to
  be obvious without breaking the calm the page is claiming.
- **A footer** carrying terms, privacy, and a source link (see the licence note below).

## Hard constraints

These come from the stack, not from taste. Breaking one produces a page that fails CI
or silently renders wrong in production.

- **Static HTML + CSS only.** No framework, no build step, no runtime CSS-in-JS. The
  page is served by Caddy beside the SPA and must not touch the app bundle — the 180 kB
  gzip budget (currently 142.54 kB) is enforced per PR and this page contributes zero.
- **The CSP is strict and already deployed** (`deploy/Caddyfile`):
  - `script-src 'self'` — **no inline `<script>`**. The one script on the page
    (session check, swaps the CTA to "Open alo-reader") is a separate file.
  - `style-src 'self' 'unsafe-inline'` — inline styles are fine.
  - `font-src 'self' data:` — **Google Fonts is blocked.** Self-host or fall back.
  - `img-src 'self' data: https:` — remote images load, but don't use them; everything
    should be local for speed and privacy.
  - `form-action 'self'` — no third-party form endpoints.
- **Inter needs handling on this page specifically.** The app self-hosts it through
  `@fontsource-variable/inter`, imported in `web/src/main.tsx` and emitted as
  unicode-range-subset woff2 by Vite (~48 kB for latin). The static landing page is
  outside that build, so it gets Inter only if you reference the files deliberately.
  Decide and state which: reuse the SPA's hashed asset (couples the page to a build
  hash — fragile), ship an unhashed copy for the landing, or let the landing render in
  the `system-ui` fallback already in `--font-sans`. Whatever you choose, `font-display`
  must not produce a flash the hero notices.
- **Theme.** Light default at `:root`, explicit choice via `[data-theme]`, OS preference
  through `prefers-color-scheme` — same resolution order as `tokens.css`, which you
  should link rather than re-declare. A visitor arriving in dark mode sees Nocturne.
- **No emoji**, anywhere. Lucide or inline SVG, matching the app.
- **Responsive to 360px** with a real side gutter; nothing scrolls horizontally except a
  screenshot that deliberately does.
- **Lighthouse ≥ 95 on all four categories** is the WP-17 acceptance bar. A static page
  should reach it easily; the way it gets lost is unsized images causing layout shift,
  and fonts that block first paint.

## Deliverables

- **`wireframe/landing.html`** — one self-contained file, the same working pattern as
  `wireframe/aligned.html`, with the real copy in place, viewable in both themes.
- **Both themes shown**, not just light with a promise about dark.
- **A screenshot spec**: which app screen, which theme, what viewport, what is cropped,
  what is annotated if anything. These are generated from the seeded e2e stack (WP-17)
  so they cannot go stale — so the spec has to be reproducible, not a one-off capture.
- **The `/app` signed-out screen** in the same file or beside it: product name, one
  line, the Clerk widget in our tokens, theme toggle, legal links, sign-up primary and
  sign-in secondary. It is currently a centred Clerk widget with inline styles and no
  product name at all.
- **Notes on what you changed or added to the token set**, if anything. New tokens are
  allowed; silent one-off values are not, because the next page inherits the mess.

## Judge it against

The page is doing its job if a reader who has never heard of this can tell, without
scrolling, what it refuses to do — and if the skeptic from the copy brief reaches the
trust section and finds it specific enough to believe. Calm is the product; a landing
page that shouts has already contradicted the pitch.

## Licence note

If the project ships under AGPL-3.0 (the recommendation on the table), §13 requires that
users interacting with it over a network can get the source. In practice that is a
"Source" link in the footer of both the landing page and the app — so design the footer
with that slot from the start rather than bolting it on later.
