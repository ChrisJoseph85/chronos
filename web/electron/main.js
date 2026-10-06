// Chronos Electron shell (thin wrapper around web/dist).
// BOUNDARY (no web/src changes needed):
// - Server URL + instance key stay in the web UI's localStorage; this process never reads secrets.
// - Renderer notifications: preload exposes window.chronosNotify(title, body) -> IPC "chronos-notify"
//   -> native Notification here. The web UI calls window.chronosNotify?.(...) defensively when present
//   (timer start/stop/void, reminder-due, briefing-question, proposal-awaiting). A tiny renderer call
//   site is out of scope for this shell; IPC is the ONLY notification content source in main.
// - Main additionally toasts on page load failure (server-down/reconnect). No polling of /api/* here.
// - contextIsolation ON, nodeIntegration OFF (see BrowserWindow webPreferences below).
// - Auto-launch: --autostart launches hidden; registration is OS-level (Win/Mac: setLoginItemSettings,
//   Linux: user-level ~/.config/autostart/chronos.desktop, never sudo).
// - mac dmg is UNSIGNED (no-sign); Win NSIS exe + Linux AppImage+deb per dist config in package.json.
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

export const IPC_NOTIFY = "chronos-notify";
export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_SIZE = { width: 1280, height: 860 };
export const DEV_URL = "http://localhost:5173";
export const DIST_TARGETS = { linux: ["AppImage", "deb"], win: ["nsis"], mac: ["dmg"] }; // mac unsigned
export const isDev = (argv = process.argv) => argv.includes("--dev");
export const isAutostartLaunch = (argv = process.argv) => argv.includes("--autostart");
export const isValidNotify = (p) =>
  !!p && typeof p.title === "string" && p.title.trim() !== "" && p.title.length <= 200 &&
  typeof p.body === "string" && p.body.length <= 1000;
export const loginItemArgs = (on) => ({ openAtLogin: !!on });
export const desktopEntryText = (exec) =>
  `[Desktop Entry]\nType=Application\nName=Chronos\nExec="${exec}" --autostart\nX-GNOME-Autostart-enabled=true\n`;
export const distTargetsFor = (plat = process.platform) =>
  DIST_TARGETS[plat === "win32" ? "win" : plat === "darwin" ? "mac" : "linux"];
export const resolveLoadTarget = (argv = process.argv, dir = HERE) =>
  isDev(argv) ? { kind: "url", value: DEV_URL } : { kind: "file", value: path.join(dir, "..", "dist", "index.html") };
// Window-size memory: JSON in userData, no deps.
export const boundsFile = (userData) => path.join(userData, "window-bounds.json");
export function loadBounds(userData, f = fs) {
  try {
    const b = JSON.parse(f.readFileSync(boundsFile(userData), "utf8"));
    if (Number.isInteger(b.width) && Number.isInteger(b.height) && b.width >= 400 && b.height >= 300) return b;
  } catch { /* fall through to defaults */ }
  return { ...DEFAULT_SIZE };
}
export function saveBounds(userData, b, f = fs) {
  try {
    f.mkdirSync(userData, { recursive: true });
    f.writeFileSync(boundsFile(userData), JSON.stringify({ width: b.width, height: b.height, x: b.x, y: b.y }));
  } catch { /* userData may be unwritable; window still works */ }
}
// Single-instance: true when THIS process must quit (another instance holds the lock).
export const shouldQuitAsSecondInstance = (gotLock) => !gotLock;
// Linux autostart: user-level XDG entry only, never sudo. Returns the .desktop path.
export function setAutostartLinux(on, home = process.env.HOME ?? "", f = fs, exec = process.execPath) {
  const fp = path.join(home, ".config", "autostart", "chronos.desktop");
  if (on) {
    f.mkdirSync(path.dirname(fp), { recursive: true });
    f.writeFileSync(fp, desktopEntryText(exec));
  } else {
    try { f.unlinkSync(fp); } catch { /* already absent */ }
  }
  return fp;
}

async function boot() {
  const { app, BrowserWindow, Notification, ipcMain } = await import("electron");
  if (shouldQuitAsSecondInstance(app.requestSingleInstanceLock())) { app.quit(); return; }
  if (process.platform === "linux") { if (!isDev()) setAutostartLinux(true); }
  else app.setLoginItemSettings(loginItemArgs(true));
  const notify = (title, body) => {
    if (Notification.isSupported()) new Notification({ title, body }).show();
  };
  ipcMain.on(IPC_NOTIFY, (_e, p) => { if (isValidNotify(p)) notify(p.title, p.body); });
  await app.whenReady();
  const saved = loadBounds(app.getPath("userData"));
  const hidden = isAutostartLaunch();
  const win = new BrowserWindow({
    width: saved.width, height: saved.height, x: saved.x, y: saved.y, show: !hidden,
    webPreferences: { contextIsolation: true, nodeIntegration: false, preload: path.join(HERE, "preload.js") },
  });
  app.on("second-instance", () => { if (win.isMinimized()) win.restore(); win.focus(); });
  const persist = () => saveBounds(app.getPath("userData"), win.getBounds());
  win.on("resize", persist);
  win.on("move", persist);
  win.webContents.on("did-fail-load", (_e, code, desc) =>
    notify("Chronos server unreachable", `Load failed (${code}): ${desc}`));
  const target = resolveLoadTarget();
  if (target.kind === "url") await win.loadURL(target.value);
  else await win.loadFile(target.value);
  if (!hidden) win.show();
  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
  app.on("activate", () => win.show());
}

if (process.versions?.electron) void boot();
