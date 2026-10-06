'use strict';

// hand-rolled bounds/panel store: defaults, persistence round-trip,
// corrupt-file recovery (never throws).

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { createStore, defaultStorePath, sanitizeBounds } = require('../main/store');

function tmpFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-store-'));
  return { dir, file: path.join(dir, 'window-state.json') };
}

describe('store', () => {
  it('defaultStorePath lands inside userData as window-state.json', () => {
    assert.equal(defaultStorePath('/ud'), path.join('/ud', 'window-state.json'));
  });

  it('loads defaults when the file is missing', () => {
    const { dir, file } = tmpFile();
    try {
      const s = createStore(file);
      const state = s.load();
      assert.equal(state.bounds.width, 1200);
      assert.equal(state.bounds.height, 800);
      assert.equal(state.sidebarCollapsed, false);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it('recovers cleanly from corrupt JSON', () => {
    const { dir, file } = tmpFile();
    try {
      fs.writeFileSync(file, '{{{not json');
      const s = createStore(file);
      assert.equal(s.load().bounds.width, 1200);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it('round-trips bounds + panels through set/save/load', () => {
    const { dir, file } = tmpFile();
    try {
      const s = createStore(file);
      s.setBounds({ width: 900, height: 700, x: 10, y: 20 });
      s.set('sidebarCollapsed', true);
      s.set('panels', { left: 240 });
      const fresh = createStore(file);
      const state = fresh.load();
      assert.equal(state.bounds.width, 900);
      assert.equal(state.bounds.x, 10);
      assert.equal(state.sidebarCollapsed, true);
      assert.deepEqual(state.panels, { left: 240 });
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it('sanitizes insane bounds back to defaults', () => {
    assert.equal(sanitizeBounds({ width: -5, height: 1e12 }).width, 1200);
    assert.equal(sanitizeBounds({ width: 0, height: 0 }).height, 800);
    assert.equal(sanitizeBounds(null).width, 1200);
  });
});
