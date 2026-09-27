// The budget covers what the page actually loads at startup: the entry script,
// every chunk index.html modulepreloads, and the stylesheets. Read from the built
// index.html rather than matched by name, because Rollup names shared chunks after
// whatever module it split out (jsx-runtime-*.js holds React once dialogs are lazy),
// and a glob such as app-*.js then silently stops counting React.
const { readFileSync } = require("node:fs");

const html = readFileSync(`${__dirname}/dist/index.html`, "utf8");
const initial = [...html.matchAll(/(?:src|href)="\/app\/(assets\/[^"]+\.(?:js|css))"/g)].map(
  (m) => `dist/${m[1]}`,
);
if (initial.length === 0) throw new Error("no assets found in dist/index.html; run the build first");

module.exports = [
  {
    name: "main app (everything index.html loads at startup, gzip)",
    path: initial,
    gzip: true,
    limit: "180 kB",
  },
];
