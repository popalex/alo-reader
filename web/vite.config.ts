/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { configDefaults } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Dev: forward API calls to the api service (Caddy handles this in prod).
    proxy: {
      "/api": {
        target: "http://api:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    // Playwright specs live in e2e/ and must not be collected by Vitest.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
