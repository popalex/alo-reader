import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  // The app lives under /app/ so that / can be the landing page on the public
  // instance (WP-17). Vite's base is fixed at build time, so this is one value for
  // both auth modes: a self-host instance redirects / to /app/ rather than getting
  // a second build. Caddy's handle_path strips the prefix again server-side.
  base: "/app/",
  plugins: [
    react(),
    // PWA (WP-14): precache the app shell, serve already-loaded entries offline,
    // and make the app installable. The offline *mutation* queue lives in the app
    // (idb, replayed on `online`), not here — the SW only owns caching.
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      // Serve the SW in `vite dev` too, so offline/PWA is testable with `make dev`
      // (not just the prod build). vite-plugin-pwa's dev SW doesn't precache built
      // assets, so HMR still serves fresh code.
      devOptions: { enabled: true, type: "module", navigateFallback: "/app/index.html" },
      includeAssets: ["favicon.ico", "apple-touch-icon-180x180.png"],
      manifest: {
        name: "alo reader",
        short_name: "alo",
        description: "A calm, keyboard-first RSS reader — early Gmail, for feeds.",
        theme_color: "#0e7c6d",
        background_color: "#f6f7f9",
        display: "standalone",
        start_url: "/app/",
        scope: "/app/",
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
        navigateFallback: "/app/index.html",
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
          {
            // Small app-shell data (config/sidebar/counts) so the app actually
            // boots offline with last-known state instead of the /config error.
            //
            // Deliberately no networkTimeoutSeconds: this is the data the user
            // *mutates* (rename a feed, move it, mark read), and the refetch that
            // follows a mutation must not be answered from the cache. A timeout
            // here silently served the pre-mutation list whenever the API took
            // longer than it to answer, leaving the sidebar wrong until something
            // else happened to refetch. Offline boot is unaffected — a fetch with
            // no network rejects immediately and falls back to the cache; the
            // timeout only ever mattered for a connected-but-hanging network.
            urlPattern: /\/api\/v1\/(config|me|folders|subscriptions|counts)\b/,
            handler: "NetworkFirst",
            options: {
              cacheName: "alo-app",
              expiration: { maxEntries: 40, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  build: {
    rollupOptions: {
      output: {
        // Name the entry chunk `app-*.js` so the size-limit budget measures only the
        // initial bundle. Lazy chunks keep `[name]-*.js` (some vendored package index
        // modules chunk as `index-*.js`), which must not be summed into the budget.
        entryFileNames: "assets/app-[hash].js",
      },
    },
  },
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
    // jsdom lacks IndexedDB (offline queue) and matchMedia (responsive hook).
    setupFiles: ["./tests/setup.ts"],
    // Playwright specs live in e2e/ and must not be collected by Vitest.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
