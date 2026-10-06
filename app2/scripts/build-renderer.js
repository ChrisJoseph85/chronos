// Concatenate renderer classic scripts into ONE self-contained dist/index.html.
// Fails the build if any absolute leading-/ asset ref remains.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const R = (p) => readFileSync(join(root, p), "utf8");
const ORDER = [
  "renderer/api.js",
  "renderer/discovery-client.js",
  "renderer/ai-row.js",
  "renderer/screens/planner.js",
  "renderer/screens/timer.js",
  "renderer/screens/briefing.js",
  "renderer/screens/stats.js",
  "renderer/screens/settings.js",
  "renderer/boot.js",
];
let html = R("renderer/shell.html");
const css = R("renderer/app.css");
const js = ORDER.map(R).join("\n;\n");
html = html.replace("<!--STYLE-->", `<style>${css}</style>`);
html = html.replace("<!--SCRIPTS-->", `<script>${js}</script>`);
if (/(src|href)="\/[^"]*"/.test(html)) {
  console.error("BUILD-FAIL: absolute asset ref found");
  process.exit(1);
}
mkdirSync(join(root, "dist"), { recursive: true });
writeFileSync(join(root, "dist", "index.html"), html);
console.log(`BUILD-OK ${html.length} bytes, ${ORDER.length} scripts inlined`);
