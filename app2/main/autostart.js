'use strict';

// Autostart helpers. Side effects are isolated behind injectable deps
// (fs-like, os-like, electron-app-like) so everything is unit-testable
// with plain node. Rules: Linux uses the per-user
// ~/.config/autostart/*.desktop entry (never sudo / system dirs);
// Windows + macOS use app.setLoginItemSettings.

const path = require('path');

const AUTOSTART_ARG = '--autostart';
const LINUX_DESKTOP_FILE = 'chronos.desktop';
const APP_NAME = 'Chronos';

function hasAutostartFlag(argv = process.argv) {
  const args = Array.isArray(argv) ? argv : [];
  return args.includes(AUTOSTART_ARG);
}

function getLinuxAutostartPath(homeDir) {
  const home =
    homeDir || (typeof process !== 'undefined' && process.env.HOME) || '/tmp';
  return path.join(home, '.config', 'autostart', LINUX_DESKTOP_FILE);
}

function quoteExec(execPath) {
  const p = String(execPath || '');
  // Quote only when needed; escape embedded double quotes.
  if (/["\s]/.test(p)) return `"${p.replace(/"/g, '\\"')}"`;
  return p;
}

function buildDesktopEntry({ execPath, appName = APP_NAME, comment = 'Chronos desktop app' } = {}) {
  if (typeof execPath !== 'string' || execPath.length === 0) {
    throw new Error('execPath must be a non-empty string');
  }
  const lines = [
    '[Desktop Entry]',
    'Type=Application',
    `Name=${appName}`,
    `Comment=${comment}`,
    `Exec=${quoteExec(execPath)} ${AUTOSTART_ARG}`,
    'Hidden=false',
    'NoDisplay=false',
    'X-GNOME-Autostart-enabled=true',
    'StartupNotify=false',
    '',
  ];
  return lines.join('\n');
}

// Pure decision helper: what should setAutostart do on this platform?
function autostartPlan(platform, enabled) {
  if (platform === 'linux') return { method: 'desktop-entry', enabled: !!enabled };
  if (platform === 'win32' || platform === 'darwin') {
    return { method: 'login-item-settings', enabled: !!enabled };
  }
  return { method: 'unsupported', enabled: !!enabled };
}

// Linux: write/remove the user-level .desktop entry. fsImpl defaults to
// node fs; tests inject a fake. Never touches system dirs, never sudo.
function setLinuxAutostart(
  enabled,
  { execPath, homeDir, fsImpl = require('fs') } = {},
) {
  const file = getLinuxAutostartPath(homeDir);
  if (!enabled) {
    try {
      if (fsImpl.existsSync(file)) fsImpl.unlinkSync(file);
    } catch {
      // best effort
    }
    return { file, enabled: false };
  }
  const content = buildDesktopEntry({ execPath });
  fsImpl.mkdirSync(path.dirname(file), { recursive: true });
  fsImpl.writeFileSync(file, content, { mode: 0o644 });
  return { file, enabled: true };
}

// Win/Mac: delegate to Electron's setLoginItemSettings. appLike is the
// Electron app object (injected so tests can use a stub).
function applyLoginItemSettings(appLike, enabled, { execPath, args } = {}) {
  if (!appLike || typeof appLike.setLoginItemSettings !== 'function') {
    throw new Error('app.setLoginItemSettings is not available');
  }
  const platform = appLike.platform || process.platform;
  if (platform === 'win32') {
    const launchArgs = Array.isArray(args) ? args : [AUTOSTART_ARG];
    appLike.setLoginItemSettings({
      openAtLogin: !!enabled,
      path: execPath || undefined,
      args: launchArgs,
    });
  } else {
    // darwin
    appLike.setLoginItemSettings({
      openAtLogin: !!enabled,
      openAsHidden: !!enabled,
    });
  }
  return { platform, enabled: !!enabled };
}

// Unified entry used by main.js settings toggle.
function setAutostartEnabled(
  enabled,
  { platform = process.platform, execPath, homeDir, fsImpl, appLike } = {},
) {
  const plan = autostartPlan(platform, enabled);
  if (plan.method === 'desktop-entry') {
    return { ...plan, ...setLinuxAutostart(enabled, { execPath, homeDir, fsImpl }) };
  }
  if (plan.method === 'login-item-settings') {
    if (!appLike) throw new Error('app object required for login-item settings');
    return { ...plan, ...applyLoginItemSettings(appLike, enabled, { execPath }) };
  }
  return { ...plan, reason: `platform ${platform} not supported` };
}

module.exports = {
  AUTOSTART_ARG,
  LINUX_DESKTOP_FILE,
  APP_NAME,
  hasAutostartFlag,
  getLinuxAutostartPath,
  buildDesktopEntry,
  autostartPlan,
  setLinuxAutostart,
  applyLoginItemSettings,
  setAutostartEnabled,
};
