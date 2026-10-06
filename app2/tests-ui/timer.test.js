// Chronos app2 UI-A — timer+log click-through tests.
// 3 modes toggle locally; strict persists; each action button hits its
// stubbed lazy endpoint.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeStub, load, tick } = require('./harness');

function goTimer(doc) {
  doc.querySelector('[data-screen-nav="timer"]').click();
}

function runningStub() {
  return makeStub([
    ['/api/timer/start', { id: 's1', label: 'deep work', mode: 'stopwatch' }],
    ['/api/timer/stop', { id: 's1', voided: false }],
    ['/api/timer/summary', { node_total_ms: 3600000, descendant_total_ms: 7200000, project_total_ms: 10800000 }],
    ['/api/stats/breakdown', [{ node_id: 'c1', title: 'Child A', kind: 'task', total_ms: 1800000 }]],
    ['/api/timer/presets', [{ name: 'pom', focus_minutes: 25, break_minutes: 5, cycles: 4 }]],
  ]);
}

test('three mode buttons toggle exclusively with zero fetch', async () => {
  const stub = makeStub([]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  const modes = ['stopwatch', 'pomodoro', 'countdown'];
  for (const m of modes) {
    const btn = doc.getElementById('timer-mode-' + m);
    assert.ok(btn, `mode button ${m} exists`);
    btn.click();
    for (const m2 of modes) {
      assert.equal(
        doc.getElementById('timer-mode-' + m2).getAttribute('aria-pressed'),
        m2 === m ? 'true' : 'false',
        `mode ${m} active`
      );
    }
  }
  assert.equal(stub.calls.length, 0, 'mode switches never fetch');
});

test('strict toggle persists to storage', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  const strict = doc.getElementById('timer-strict');
  assert.equal(strict.checked, false);
  strict.click();
  assert.equal(strict.checked, true);
  assert.equal(dom.window.localStorage.getItem('chronos.timer.strict'), '1');
});

test('strict mode blocks start without label (banner, no fetch)', async () => {
  const stub = makeStub([]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('timer-strict').click();
  doc.getElementById('timer-start').click();
  await tick();
  assert.equal(stub.calls.length, 0);
  assert.match(doc.getElementById('global-banner').textContent, /Strict mode/);
});

test('Start POSTs /api/timer/start with mode + label', async () => {
  const stub = runningStub();
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('timer-mode-pomodoro').click();
  doc.getElementById('timer-label').value = 'deep work';
  doc.getElementById('timer-start').click();
  await tick();
  const call = stub.calls.find((c) => c.url.endsWith('/api/timer/start'));
  assert.ok(call, 'start posted: ' + JSON.stringify(stub.calls));
  assert.equal(call.opts.method, 'POST');
  const body = JSON.parse(call.opts.body);
  assert.equal(body.mode, 'pomodoro');
  assert.equal(body.label, 'deep work');
  assert.match(doc.getElementById('timer-status').textContent, /Running/);
});

test('Stop POSTs /api/timer/stop with source + void flag', async () => {
  const stub = runningStub();
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('timer-void').click();
  doc.getElementById('timer-stop').click();
  await tick();
  const call = stub.calls.find((c) => c.url.endsWith('/api/timer/stop'));
  assert.ok(call, 'stop posted');
  const body = JSON.parse(call.opts.body);
  assert.equal(body.source, 'desktop');
  assert.equal(body.void, true);
  assert.match(doc.getElementById('timer-status').textContent, /Stopped/);
});

test('Load summary GETs /api/timer/summary and renders totals', async () => {
  const stub = runningStub();
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('timer-summary-load').click();
  await tick();
  assert.ok(stub.calls.some((c) => c.url.includes('/api/timer/summary')), 'summary fetched');
  assert.match(doc.getElementById('timer-summary').textContent, /1:00:00/);
});

test('Breakdown drill GETs /api/stats/breakdown and renders rows', async () => {
  const stub = runningStub();
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('breakdown-node').value = 'n1';
  doc.getElementById('breakdown-from').value = '2026-10-01';
  doc.getElementById('breakdown-to').value = '2026-10-06';
  doc.getElementById('breakdown-drill').click();
  await tick();
  assert.ok(stub.calls.some((c) => c.url.includes('/api/stats/breakdown')), 'breakdown fetched');
  const rows = doc.querySelectorAll('#breakdown-result table tbody tr');
  assert.equal(rows.length, 1);
  assert.match(rows[0].textContent, /Child A/);
});

test('Breakdown drill without inputs shows banner, no fetch', async () => {
  const stub = makeStub([]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('breakdown-drill').click();
  await tick();
  assert.equal(stub.calls.length, 0);
  assert.match(doc.getElementById('global-banner').textContent, /needs node id/);
});

test('Load presets GETs list; Add preset POSTs', async () => {
  const stub = runningStub();
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('presets-load').click();
  await tick();
  assert.ok(stub.calls.some((c) => c.url.endsWith('/api/timer/presets') && c.opts.method === 'GET'));
  assert.match(doc.getElementById('presets-list').textContent, /pom/);
  doc.getElementById('preset-name').value = 'sprint';
  doc.getElementById('preset-focus').value = '50';
  doc.getElementById('preset-break').value = '10';
  doc.getElementById('preset-cycles').value = '3';
  doc.getElementById('preset-add').click();
  await tick();
  const post = stub.calls.find((c) => c.url.endsWith('/api/timer/presets') && c.opts.method === 'POST');
  assert.ok(post, 'preset posted');
  assert.equal(JSON.parse(post.opts.body).name, 'sprint');
});

test('failed timer actions show banner and re-enable buttons', async () => {
  const stub = makeStub([]);
  stub.fail = true;
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goTimer(doc);
  doc.getElementById('timer-start').click();
  await tick();
  const banner = doc.getElementById('global-banner');
  assert.equal(banner.hidden, false);
  assert.match(banner.textContent, /Timer start failed/);
  assert.equal(doc.getElementById('timer-start').disabled, false);
});
