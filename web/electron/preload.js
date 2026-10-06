// Chronos preload: exposes ONLY window.chronosNotify(title, body). No secrets touched;
// server URL + instance key stay in the web UI's localStorage (see main.js header for boundary).
// Web UI calls window.chronosNotify?.(title, body) defensively when present.
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("chronosNotify", (title, body) => {
  ipcRenderer.send("chronos-notify", { title, body });
});
