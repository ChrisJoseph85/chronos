// Chronos app2 UI-A — bundle contract tests.
// Single self-contained file; no window.chronos at import time.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { readBuilt } = require('./harness');

test('bundle is a single self-contained file', () => {
  const html = readBuilt();
  assert.match(html, /<style>/);
  assert.match(html, /<script>/);
  assert.equal((html.match(/(src|href)\s*=\s*["']\//g) || []).length, 0, 'no leading-/ asset refs');
  assert.equal((html.match(/url\(\s*["']?\//g) || []).length, 0, 'no leading-/ css urls');
});

test('renderer JS never references window.chronos at import time', () => {
  // The preload bridge may only be touched via call-time locals
  // (w.chronos); the literal `window.chronos` must not appear.
  const srcFiles = [
    '../renderer-src/shell/shell.js',
    '../renderer-src/screens/planner.js',
    '../renderer-src/screens/timer.js',
  ];
  for (const rel of srcFiles) {
    const raw = fs.readFileSync(path.join(__dirname, rel), 'utf8');
    // Strip comments — the property under test is about executable code.
    const text = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    assert.equal(
      /window\.chronos(?![A-Z])/.test(text), false,
      `${rel} contains a window.chronos reference`
    );
  }
  // UI-B owns its files and its own bridge usage; this asserts the UI-A
  // segments of the bundle carry no window.chronos reference.
  const html = readBuilt();
  const mine = ['shell/shell.js', 'screens/planner.js', 'screens/timer.js'];
  for (const rel of mine) {
    const marker = '/* --- ' + rel + ' --- */';
    const start = html.indexOf(marker);
    assert.ok(start !== -1, `bundle contains ${rel}`);
    const segment = html.slice(start, html.indexOf('<\/script>', start));
    const code = segment.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
    assert.equal(/window\.chronos(?![A-Z])/.test(code), false, `bundle segment ${rel} references window.chronos`);
  }
});
