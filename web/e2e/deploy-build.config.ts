// The app's own Vite config, plus one statement appended to the entry module.
// deploy-update.spec.ts builds the app twice with different values: same source,
// different bytes, so the second build has new file hashes and a new service worker
// manifest, the way a real deploy does. A comment banner would not do: Vite 8 hashes
// chunks before banners are added, so both builds came out identical. Nothing in the
// app reads the value.

import { defineConfig, mergeConfig, type Plugin } from "vite";

import base from "../vite.config.ts";

const build = JSON.stringify(process.env.ALO_E2E_BUILD ?? "?");

const markBuild: Plugin = {
  name: "alo-e2e-mark-build",
  apply: "build",
  transform(code, id) {
    if (!id.endsWith("/src/main.tsx")) return null;
    return { code: `${code}\nglobalThis.__ALO_E2E_BUILD__ = ${build};\n`, map: null };
  },
};

export default mergeConfig(base, defineConfig({ plugins: [markBuild] }));
