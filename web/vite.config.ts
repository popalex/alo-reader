import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    react(),
    // PWA (WP-14): precache the app shell, serve already-loaded entries offline,
    // and make the app installable. The offline *mutation* queue lives in the app
    // (idb, replayed on `online`), not here — the SW only owns caching.
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      // No SW in `vite dev` (avoids stale-cache surprises during HMR); it's built
      // for preview/prod, which is what e2e drives through Caddy.
      devOptions: { enabled: false },
      includeAssets: ["favicon.ico", "apple-touch-icon-180x180.png"],
      manifest: {
        name: "alo reader",
        short_name: "alo",
        description: "A calm, keyboard-first RSS reader — early Gmail, for feeds.",
        theme_color: "#0e7c6d",
        background_color: "#f6f7f9",
        display: "standalone",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "pwa-64x64.png", sizes: "64x64", type: "image/png" },
          { src: "pwa-192x192.png", sizes: "192x192", type: "image/png" },
          { src: "pwa-512x512.png", sizes: "512x512", type: "image/png" },
          {
            src: "maskable-icon-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Precache the built shell (js/css/html/icons) for offline boot.
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            // Already-loaded streams/entries readable offline; fresh when online.
            urlPattern: /\/api\/v1\/(streams|entries)\//,
            handler: "NetworkFirst",
            options: {
              cacheName: "alo-entries",
              networkTimeoutSeconds: 3,
              expiration: { maxEntries: 500, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
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
