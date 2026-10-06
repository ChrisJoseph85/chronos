'use strict';

// Chronos app2 shell (main process). Electron is loaded lazily so this
// module can be required by plain-node unit tests (no display, no
// electron installed) to exercise the pure logic below.

const fs = require('fs');
const path = require('path');

const { AUTOSTART_ARG, hasAutostartFlag } = require('./autostart');
const { handleNotifyIpc } = require('./notify');
const { createStore, defaultStorePath } = require('./store');

const NOTIFY_CHANNEL = 'chronos-notify';
const NAVIGATE_CHANNEL = 'chronos-navigate';

let electron = null;
try {
  // eslint-disable-next-line global-require
  electron = require('electron');
} catch {
  electron = null; // plain-node test environment: pure logic still works.
}

// ---------------------------------------------------------------------------
// Pure, unit-testable logic (no electron required)
// ---------------------------------------------------------------------------

function isAutostartLaunch(argv = process.argv) {
  return hasAutostartFlag(argv);
}

// Single-instance: app.requestSingleInstanceLock() returns true for the
// first instance. A second instance must quit instead of opening a window.
function shouldQuitAsSecondInstance(gotLock) {
  return !gotLock;
}

// Where the renderer bundle lives. A sibling agent produces it; the shell
// must never create renderer content itself.
function defaultRendererIndexPath(fromDir = __dirname) {
  return path.join(fromDir, '..', 'renderer-dist', 'index.html');
}

const FALLBACK_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Chronos — renderer not built</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; display: grid;
         place-items: center; min-height: 100vh; background: #111; color: #eee; }
  main { max-width: 36rem; padding: 2rem; text-align: center; }
  code { background: #222; padding: 0.1rem 0.4rem; border-radius: 4px; }
</style>
</head>
<body>
<main>
  <h1>Renderer not built</h1>
  <p>The Chronos shell started correctly, but no renderer bundle was found.</p>
  <p>Expected file: <code>app2/renderer-dist/index.html</code></p>
  <p>Build the renderer bundle, then relaunch the app. Nothing else is wrong.</p>
</main>
</body>
</html>
`;

// Resolve what the BrowserWindow should load. Never throws, never crashes:
// missing renderer -> clean fallback page descriptor.
function resolveLoadTarget(indexPath, existsFn = fs.existsSync) {
  let exists = false;
  try {
    exists = !!existsFn(indexPath);
  } catch {
    exists = false;
  }
  if (exists) return { type: 'file', filePath: indexPath };
  return { type: 'fallback-html', html: FALLBACK_HTML };
}

// Window visibility for autostart: hidden launch, no steal-focus.
function windowShowOptions(argv = process.argv) {
  const hidden = isAutostartLaunch(argv);
  return { show: !hidden, startHidden: hidden };
}

// ---------------------------------------------------------------------------
// Electron runtime (only runs when electron is present and this is the entry)
// ---------------------------------------------------------------------------

let mainWindow = null;
let store = null;

function getStore(app) {
  if (!store) store = createStore(defaultStorePath(app.getPath('userData')));
  return store;
}

function showNotification(title, body) {
  const { Notification } = electron;
  if (Notification && Notification.isSupported && Notification.isSupported()) {
    const n = new Notification({ title, body });
    n.show();
    return true;
  }
  return false;
}

function loadInto(win, target) {
  if (target.type === 'file') return win.loadFile(target.filePath);
  return win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(target.html)}`);
}

function createMainWindow(app, BrowserWindow, argv = process.argv) {
  const appStore = getStore(app);
  const state = appStore.load();
  const visibility = windowShowOptions(argv);

  const win = new BrowserWindow({
    width: state.bounds.width,
    height: state.bounds.height,
    x: state.bounds.x,
    y: state.bounds.y,
    show: visibility.show,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, // frozen contract: always on
      nodeIntegration: false, // frozen contract: always off
      sandbox: true,
    },
  });

  const indexPath = defaultRendererIndexPath(__dirname);
  const target = resolveLoadTarget(indexPath);
  loadInto(win, target).catch(() => {
    win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(FALLBACK_HTML)}`);
  });

  if (visibility.show) win.once('ready-to-show', () => win.show());

  const persistBounds = () => {
    try {
      appStore.setBounds(win.getBounds());
    } catch {
      // best effort
    }
  };
  win.on('resize', persistBounds);
  win.on('move', persistBounds);
  win.on('close', persistBounds);
  win.on('closed', () => {
    if (mainWindow === win) mainWindow = null;
  });

  return win;
}

function startApp(e = electron, argv = process.argv) {
  if (!e) throw new Error('Electron is not available');
  const { app, BrowserWindow, ipcMain } = e;

  const gotLock = app.requestSingleInstanceLock();
  if (shouldQuitAsSecondInstance(gotLock)) {
    app.quit();
    return null;
  }

  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  ipcMain.on(NOTIFY_CHANNEL, (_event, payload) => {
    handleNotifyIpc(payload, ({ title, body }) => showNotification(title, body));
  });

  const ready = () => {
    mainWindow = createMainWindow(app, BrowserWindow, argv);
  };
  if (app.isReady && app.isReady()) ready();
  else app.whenReady().then(ready);

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
  app.on('activate', () => {
    if (mainWindow === null && BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createMainWindow(app, BrowserWindow, argv);
    }
  });

  return true;
}

if (require.main === module && electron) {
  startApp(electron, process.argv);
}

module.exports = {
  NOTIFY_CHANNEL,
  NAVIGATE_CHANNEL,
  AUTOSTART_ARG,
  FALLBACK_HTML,
  isAutostartLaunch,
  shouldQuitAsSecondInstance,
  defaultRendererIndexPath,
  resolveLoadTarget,
  windowShowOptions,
  startApp,
};
