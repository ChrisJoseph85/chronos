// Autostart: hidden --autostart launch.
// Linux: user-level ~/.config/autostart/chronos-electron.desktop (never
// sudo). Win/Mac: app.setLoginItemSettings. Pure helpers are unit-tested
// with an injectable fs; the Electron `app` object is injected too.

export const APP_ID = "chronos-electron";

export function desktopFileContent(execPath) {
  return (
    "[Desktop Entry]\n" +
    "Type=Application\n" +
    "Name=Chronos\n" +
    `Exec="${execPath}" --autostart --hidden\n` +
    "Hidden=false\n" +
    "NoDisplay=false\n" +
    "X-GNOME-Autostart-enabled=true\n"
  );
}

export function desktopFilePath(homeDir) {
  return `${homeDir}/.config/autostart/${APP_ID}.desktop`;
}

/** Linux apply. fs: {writeFileSync, unlinkSync, mkdirSync}. Returns "set"|"cleared". */
export function applyLinuxAutostart({ homeDir, execPath, enabled, fs }) {
  const path = desktopFilePath(homeDir);
  if (enabled) {
    fs.mkdirSync(`${homeDir}/.config/autostart`, { recursive: true });
    fs.writeFileSync(path, desktopFileContent(execPath), "utf8");
    return "set";
  }
  try {
    fs.unlinkSync(path);
  } catch {
    // already absent -> fine
  }
  return "cleared";
}

/**
 * Cross-platform apply.
 * @param {object} opts {platform, enabled, execPath, homeDir, fs, app}
 * app: Electron app (setLoginItemSettings / getLoginItemSettings).
 */
export function applyAutostart(opts) {
  const { platform, enabled } = opts;
  if (platform === "linux") {
    return { method: "desktop-file", state: applyLinuxAutostart(opts) };
  }
  if (platform === "win32" || platform === "darwin") {
    opts.app.setLoginItemSettings({
      openAtLogin: !!enabled,
      args: ["--autostart"],
    });
    return { method: "login-item", state: enabled ? "set" : "cleared" };
  }
  return { method: "unsupported", state: "cleared" };
}

export function isAutostart({ platform, homeDir, fs, app }) {
  if (platform === "linux") {
    try {
      fs.accessSync(desktopFilePath(homeDir));
      return true;
    } catch {
      return false;
    }
  }
  if ((platform === "win32" || platform === "darwin") && app) {
    try {
      return !!app.getLoginItemSettings({ args: ["--autostart"] }).openAtLogin;
    } catch {
      return false;
    }
  }
  return false;
}
