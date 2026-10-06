// Chronos app2 — integration: renderer build contract.
//
// Re-asserts the frozen build rules against the emitted bundle:
// single self-contained app2/renderer-dist/index.html, no leading-/
// asset refs, all 5 screens + AI row + shell present.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { BUILT, ROOT, readBuilt } = require('./harness');

test('build emits a single self-contained index.html', () => {
  assert.ok(fs.existsSync(BUILT), 'renderer-dist/index.html exists — run node app2/build-renderer.mjs');
  const html = readBuilt();
  assert.match(html, /<style>/);
  assert.match(html, /<script>/);
  assert.ok(html.length > 50000, `bundle looks complete, got ${html.length} bytes`);
  // Only index.html in renderer-dist (single-file contract).
  const entries = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules') continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else entries.push(path.relative(path.join(ROOT, 'renderer-dist'), p));
    }
  })(path.join(ROOT, 'renderer-dist'));
  assert.deepEqual(entries, ['index.html'], 'renderer-dist contains only index.html, got: ' + JSON.stringify(entries));
});

test('build has no leading-/ asset refs', () => {
  const html = readBuilt();
  assert.equal((html.match(/(src|href)\s*=\s*["']\//g) || []).length, 0, 'no leading-/ src/href');
  assert.equal((html.match(/url\(\s*["']?\//g) || []).length, 0, 'no leading-/ css url()');
  assert.equal((html.match(/@import\s+["']\//g) || []).length, 0, 'no leading-/ @import');
});

test('build contains all 5 screens, shell, AI row and discovery', () => {
  const html = readBuilt();
  for (const name of ['ChronosShell', 'ChronosPlanner', 'ChronosTimer', 'ChronosBriefing', 'ChronosStats', 'ChronosSettings', 'ChronosAiRow', 'ChronosDiscovery']) {
    assert.ok(html.includes(name), `bundle contains ${name}`);
  }
  for (const id of ['screen-planner', 'screen-timer', 'screen-briefing', 'screen-stats', 'screen-settings']) {
    assert.ok(html.includes(`id="${id}"`), `bundle contains section #${id}`);
  }
  for (const nav of ['planner', 'timer', 'briefing', 'stats', 'settings']) {
    assert.ok(html.includes(`data-screen-nav="${nav}"`), `bundle contains nav ${nav}`);
  }
});
