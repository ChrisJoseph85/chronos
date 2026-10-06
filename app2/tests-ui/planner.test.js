// Chronos app2 UI-A — planner click-through tests.
// Calendar renders offline; every button triggers its stubbed lazy fetch.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeStub, load, tick } = require('./harness');

const NODES = [
  { id: 'n1', title: 'Project Alpha', kind: 'project', tags: ['work'] },
  { id: 'n2', title: 'Task One', kind: 'task', parent: 'n1', tags: ['work', 'urgent'] },
];

function goPlanner(doc) {
  doc.querySelector('[data-screen-nav="planner"]').click();
}

test('calendar renders offline with zero fetch calls', async () => {
  const stub = makeStub([]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  const days = doc.querySelectorAll('#planner-calendar .cal-day:not(.blank)');
  assert.ok(days.length >= 28 && days.length <= 31, `day cells rendered, got ${days.length}`);
  assert.ok(doc.getElementById('cal-label').textContent.length > 0);
  assert.equal(stub.calls.length, 0);
});

test('calendar prev/next/today switch months with zero fetch', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  const label = () => doc.getElementById('cal-label').textContent;
  const first = label();
  doc.getElementById('cal-next').click();
  assert.notEqual(label(), first);
  doc.getElementById('cal-prev').click();
  assert.equal(label(), first);
  doc.getElementById('cal-next').click();
  doc.getElementById('cal-today').click();
  assert.equal(label(), first);
});

test('day click lazily GETs /api/buckets and shows detail', async () => {
  const stub = makeStub([[ '/api/buckets', [{ id: 'b1', title: 'Morning' }] ]]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goPlanner(doc);
  const day = doc.querySelector('#planner-calendar .cal-day[data-date]');
  assert.ok(day, 'a day button exists');
  day.click();
  await tick();
  assert.ok(stub.calls.some((c) => c.url.includes('/api/buckets?level=D')), 'buckets fetched: ' + JSON.stringify(stub.calls));
  assert.match(doc.getElementById('planner-day-detail').textContent, /bucket\(s\)/);
});

test('Load nodes click GETs /api/nodes and renders tree', async () => {
  const stub = makeStub([[ '/api/nodes', NODES ]]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goPlanner(doc);
  doc.getElementById('planner-load-nodes').click();
  await tick();
  assert.ok(stub.calls.some((c) => c.url.endsWith('/api/nodes')), 'nodes fetched');
  const text = doc.getElementById('planner-node-list').textContent;
  assert.match(text, /Project Alpha/);
  assert.match(text, /Task One/);
});

test('Load tags click derives tags from /api/nodes', async () => {
  const stub = makeStub([[ '/api/nodes', NODES ]]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goPlanner(doc);
  doc.getElementById('planner-load-tags').click();
  await tick();
  assert.ok(stub.calls.some((c) => c.url.endsWith('/api/nodes')), 'nodes fetched for tags');
  const chips = doc.querySelectorAll('#planner-tag-list .tag-chip');
  const names = Array.from(chips).map((c) => c.textContent).sort();
  assert.deepEqual(names, ['urgent', 'work']);
});

test('failed loads show banner and re-enable buttons', async () => {
  const stub = makeStub([]);
  stub.fail = true;
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  goPlanner(doc);
  doc.getElementById('planner-load-nodes').click();
  await tick();
  const banner = doc.getElementById('global-banner');
  assert.equal(banner.hidden, false);
  assert.match(banner.textContent, /Nodes load failed/);
  assert.equal(doc.getElementById('planner-load-nodes').disabled, false);
  doc.getElementById('planner-load-tags').click();
  await tick();
  assert.match(banner.textContent, /Tags load failed/);
});
