// Corrupt-tolerant JSON store. Secrets NEVER persisted: only UI_KEYS round-trip.
import fs from "node:fs";
import path from "node:path";

export const UI_KEYS = ["bounds", "panels", "sidebar", "autostart", "notify", "serverUrl"];

export function loadStore(dir, f = fs) {
  const fp = path.join(dir, "chronos-ui.json");
  try {
    const raw = JSON.parse(f.readFileSync(fp, "utf8"));
    const out = {};
    for (const k of UI_KEYS) if (raw[k] !== undefined) out[k] = raw[k];
    return out;
  } catch { return {}; }
}

export function saveStore(dir, state, f = fs) {
  const fp = path.join(dir, "chronos-ui.json");
  const out = {};
  for (const k of UI_KEYS) if (state[k] !== undefined) out[k] = state[k];
  f.mkdirSync(dir, { recursive: true });
  f.writeFileSync(fp, JSON.stringify(out));
  return fp;
}
