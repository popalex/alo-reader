import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted Inter (the design system's typeface — tokens.css assumed it but it was
// never bundled, so the UI fell back to system-ui). The weight-axis variable font covers
// 100–900; unicode-range means the browser only fetches the ~48KB latin subset. Served
// from 'self', so it satisfies the CSP font-src.
import "@fontsource-variable/inter/wght.css";
import "./styles/tokens.css";
import "./styles/global.css";
import { App } from "./App";
import { initTheme } from "./app/theme";

const root = document.getElementById("root");
if (!root) {
  throw new Error("root element not found");
}

// Apply the saved colour-theme choice before first paint.
initTheme();

// The service worker precaches every asset for offline use. Registering it at `load`
// (the plugin's default) put that install and its ~40 downloads inside the first-load
// window, as a long task of its own. A few seconds later costs nothing: offline use
// needs the first visit to finish anyway.
// In `make dev` the plugin serves its dev service worker at dev-sw.js?dev-sw, as a
// module (devOptions in vite.config.ts), so offline stays testable there too.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    window.setTimeout(() => {
      const base = import.meta.env.BASE_URL;
      void navigator.serviceWorker.register(
        import.meta.env.DEV ? `${base}dev-sw.js?dev-sw` : `${base}sw.js`,
        { scope: base, type: import.meta.env.DEV ? "module" : "classic" },
      );
    }, 3000);
  });
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
