// Headless smoke: builds renderer, asserts bundle integrity, exits.
// Never launches Electron (no display on CI-less boxes). Exit non-zero on fail.
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
execSync("npm run build:renderer", { stdio: "inherit" });
const html = readFileSync("dist/index.html", "utf8");
for (const needle of ["Chronos.screens.planner", "Chronos.screens.timer", "Chronos.screens.briefing",
  "Chronos.screens.stats", "Chronos.screens.settings", "ChronosAiRow", "ChronosBoot"]) {
  if (!html.includes(needle)) { console.error(`SMOKE-FAIL missing ${needle}`); process.exit(1); }
}
console.log("SMOKE-RESULT ok");
