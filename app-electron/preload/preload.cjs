// Preload: minimal hardened bridge. contextIsolation stays ON and
// nodeIntegration OFF (see main.js). Secrets (server URL, instance key,
// provider keys) live in renderer localStorage only — they NEVER cross
// this bridge and are never written to userData JSON.
//
// NOTE: .cjs on purpose — Electron loads the preload as a classic script
// (package "type": "module" is NOT honored here), so ESM `import` syntax
// fatals with "Cannot use import statement outside a module".
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("chronos", {
  platform: process.platform,
  storeGet: (key) => ipcRenderer.invoke("chronos:store-get", key),
  storeSet: (key, value) => ipcRenderer.invoke("chronos:store-set", key, value),
  panelSet: (key, fraction) => ipcRenderer.invoke("chronos:panel-set", key, fraction),
  autostartGet: () => ipcRenderer.invoke("chronos:autostart-get"),
  autostartSet: (enabled) => ipcRenderer.invoke("chronos:autostart-set", enabled),
});
