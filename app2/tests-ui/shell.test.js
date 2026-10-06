// Chronos app2 UI-A — shell click-through tests.
// Click each nav -> screen visible; collapse persists; boot is offline-first.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeStub, load, tick, visible } = require('./harness');

const NAVS = [
  ['planner', 'screen-planner'],
  ['timer', 'screen-timer'],
  ['briefing', 'screen-briefing'],
  ['stats', 'screen-stats'],
  ['settings', 'screen-settings'],
];

test('boot performs zero network calls (offline first paint)', async () => {
  const stub = makeStub([]);
  const dom = load(stub);
  await tick();
  assert.equal(stub.calls.length, 0, 'expected no fetch at boot, got: ' + JSON.stringify(stub.calls));
  const doc = dom.window.document;
  assert.ok(doc.getElementById('sidebar'), 'sidebar present');
  assert.ok(visible(doc, 'screen-planner'), 'planner visible by default');
});

test('no window.chronos dependency at import/startup', async () => {
  const dom = load(makeStub([]));
  await tick();
  assert.equal(typeof dom.window.chronos, 'undefined');
  // Planner + timer still rendered their offline states without the bridge.
  assert.ok(dom.window.document.getElementById('planner-calendar'));
  assert.ok(dom.window.document.getElementById('timer-start'));
});

test('click each nav -> its screen visible, others hidden', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  for (const [nav, section] of NAVS) {
    const btn = doc.querySelector(`[data-screen-nav="${nav}"]`);
    assert.ok(btn, `nav button for ${nav} exists`);
    btn.click();
    for (const [, sec] of NAVS) {
      assert.equal(visible(doc, sec), sec === section, `${nav} click: ${sec} visibility`);
    }
    assert.equal(btn.getAttribute('aria-current'), 'page');
  }
});

test('collapse toggle collapses to icons and persists', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  const sidebar = doc.getElementById('sidebar');
  const collapse = doc.getElementById('sidebar-collapse');
  assert.ok(collapse, 'collapse button exists');
  assert.ok(!sidebar.classList.contains('collapsed'));
  collapse.click();
  assert.ok(sidebar.classList.contains('collapsed'));
  assert.equal(dom.window.localStorage.getItem('chronos.sidebar.collapsed'), '1');
  collapse.click();
  assert.ok(!sidebar.classList.contains('collapsed'));
  assert.equal(dom.window.localStorage.getItem('chronos.sidebar.collapsed'), '0');
});

test('collapsed state restored from storage on boot', async () => {
  const dom = load(makeStub([]), { 'chronos.sidebar.collapsed': '1' });
  await tick();
  assert.ok(dom.window.document.getElementById('sidebar').classList.contains('collapsed'));
});

test('server-down boot still renders; lazy click shows banner', async () => {
  const stub = makeStub([]);
  stub.fail = true; // every fetch throws
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  // Empty states rendered despite dead server.
  assert.match(doc.getElementById('planner-node-list').textContent, /No nodes loaded yet/);
  assert.equal(doc.getElementById('global-banner').hidden, true);
  doc.getElementById('planner-load-nodes').click();
  await tick();
  const banner = doc.getElementById('global-banner');
  assert.equal(banner.hidden, false, 'banner shown on failure');
  assert.match(banner.textContent, /Nodes load failed/);
});

test('sidebar drag splitter present and wired', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  const sp = doc.getElementById('sidebar-splitter');
  assert.ok(sp, 'sidebar splitter exists');
  assert.equal(sp.classList.contains('splitter'), true);
  assert.equal(sp.getAttribute('data-split-target'), 'sidebar');
});
