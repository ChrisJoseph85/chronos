'use strict';

// autostart: --autostart flag, Linux user .desktop entry, login-item settings.

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const {
  AUTOSTART_ARG,
  hasAutostartFlag,
  getLinuxAutostartPath,
  buildDesktopEntry,
  autostartPlan,
  setLinuxAutostart,
  applyLoginItemSettings,
  setAutostartEnabled,
} = require('../main/autostart');

describe('autostart flag', () => {
  it('detects --autostart anywhere in argv', () => {
    assert.equal(hasAutostartFlag(['electron', '.', '--autostart']), true);
    assert.equal(hasAutostartFlag(['--autostart']), true);
  });

  it('is false without the flag', () => {
    assert.equal(hasAutostartFlag(['electron', '.']), false);
    assert.equal(hasAutostartFlag([]), false);
  });

  it('does not match lookalikes', () => {
    assert.equal(hasAutostartFlag(['--autostartX', '--no-autostart']), false);
  });
});

describe('linux desktop entry', () => {
  it('lives under user ~/.config/autostart (never sudo/system dirs)', () => {
    const p = getLinuxAutostartPath('/home/tester');
    assert.equal(p, path.join('/home/tester', '.config', 'autostart', 'chronos.desktop'));
    assert.ok(!p.startsWith('/etc') && !p.startsWith('/usr'), 'must be user-level');
  });

  it('entry content launches hidden with --autostart', () => {
    const content = buildDesktopEntry({ execPath: '/opt/Chronos/chronos' });
    assert.ok(content.includes('[Desktop Entry]'));
    assert.ok(content.includes('Type=Application'));
    assert.ok(content.includes(`Exec=/opt/Chronos/chronos ${AUTOSTART_ARG}`));
    assert.ok(content.includes('X-GNOME-Autostart-enabled=true'));
    assert.ok(!content.toLowerCase().includes('sudo'), 'must never use sudo');
  });

  it('quotes exec paths containing spaces', () => {
    const content = buildDesktopEntry({ execPath: '/opt/My Apps/chronos' });
    assert.ok(content.includes('Exec="/opt/My Apps/chronos" --autostart'));
  });

  it('throws on empty execPath', () => {
    assert.throws(() => buildDesktopEntry({ execPath: '' }));
  });

  it('writes and removes the entry via injected fs (no real fs touched)', () => {
    const files = new Map();
    const fsFake = {
      mkdirSync: () => {},
      writeFileSync: (f, c) => files.set(f, String(c)),
      existsSync: (f) => files.has(f),
      unlinkSync: (f) => files.delete(f),
    };
    const on = setLinuxAutostart(true, { execPath: '/opt/c', homeDir: '/home/t', fsImpl: fsFake });
    assert.equal(on.enabled, true);
    assert.ok(files.has(on.file));
    assert.ok(files.get(on.file).includes('--autostart'));
    const off = setLinuxAutostart(false, { homeDir: '/home/t', fsImpl: fsFake });
    assert.equal(off.enabled, false);
    assert.equal(files.size, 0);
  });
});

describe('login-item settings (win/mac)', () => {
  it('win32 passes --autostart args', () => {
    const calls = [];
    applyLoginItemSettings(
      { platform: 'win32', setLoginItemSettings: (o) => calls.push(o) },
      true,
      { execPath: 'C:\\Chronos\\c.exe' },
    );
    assert.equal(calls.length, 1);
    assert.equal(calls[0].openAtLogin, true);
    assert.deepEqual(calls[0].args, [AUTOSTART_ARG]);
  });

  it('darwin uses openAtLogin + openAsHidden', () => {
    const calls = [];
    applyLoginItemSettings(
      { platform: 'darwin', setLoginItemSettings: (o) => calls.push(o) },
      true,
      {},
    );
    assert.equal(calls[0].openAtLogin, true);
    assert.equal(calls[0].openAsHidden, true);
  });

  it('disable turns openAtLogin off', () => {
    const calls = [];
    applyLoginItemSettings(
      { platform: 'darwin', setLoginItemSettings: (o) => calls.push(o) },
      false,
      {},
    );
    assert.equal(calls[0].openAtLogin, false);
  });

  it('throws without an app object', () => {
    assert.throws(() => applyLoginItemSettings(null, true));
  });
});

describe('autostartPlan / setAutostartEnabled routing', () => {
  it('linux -> desktop-entry, win/mac -> login-item-settings', () => {
    assert.equal(autostartPlan('linux', true).method, 'desktop-entry');
    assert.equal(autostartPlan('win32', true).method, 'login-item-settings');
    assert.equal(autostartPlan('darwin', true).method, 'login-item-settings');
    assert.equal(autostartPlan('sunos', true).method, 'unsupported');
  });

  it('routes linux through the desktop entry with fake fs', () => {
    const files = new Map();
    const fsFake = {
      mkdirSync: () => {},
      writeFileSync: (f, c) => files.set(f, String(c)),
      existsSync: (f) => files.has(f),
      unlinkSync: (f) => files.delete(f),
    };
    const r = setAutostartEnabled(true, {
      platform: 'linux', execPath: '/opt/c', homeDir: '/home/t', fsImpl: fsFake,
    });
    assert.equal(r.method, 'desktop-entry');
    assert.equal(files.size, 1);
  });

  it('routes win32 through the app object', () => {
    const calls = [];
    const r = setAutostartEnabled(true, {
      platform: 'win32',
      execPath: 'c.exe',
      appLike: { platform: 'win32', setLoginItemSettings: (o) => calls.push(o) },
    });
    assert.equal(r.method, 'login-item-settings');
    assert.equal(calls.length, 1);
  });
});
