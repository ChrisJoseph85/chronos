// Chronos app2 UI-A — shared jsdom harness (shell + planner + timer tests).
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (_) {
  ({ JSDOM } = require('/tmp/opencode/uia/node_modules/jsdom'));
}

const ROOT = path.join(__dirname, '..');
const BUILT = path.join(ROOT, 'renderer-dist', 'index.html');

function readBuilt() {
  return fs.readFileSync(BUILT, 'utf8');
}

// Recording fetch stub. routes: [[substring, jsonBody], ...].
// Unmatched URLs resolve to []. Rejects when `fail` is set.
function makeStub(routes) {
  const calls = [];
  const fn = async (url, opts) => {
    calls.push({ url: String(url), opts: opts || {} });
    if (fn.fail) throw new Error('network down');
    const u = String(url);
    for (const [match, body] of routes || []) {
      if (u.includes(match)) {
        return { ok: true, status: 200, json: async () => body };
      }
    }
    return { ok: true, status: 200, json: async () => [] };
  };
  fn.calls = calls;
  fn.fail = false;
  return fn;
}

function load(stubFetch, seedStorage) {
  const html = readBuilt();
  const dom = new JSDOM(html, {
    url: 'http://localhost/',
    runScripts: 'dangerously',
    beforeParse(window) {
      window.fetch = stubFetch;
      if (seedStorage) {
        for (const [k, v] of Object.entries(seedStorage)) {
          try { window.localStorage.setItem(k, v); } catch (_) { /* ignore */ }
        }
      }
      // window.chronos (preload bridge) is deliberately NOT defined here.
    },
  });
  return dom;
}

function tick(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms || 20));
}

function visible(doc, id) {
  const sec = doc.getElementById(id);
  return !!sec && sec.hidden === false;
}

module.exports = { JSDOM, ROOT, BUILT, readBuilt, makeStub, load, tick, visible };
