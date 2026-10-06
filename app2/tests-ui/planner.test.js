// Chronos app2 PLANNER-REBUILD — week-grid planner click-through tests.
// Week grid renders offline; expand/collapse, month/year nav, and HTML5
// drag-drop reschedule (POST /api/commands update_event + ai-context feed)
// are all exercised with stubbed fetch. Run: node --test app2/tests-ui/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { makeStub, load, tick } = require('./harness');

const Planner = require('../renderer-src/screens/planner.js');
const AiContext = require('../renderer-src/ai-context.js');

const NODES = [
  { id: 'n1', title: 'Project Alpha', kind: 'project', tags: ['work'] },
  { id: 'n2', title: 'Task One', kind: 'task', parent: 'n1', tags: ['work', 'urgent'] },
];

function heads(doc) {
  return Array.from(doc.querySelectorAll('#planner-calendar .day-head'));
}

function slots(doc) {
  return Array.from(doc.querySelectorAll('#planner-calendar .slot'));
}

function slotMs(dateISO, hour) {
  const p = String(dateISO).split('-');
  return new Date(+p[0], (+p[1]) - 1, +p[2], hour, 0, 0, 0).getTime();
}

function dragTo(doc, win, srcEl, slotEl) {
  assert.ok(srcEl, 'drag source exists');
  assert.ok(slotEl, 'drop slot exists');
  srcEl.dispatchEvent(new win.Event('dragstart', { bubbles: true }));
  slotEl.dispatchEvent(new win.Event('drop', { bubbles: true }));
}

// ---- module contract: constants + pure ai-context feed ----

test('planner exports hour-range constants + reschedule route', () => {
  assert.equal(Planner.HOUR_START, 6);
  assert.equal(Planner.HOUR_END, 22);
  assert.equal(Planner.RESCHEDULE_ROUTE, '/api/commands');
  assert.equal(Planner.RESCHEDULE_TOOL, 'update_event');
});

test('ai-context feed is pure logic: push/get/clear/summarize', () => {
  AiContext.clearEvents();
  assert.deepEqual(AiContext.getRecentEvents(5), []);
  assert.equal(AiContext.summarizeRecent(5), '');
  const rec = AiContext.pushScheduleEvent({ id: 'b1', title: 'Write report', from: 'unscheduled', to: '2026-10-07 09:00' });
  assert.equal(rec.type, 'reschedule');
  assert.ok(typeof rec.at === 'number');
  AiContext.pushScheduleEvent({ id: 'e2', title: 'Standup', from: '2026-10-07 08:00', to: '2026-10-08 10:00' });
  const recent = AiContext.getRecentEvents(5);
  assert.equal(recent.length, 2);
  assert.equal(recent[0].id, 'e2', 'newest first');
  assert.match(AiContext.summarizeRecent(5), /Standup moved/);
  AiContext.clearEvents();
  assert.deepEqual(AiContext.getRecentEvents(), []);
});

test('ai-context feed caps at MAX_EVENTS and never touches network', () => {
  AiContext.clearEvents();
  for (let i = 0; i < AiContext.MAX_EVENTS + 5; i++) {
    AiContext.pushScheduleEvent({ id: 'x' + i, to: '2026-10-07 09:00' });
  }
  assert.equal(AiContext.getRecentEvents(AiContext.MAX_EVENTS + 50).length, AiContext.MAX_EVENTS);
  assert.deepEqual(AiContext.getRecentEvents(0), []);
  AiContext.clearEvents();
  const src = fs.readFileSync(path.join(__dirname, '..', 'renderer-src', 'ai-context.js'), 'utf8');
  assert.equal(/fetch\s*\(/.test(src), false, 'ai-context must contain no fetch calls');
});

// ---- week grid offline boot ----

test('boot performs zero fetch; week renders 7 columns + hour rows', async () => {
  const stub = makeStub([]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  assert.equal(stub.calls.length, 0, 'no fetch at boot: ' + JSON.stringify(stub.calls));
  assert.equal(heads(doc).length, 7, 'seven day columns');
  const hours = Planner.HOUR_END - Planner.HOUR_START;
  assert.equal(slots(doc).length, 7 * hours, `7x${hours} hour slots`);
  const first = slots(doc)[0];
  assert.equal(first.getAttribute('data-hour'), String(Planner.HOUR_START));
  assert.match(doc.getElementById('planner-week-label').textContent, /Week of/);
  assert.match(doc.getElementById('planner-calendar').textContent, /No events this week/);
});

test('buckets strip and day grid are independent scroll regions; sidebar docked right', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  const strip = doc.getElementById('planner-buckets');
  const grid = doc.getElementById('planner-week-scroll');
  assert.ok(strip, 'buckets strip exists');
  assert.ok(grid, 'week grid scroll container exists');
  assert.notEqual(strip, grid);
  assert.equal(strip.style.overflowX, 'auto', 'strip scrolls on its own');
  assert.equal(grid.style.overflow, 'auto', 'grid scrolls on its own');
  const side = doc.getElementById('planner-side');
  assert.ok(side, 'weekly-buckets sidebar exists');
  const body = side.parentElement;
  const kids = Array.from(body.children).map((n) => n.id);
  assert.ok(kids.indexOf('planner-calendar') < kids.indexOf('planner-side'), 'sidebar docked right of calendar: ' + kids.join(','));
  assert.ok(doc.getElementById('planner-side-buckets'), 'sidebar bucket list exists');
});

// ---- expand / collapse ----

test('click day header expands focus (day + adjacent + agenda); X returns to week', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  const head = heads(doc)[2];
  const date = head.getAttribute('data-date');
  head.click();
  await tick();
  assert.equal(doc.getElementById('planner-calendar').getAttribute('data-view'), 'expanded');
  assert.ok(doc.getElementById('planner-expanded'), 'expanded focus visible');
  assert.ok(doc.querySelector(`.expanded-day[data-date="${date}"]`), 'focused day shown large');
  assert.ok(doc.getElementById('planner-agenda-' + date), 'agenda for focused day');
  doc.getElementById('planner-collapse-day').click();
  await tick();
  assert.equal(doc.getElementById('planner-calendar').getAttribute('data-view'), 'week');
  assert.equal(heads(doc).length, 7, 'back to 7 columns');
});

