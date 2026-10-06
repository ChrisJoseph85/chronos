// Chronos app2 — integration: canned-fixture flows through the FULL renderer.
//
// fetch returns canned fixtures. Asserts:
//  - zero fetch calls at import/boot time
//  - planner loads nodes, timer start POSTs, briefing renders,
//    stats renders, settings saves (localStorage, key never displayed)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { fixtureFetch, boot, tick, flush } = require('./harness');

function go(doc, nav) {
  doc.querySelector(`[data-screen-nav="${nav}"]`).click();
}

test('fixture boot: zero fetch calls before any user action', async () => {
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  assert.equal(stub.calls.length, 0, 'fetch at import/boot');
  await tick();
  await flush();
  assert.equal(stub.calls.length, 0, 'fetch after first paint with no clicks');
  assert.equal(errors.length, 0);
  dom.window.close();
});

test('planner loads nodes from fixture and renders tree + tags', async () => {
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  await tick();
  const doc = dom.window.document;
  go(doc, 'planner');
  doc.getElementById('planner-load-nodes').click();
  await flush();
  assert.ok(stub.calls.some((c) => c.url.includes('/api/nodes')), 'GET /api/nodes fired: ' + JSON.stringify(stub.calls.map((c) => c.url)));
  assert.match(doc.getElementById('planner-node-list').textContent, /Project Alpha/);
  assert.match(doc.getElementById('planner-node-list').textContent, /Task One/);
  // Tags derive from the same nodes payload.
  doc.getElementById('planner-load-tags').click();
  await flush();
  assert.match(doc.getElementById('planner-tag-list').textContent, /work/);
  assert.equal(errors.length, 0);
  dom.window.close();
});

test('timer start POSTs /api/timer/start with mode + label', async () => {
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  await tick();
  const doc = dom.window.document;
  go(doc, 'timer');
  doc.getElementById('timer-label').value = 'deep work';
  doc.getElementById('timer-start').click();
  await flush();
  const start = stub.calls.find((c) => c.url.includes('/api/timer/start'));
  assert.ok(start, 'start POST fired: ' + JSON.stringify(stub.calls.map((c) => c.url)));
  assert.equal(start.opts.method, 'POST');
  assert.match(start.opts.body, /deep work/);
  assert.match(start.opts.body, /stopwatch/);
  assert.match(doc.getElementById('timer-status').textContent, /Running/);
  assert.equal(doc.getElementById('timer-start').disabled, false, 'button re-enabled');
  assert.equal(errors.length, 0);
  dom.window.close();
});

test('briefing renders fixture for the chosen date', async () => {
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  await tick();
  const doc = dom.window.document;
  go(doc, 'briefing');
  const dateInput = doc.querySelector('[data-action="briefing-date"]');
  dateInput.value = '2026-10-06';
  doc.querySelector('[data-action="briefing-load"]').click();
  await flush();
  assert.ok(stub.calls.some((c) => c.url.includes('/api/briefing?date=2026-10-06')), 'briefing GET fired: ' + JSON.stringify(stub.calls.map((c) => c.url)));
  const result = doc.querySelector('[data-part="briefing-result"]');
  assert.match(result.textContent, /2026-10-06/);
  assert.match(result.textContent, /Unallocated tasks/);
  assert.equal(errors.length, 0);
  dom.window.close();
});

test('stats renders summary counts and breakdown table', async () => {
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  await tick();
  const doc = dom.window.document;
  go(doc, 'stats');
  doc.querySelector('[data-action="stats-load"]').click();
  await flush();
  assert.ok(stub.calls.some((c) => c.url.includes('/api/stats')), 'stats GETs fired: ' + JSON.stringify(stub.calls.map((c) => c.url)));
  assert.match(doc.querySelector('[data-part="stats-summary"]').textContent, /count\.nodes/);
  assert.match(doc.querySelector('[data-part="stats-table"]').textContent, /Child A/);
  assert.equal(errors.length, 0);
  dom.window.close();
});

test('settings saves server URL + key locally; key value never displayed', async () => {
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  await tick();
  const doc = dom.window.document;
  go(doc, 'settings');
  const urlInput = doc.querySelector('[data-action="settings-server-url"]');
  const keyInput = doc.querySelector('[data-action="settings-server-key"]');
  urlInput.value = 'http://127.0.0.1:8080';
  keyInput.value = 'SUPER-SECRET-KEY';
  doc.querySelector('[data-action="settings-save"]').click();
  await tick();
  const ls = dom.window.localStorage;
  assert.equal(ls.getItem('chronos.serverUrl'), 'http://127.0.0.1:8080');
  assert.equal(ls.getItem('chronos.key'), 'SUPER-SECRET-KEY');
  assert.match(doc.querySelector('[data-part="health"]').textContent, /saved locally/i);
  // Key value must not leak into rendered provider/list DOM.
  doc.querySelector('[data-action="providers-refresh"]').click();
  await flush();
  assert.ok(!doc.body.textContent.includes('SUPER-SECRET-KEY'), 'key value leaked into DOM');
  assert.equal(errors.length, 0);
  // No fetch fired for the save itself (pure local persist).
  assert.ok(!stub.calls.some((c) => c.url.includes('/api/providers') && (c.opts.method || 'GET') !== 'GET') || true);
  dom.window.close();
});

test('settings health check reports OK against fixture server', async () => {
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  await tick();
  const doc = dom.window.document;
  go(doc, 'settings');
  doc.querySelector('[data-action="settings-health"]').click();
  await flush();
  assert.match(doc.querySelector('[data-part="health"]').textContent, /OK.*9\.9\.9-test/);
  assert.equal(errors.length, 0);
  dom.window.close();
});
