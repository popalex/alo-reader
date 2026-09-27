// Write a .br and a .gz next to every text file in dist/, at maximum quality, for
// Caddy's `precompressed br gzip` (deploy/Caddyfile). Compressing once at build time
// is what makes brotli-11 affordable: app.js comes out about 15% smaller than the
// gzip Caddy's `encode` produces per request. Runs after `vite build`, so the
// service worker and manifest get siblings too.
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";

const dist = new URL("../dist/", import.meta.url).pathname;
const files = (await readdir(dist, { recursive: true })).filter((f) =>
  /\.(js|css|html|svg|json|webmanifest)$/.test(f),
);
await Promise.all(
  files.map(async (f) => {
    const path = join(dist, f);
    const body = await readFile(path);
    const br = brotliCompressSync(body, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_SIZE_HINT]: body.length,
      },
    });
    await writeFile(`${path}.br`, br);
    await writeFile(`${path}.gz`, gzipSync(body, { level: 9 }));
  }),
);
console.log(`precompressed ${files.length} files (br + gz)`);
