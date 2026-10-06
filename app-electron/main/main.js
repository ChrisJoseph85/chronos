// Chronos Electron main process: window bounds persistence, autostart,
// hardened webPreferences (contextIsolation ON, nodeIntegration OFF).
// Renderer loads dist/index.html from DISK (loadFile) — no web server.
import { app, BrowserWindow, ipcMain } from "electron";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import fs from "node:fs";
import { createStore } from "./store.js";
import { applyAutostart, isAutostart } from "./autostart.js";

const here = dirname(fileURLToPath(import.meta.url));
const APP_ROOT = join(here, "..");
const DIST_INDEX = join(APP_ROOT, "dist", "index.html");

const hiddenLaunch = process.argv.includes("--autostart") || process.argv.includes("--hidden");
const smokeMode = process.argv.includes("--smoke");

if (smokeMode) {
  // Headless smoke: no X needed. Loads the real renderer bundle from disk
  // and reports console/page errors.
  app.commandLine.appendSwitch("headless");
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("no-sandbox");
  app.commandLine.appendSwitch("disable-dev-shm-usage");
  app.commandLine.appendSwitch("no-zygote");
  app.disableHardwareAcceleration();
  // Hard watchdog: never hang CI.
  setTimeout(() => {
    console.error("SMOKE-FAIL watchdog timeout (30s)");
    app.exit(2);
  }, 30000).unref?.();
}

const store = createStore(join(app.getPath("userData"), "chronos-electron.json"));

let win = null;

function windowOptions() {
  const saved = store.get("window");
  const opts = {
    width: 1180,
    height: 760,
    minWidth: 620,
    minHeight: 480,
    show: false,
    backgroundColor: "#14161c",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: join(APP_ROOT, "preload", "preload.cjs"),
    },
  };
  if (saved && Number.isFinite(saved.width) && Number.isFinite(saved.height)) {
    opts.width = Math.max(620, saved.width);
    opts.height = Math.max(480, saved.height);
    if (Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
      opts.x = saved.x;
      opts.y = saved.y;
    }
  }
  return { opts, maximized: !!(saved && saved.maximized) };
}

async function createWindow() {
  const { opts, maximized } = windowOptions();
  win = new BrowserWindow(opts);

  const persistBounds = () => {
    if (!win || win.isDestroyed()) return;
    try {
      const b = win.getBounds();
      store.set("window", { ...b, maximized: win.isMaximized() });
    } catch {
      // shutdown race -> ignore
    }
  };
  win.on("resize", persistBounds);
  win.on("move", persistBounds);
  win.on("close", persistBounds);

  if (smokeMode) {
    const errors = [];
    const verbose = process.argv.includes("--smoke-verbose");
    win.webContents.on("console-message", (_e, _level, message) => {
      if (verbose) console.log(`SMOKE-CONSOLE ${_level}: ${message}`);
      if (/error|failed|uncaught/i.test(message)) errors.push(message);
    });
    win.webContents.on("page-title-updated", () => {});
    const failures = [];
    win.webContents.on("did-fail-load", (_e, code, desc, url) => {
      failures.push(`load-fail ${code} ${desc} ${url}`);
    });
    win.webContents.session.webRequest.onCompleted((d) => {
      if (d.statusCode >= 400) failures.push(`${d.statusCode} ${d.url}`);
    });
    try {
      await win.loadFile(DIST_INDEX);
      await win.webContents.executeJavaScript(
        `new Promise((res) => {
           const t0 = Date.now();
           (function wait() {
             const v = document.getElementById('view');
             const ok = v && v.dataset.ready === '1';
             if (ok || Date.now() - t0 > 8000) res({
               ready: !!ok,
               sidebar: !!document.getElementById('sidebar'),
               views: document.querySelectorAll('#sidebar [data-view]').length,
             });
             else setTimeout(wait, 100);
           })();
         })`,
        true,
      ).then((state) => {
        console.log(`SMOKE-RESULT ${JSON.stringify({ ...state, errors, failures })}`);
        if (!state.ready || state.views < 5) {
          console.error("SMOKE-FAIL renderer did not reach ready state");
          process.exitCode = 1;
        }
      });
    } catch (err) {
      console.error(`SMOKE-FAIL loadFile: ${err && err.message}`);
      process.exitCode = 1;
    } finally {
      app.quit();
    }
    return;
  }

  await win.loadFile(DIST_INDEX);
  if (maximized) win.maximize();
  if (!hiddenLaunch) win.show();
  else win.hide();
  win.once("ready-to-show", () => {
    if (!hiddenLaunch && !win.isVisible()) win.show();
  });
}

// ---- preload bridge (no secrets cross here) ----
ipcMain.handle("chronos:store-get", (_e, key) => store.get(key));
ipcMain.handle("chronos:store-set", (_e, key, value) => {
  store.set(key, value);
  return true;
});
ipcMain.handle("chronos:panel-set", (_e, key, fraction) => store.setPanel(key, fraction));
ipcMain.handle("chronos:autostart-get", () =>
  isAutostart({ platform: process.platform, homeDir: homedir(), fs, app }),
);
ipcMain.handle("chronos:autostart-set", (_e, enabled) => {
  const res = applyAutostart({
    platform: process.platform,
    enabled: !!enabled,
    execPath: process.execPath,
    homeDir: homedir(),
    fs,
    app,
  });
  store.set("autostart", !!enabled);
  return res;
});

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
