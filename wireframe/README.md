# Wireframe — style directions for WP-09

Five full mockups of the alo-reader three-pane UI. **Same markup and same
content in all five** (CSS Zen Garden style) so the only variable is the visual
direction. The three-pane *shape and behaviour* are fixed by `DESIGN.md §1.7`;
these pin down the free axes — typography, palette, density, light/dark — that
WP-09 has to decide.

## Open

Open **`index.html`** for the chooser, or any of the pages directly:

| File | Direction | Character |
|---|---|---|
| `console.html`  | Console  | Light monospace developer tool; teal, TUI inverse selection |
| `studio.html`   | Studio   | Modern muted product UI; Inter, restrained indigo — the safe ship |
| `reader.html`   | Reader   | Warm editorial; serif reading pane, deep-teal accent |
| `classic.html`  | Classic  | Authentic early-Gmail; Arial, max density, pale-yellow selected row |
| `nocturne.html` | Nocturne | Calm low-contrast dark; IBM Plex Sans, soft slate, gentle green |

Best viewed at desktop width. Live pages pull display faces from Google Fonts;
they fall back to strong system stacks offline.

## Regenerate

Everything is generated from one script so the markup stays identical:

```
python build.py
```

`shots/` holds reference screenshots (regenerate with headless Chromium).
