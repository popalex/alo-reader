import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

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
