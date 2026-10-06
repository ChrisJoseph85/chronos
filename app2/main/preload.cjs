// Preload: exposes ONLY window.chronos.notify. Never touches secrets.
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("chronos", {
  notify: (title, body, kind) => ipcRenderer.invoke("chronos-notify", { title, body, kind }),
});
