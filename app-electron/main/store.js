// Hand-rolled userData JSON store (no deps). Holds ONLY non-secret UI
// state: window bounds, panel sizes, sidebar, autostart flag. Secrets
// (server URL, instance key, provider keys) live in renderer localStorage
// and never touch this file.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const DEFAULTS = {
  window: null, // {x,y,width,height,maximized} | null
  panels: {}, // splitterKey -> fraction 0..1
  sidebarCollapsed: false,
};

export function createStore(filePath) {
  let data = { ...DEFAULTS };
  try {
    const raw = readFileSync(filePath, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") data = { ...DEFAULTS, ...parsed };
  } catch {
    // missing/corrupt -> start fresh (corrupt file is overwritten on save)
  }

  function save() {
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");
  }

  return {
    path: filePath,
    get(key) {
      return key === undefined ? { ...data } : data[key];
    },
    set(key, value) {
      data[key] = value;
      save();
    },
    setPanel(key, fraction) {
      const f = Math.min(0.9, Math.max(0.1, Number(fraction) || 0.5));
      data.panels = { ...data.panels, [key]: f };
      save();
      return f;
    },
    reset() {
      data = { ...DEFAULTS };
      save();
    },
  };
}
