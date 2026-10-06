'use strict';

// Frozen IPC contract: preload exposes EXACTLY window.chronos with
// { notify, onNavigate }. contextIsolation stays on, nodeIntegration stays
// off (enforced in main.js). Secrets stay in renderer localStorage; the
// preload never touches secrets.

const { contextBridge, ipcRenderer } = require('electron');

const NOTIFY_CHANNEL = 'chronos-notify';
const NAVIGATE_CHANNEL = 'chronos-navigate';

contextBridge.exposeInMainWorld('chronos', {
  // Renderer -> main only. Validated in main (notify.js); invalid payloads
  // are dropped silently. Returns void (fire-and-forget by contract).
  notify: (title, body) => {
    ipcRenderer.send(NOTIFY_CHANNEL, { title, body });
  },
  // Optional: main -> renderer navigation hint. Returns an unsubscribe fn.
  onNavigate: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, route) => callback(route);
    ipcRenderer.on(NAVIGATE_CHANNEL, listener);
    return () => ipcRenderer.removeListener(NAVIGATE_CHANNEL, listener);
  },
});