// ---- month + year navigation ----

test('month view nav works; clicking a day jumps to focused week', async () => {
  const stub = makeStub([['/api/buckets', [{ id: 'b1', title: 'Morning' }]]]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  doc.getElementById('planner-month-view').click();
  await tick();
  const label = () => doc.getElementById('cal-label').textContent;
  const days = doc.querySelectorAll('#planner-calendar .cal-day[data-date]');
  assert.ok(days.length >= 28 && days.length <= 31, 'compact month grid');
  const first = label();
  doc.getElementById('cal-next').click();
  await tick();
  assert.notEqual(label(), first, 'next month navigates');
  doc.getElementById('cal-prev').click();
  await tick();
  assert.equal(label(), first, 'prev month returns');
  const callsBefore = stub.calls.length;
  const day = doc.querySelector('#planner-calendar .cal-day[data-date]');
  const date = day.getAttribute('data-date');
  day.click();
  await tick();
  assert.equal(doc.getElementById('planner-calendar').getAttribute('data-view'), 'expanded', 'day jumps to focused week');
  assert.ok(doc.querySelector(`.expanded-day[data-date="${date}"]`), 'jumped day is focused');
  assert.equal(stub.calls.length, callsBefore, 'month/day nav never fetches');
});

test('year overview shows 12 months; month button opens month view', async () => {
  const dom = load(makeStub([]));
  await tick();
  const doc = dom.window.document;
  doc.getElementById('planner-year-view').click();
  await tick();
  assert.equal(doc.getElementById('planner-calendar').getAttribute('data-view'), 'year');
  const months = doc.querySelectorAll('#planner-year-grid .year-month-btn');
  assert.equal(months.length, 12, 'twelve month buttons');
  months[0].click();
  await tick();
  assert.equal(doc.getElementById('planner-calendar').getAttribute('data-view'), 'month');
  assert.ok(doc.getElementById('cal-label'), 'month grid shown');
});

// ---- drag-drop reschedule ----

test('drag bucket onto slot POSTs update_event + pushes context event', async () => {
  const stub = makeStub([
    ['/api/buckets', [{ id: 'b1', title: 'Write report' }]],
    ['/api/commands', { tool: 'update_event', result: { id: 'b1', updated: true } }],
  ]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  const win = dom.window;
  doc.getElementById('planner-load-buckets').click();
  await tick();
  const bucket = doc.querySelector('#planner-buckets .bucket[data-id="b1"]');
  assert.ok(bucket, 'bucket rendered in strip');
  assert.ok(doc.querySelector('#planner-side-buckets .bucket[data-id="b1"]'), 'bucket mirrored in right sidebar');
  const dates = heads(doc).map((h) => h.getAttribute('data-date'));
  const slotEl = doc.querySelector(`.slot[data-date="${dates[2]}"][data-hour="9"]`);
  dragTo(doc, win, bucket, slotEl);
  await tick();
  await tick();
  const call = stub.calls.find((c) => c.url.endsWith('/api/commands'));
  assert.ok(call, 'reschedule posted: ' + JSON.stringify(stub.calls));
  assert.equal(call.opts.method, 'POST');
  const body = JSON.parse(call.opts.body);
  assert.equal(body.tool, 'update_event');
  assert.equal(body.arguments.id, 'b1');
  assert.equal(body.arguments.start_ms, slotMs(dates[2], 9));
  assert.equal(body.arguments.end_ms, slotMs(dates[2], 9) + 3600000);
  const placed = doc.querySelector(`.slot[data-date="${dates[2]}"][data-hour="9"] .event-block[data-id="b1"]`);
  assert.ok(placed, 'optimistic event block in target slot');
  const feed = win.ChronosAiContext.getRecentEvents(5);
  assert.equal(feed.length, 1, 'one schedule event recorded');
  assert.equal(feed[0].id, 'b1');
  assert.equal(feed[0].from, 'unscheduled');
  assert.equal(feed[0].to, dates[2] + ' 09:00');
  assert.match(doc.getElementById('planner-day-detail').textContent, /Moved Write report/);
});

test('drag existing event to another slot reschedules from->to', async () => {
  const dom0 = load(makeStub([]));
  await tick();
  const d0 = dom0.window.document;
  const dates = heads(d0).map((h) => h.getAttribute('data-date'));
  const startMs = slotMs(dates[0], 8);
  const stub = makeStub([
    ['/api/events', [{ id: 'e1', title: 'Standup', start_ms: startMs, end_ms: startMs + 3600000 }]],
    ['/api/commands', { tool: 'update_event', result: { id: 'e1', updated: true } }],
  ]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  const win = dom.window;
  doc.getElementById('planner-load-week').click();
  await tick();
  const fromSlot = doc.querySelector(`.slot[data-date="${dates[0]}"][data-hour="8"]`);
  assert.ok(fromSlot.querySelector('.event-block[data-id="e1"]'), 'event block rendered');
  const toSlot = doc.querySelector(`.slot[data-date="${dates[1]}"][data-hour="10"]`);
  dragTo(doc, win, fromSlot.querySelector('.event-block[data-id="e1"]'), toSlot);
  await tick();
  await tick();
  const call = stub.calls.find((c) => c.url.endsWith('/api/commands'));
  assert.ok(call, 'reschedule posted');
  const body = JSON.parse(call.opts.body);
  assert.equal(body.tool, 'update_event');
  assert.equal(body.arguments.start_ms, slotMs(dates[1], 10));
  const fromSel = `.slot[data-date="${dates[0]}"][data-hour="8"]`;
  const toSel = `.slot[data-date="${dates[1]}"][data-hour="10"]`;
  assert.ok(!doc.querySelector(fromSel + ' .event-block[data-id="e1"]'), 'moved out of old slot');
  assert.ok(doc.querySelector(toSel + ' .event-block[data-id="e1"]'), 'present in new slot');
  const feed = win.ChronosAiContext.getRecentEvents(5);
  assert.equal(feed[0].from, dates[0] + ' 08:00');
  assert.equal(feed[0].to, dates[1] + ' 10:00');
});

test('server-down drag shows banner + rolls back', async () => {
  const stub = makeStub([[ '/api/buckets', [{ id: 'b1', title: 'Write report' }] ]]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  const win = dom.window;
  doc.getElementById('planner-load-buckets').click();
  await tick();
  assert.ok(doc.querySelector('#planner-buckets .bucket[data-id="b1"]'), 'bucket loaded while server up');
  stub.fail = true; // server dies before the drop commits
  const dates = heads(doc).map((h) => h.getAttribute('data-date'));
  const slotEl = doc.querySelector(`.slot[data-date="${dates[3]}"][data-hour="11"]`);
  dragTo(doc, win, doc.querySelector('#planner-buckets .bucket[data-id="b1"]'), slotEl);
  await tick();
  await tick();
  const banner = doc.getElementById('global-banner');
  assert.equal(banner.hidden, false, 'banner shown');
  assert.match(banner.textContent, /Reschedule failed/);
  assert.ok(doc.querySelector('#planner-buckets .bucket[data-id="b1"]'), 'bucket rolled back to strip');
  const freshSlot = doc.querySelector(`.slot[data-date="${dates[3]}"][data-hour="11"]`);
  assert.equal(freshSlot.querySelector('.event-block[data-id="b1"]'), null, 'no orphan block in slot');
  assert.equal(win.ChronosAiContext.getRecentEvents(5).length, 0, 'failed move records nothing');
});

// ---- preserved nodes/tags contract ----

test('Load nodes GETs /api/nodes and renders tree; failure shows banner', async () => {
  const stub = makeStub([['/api/nodes', NODES]]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  doc.getElementById('planner-load-nodes').click();
  await tick();
  assert.ok(stub.calls.some((c) => c.url.endsWith('/api/nodes')), 'nodes fetched lazily');
  assert.match(doc.getElementById('planner-node-list').textContent, /Project Alpha/);
});

test('Load tags derives chips from /api/nodes', async () => {
  const stub = makeStub([['/api/nodes', NODES]]);
  const dom = load(stub);
  await tick();
  const doc = dom.window.document;
  doc.getElementById('planner-load-tags').click();
  await tick();
  const chips = Array.from(doc.querySelectorAll('#planner-tag-list .tag-chip')).map((c) => c.textContent).sort();
  assert.deepEqual(chips, ['urgent', 'work']);
});
