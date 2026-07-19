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

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
