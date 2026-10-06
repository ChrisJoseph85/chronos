// Chronos main process. ESM, no top-level electron import (testable).
// --autostart: launch hidden. --smoke: print SMOKE-RESULT, exit 0 (10s guard).
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { isAutostartLaunch } from "./autostart.js";
import { loadStore, saveStore } from "./store.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const isValidNotify = (p) =>
  !!p && typeof p.title === "string" && p.title.trim() !== "" && p.title.length <= 200 &&
  typeof p.body === "string" && p.body.length <= 1000;

async function run() {
  const { app, BrowserWindow, ipcMain, Notification, shell } = await import("electron");
  if (!app.requestSingleInstanceLock()) { app.quit(); return; }
  const hidden = isAutostartLaunch();
  await app.whenReady();
  const userDir = app.getPath("userData");
  const ui = loadStore(userDir);
  const b = ui.bounds ?? { width: 1280, height: 860 };
  const win = new BrowserWindow({
    ...b, show: !hidden,
    webPreferences: { preload: path.join(HERE, "preload.cjs"), contextIsolation: true, nodeIntegration: false },
  });
  win.on("close", () => saveStore(userDir, { ...ui, bounds: win.getBounds() }));
  ipcMain.handle("chronos-notify", (_e, p) => {
    if (!isValidNotify(p)) return false;
    if ((ui.notify ?? {})[p.kind ?? "timer"] === false) return false;
    new Notification({ title: p.title.trim(), body: p.body }).show();
    return true;
  });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  win.webContents.on("did-fail-load", () => {
    new Notification({ title: "Chronos", body: "UI failed to load — reinstall the app." }).show();
  });
  await win.loadFile(path.join(HERE, "..", "dist", "index.html"));
  if (hidden) win.hide();
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) run().catch((e) => { console.error(e); process.exit(1); });
