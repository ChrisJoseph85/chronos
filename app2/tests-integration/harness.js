// Chronos app2 — cross-screen integration harness (INTEGRATOR owned).
//
// Boots the FULL built renderer (app2/renderer-dist/index.html) in jsdom
// with runScripts:dangerously, fetch stubbed per-test. Collects jsdomError
// script errors so "every button click is safe" is asserted, not eyeballed.
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM;
let VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require('jsdom'));
} catch (_) {
  try {
    ({ JSDOM, VirtualConsole } = require(path.join(__dirname, '..', 'tests-ui-b', 'node_modules', 'jsdom')));
  } catch (_) {
    ({ JSDOM, VirtualConsole } = require('/tmp/opencode/uia/node_modules/jsdom'));
  }
}

const ROOT = path.join(__dirname, '..');
const BUILT = path.join(ROOT, 'renderer-dist', 'index.html');

function readBuilt() {
  return fs.readFileSync(BUILT, 'utf8');
}

// Throwing stub: SYNCHRONOUS throw (server-down — connection refused).
// Every screen must degrade to banner/disabled state, never crash.
function throwingFetch() {
  const calls = [];
  const fn = (url, opts) => {
    calls.push({ url: String(url), opts: opts || {} });
    throw new Error('connection refused');
  };
  fn.calls = calls;
  return fn;
}

// Fixture stub: async canned responses by URL substring.
function fixtureFetch() {
  const calls = [];
  const routes = [
    ['/api/nodes', [
      { id: 'n1', title: 'Project Alpha', kind: 'project', tags: ['work'] },
      { id: 'n2', title: 'Task One', kind: 'task', parent: 'n1', tags: ['work', 'urgent'] },
    ]],
    ['/api/timer/start', { id: 's1', label: 'deep work', mode: 'stopwatch' }],
    ['/api/timer/stop', { id: 's1', voided: false }],
    ['/api/timer/summary', { node_total_ms: 3600000, descendant_total_ms: 7200000, project_total_ms: 10800000 }],
    ['/api/stats/breakdown', [{ node_id: 'c1', title: 'Child A', kind: 'task', total_ms: 1800000 }]],
    ['/api/timer/presets', [{ name: 'pom', focus_minutes: 25, break_minutes: 5, cycles: 4 }]],
    ['/api/briefing', { date: '2026-10-06', unallocated_tasks: 3, rollover: 1, due_reviews: 2, question: 'Focus?' }],
    ['/api/stats', { counts: { nodes: 7, sessions: 4 }, streaks: { daily: 5 } }],
    ['/api/providers', { stt: [], text: [{ id: 'p1', name: 'Main', base_url: 'http://x', key_ids: ['k1'] }], embeddings: [] }],
    ['/api/health', { status: 'ok', version: '9.9.9-test' }],
    ['/api/say', { message: 'canned answer' }],
    ['/api/voice', { transcript: 'canned transcript' }],
    ['/api/buckets', [{ id: 'b1', title: 'Morning' }]],
  ];
  const fn = (url, opts) => {
    calls.push({ url: String(url), opts: opts || {} });
    const u = String(url);
    for (const [match, body] of routes) {
      if (u.includes(match)) return Promise.resolve({ ok: true, status: 200, json: async () => body });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => [] });
  };
  fn.calls = calls;
  return fn;
}

// Boot the full bundle. Returns { dom, errors, fetch }.
// errors collects jsdom script errors (uncaught exceptions in handlers).
function boot(fetchStub, seedStorage) {
  const html = readBuilt();
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => errors.push(e));
  const dom = new JSDOM(html, {
    url: 'http://localhost/',
    runScripts: 'dangerously',
    virtualConsole: vc,
    beforeParse(window) {
      window.fetch = fetchStub;
      // Deterministic canvas fallback: jsdom without the canvas package
      // emits a jsdomError on getContext('2d'). The app handles a null
      // context by rendering a table — stub it to null so the suite
      // exercises that (correct) path instead of jsdom's error logging.
      try {
        if (window.HTMLCanvasElement && window.HTMLCanvasElement.prototype) {
          window.HTMLCanvasElement.prototype.getContext = function () { return null; };
        }
      } catch (_) { /* ignore */ }
      if (seedStorage) {
        for (const [k, v] of Object.entries(seedStorage)) {
          try { window.localStorage.setItem(k, v); } catch (_) { /* ignore */ }
        }
      }
      // window.chronos (preload bridge) deliberately NOT defined.
    },
  });
  return { dom, errors, fetch: fetchStub };
}

function tick(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms || 25));
}

// Generous flush for the screens' Promise.resolve(p).then chains.
async function flush(turns) {
  for (let i = 0; i < (turns || 15); i++) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  await tick(10);
}

function visible(doc, id) {
  const sec = doc.getElementById(id);
  return !!sec && sec.hidden === false;
}

const SCREENS = [
  ['planner', 'screen-planner'],
  ['timer', 'screen-timer'],
  ['briefing', 'screen-briefing'],
  ['stats', 'screen-stats'],
  ['settings', 'screen-settings'],
];

module.exports = {
  JSDOM, ROOT, BUILT, SCREENS,
  readBuilt, throwingFetch, fixtureFetch, boot, tick, flush, visible,
};
