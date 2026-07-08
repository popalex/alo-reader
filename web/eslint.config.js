// Flat ESLint config for the SPA. Scope is correctness, not style (Prettier/the
// editor own formatting): the TypeScript recommended rules, the React Hooks
// rules that catch the mistakes this codebase is prone to (bad hook deps, hooks
// called conditionally), and react-refresh so component modules stay HMR-safe.
// Runs in CI alongside `tsc` (see .github/ci.yml).

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Generated / build output — never linted.
  { ignores: ["dist", "coverage", "src/api/schema.d.ts"] },

  // App source (browser).
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },

  // Tests, e2e specs and tooling config run under Node with test globals.
  {
    files: ["tests/**", "e2e/**", "*.config.{ts,js}"],
    languageOptions: {
      globals: { ...globals.node, ...globals.browser },
    },
  },
);
