// Post-process vite output so the renderer is ONE self-contained file.
// Inlines every <script src> and <link rel=stylesheet> into dist/index.html
// so the app works over file:// with ZERO external refs (belt & braces on
// top of vite base './'). Fails the build if any absolute leading-/ asset
// ref remains.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const indexPath = join(dist, "index.html");

let html = readFileSync(indexPath, "utf8");

// Inline local stylesheets.
html = html.replace(/<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g, (tag, href) => {
  if (/^(https?:|data:|\/)/.test(href)) return tag;
  const p = join(dist, href.replace(/^\.\//, ""));
  if (!existsSync(p)) return tag;
  return `<style>${readFileSync(p, "utf8")}</style>`;
});

// Inline local scripts (vite emits type="module"; inline keeps semantics,
// and bundled output has no external imports, so file:// is safe).
html = html.replace(/<script([^>]*)src="([^"]+)"([^>]*)><\/script>/g, (tag, pre, src, post) => {
  if (/^(https?:|data:|\/)/.test(src)) return tag;
  const p = join(dist, src.replace(/^\.\//, ""));
  if (!existsSync(p)) return tag;
  const type = /type="module"/.test(pre + post) ? ` type="module"` : "";
  return `<script${type}>${readFileSync(p, "utf8")}</script>`;
});

writeFileSync(indexPath, html);

// Hard verification: no absolute asset refs allowed.
const bad = [...html.matchAll(/(?:src|href)="(\/[^"]*)"/g)].map((m) => m[1]);
if (bad.length > 0) {
  console.error(`FORBIDDEN absolute asset refs in dist/index.html: ${bad.join(", ")}`);
  process.exit(1);
}
const remaining = [...html.matchAll(/(?:src|href)="(\.[^"]*)"/g)].map((m) => m[1]);
console.log(`inline-dist: single-file index.html, external relative refs left: ${remaining.length}`);
