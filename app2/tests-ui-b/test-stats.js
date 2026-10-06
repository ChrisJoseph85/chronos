// UI-B: Stats screen — mount is network-free; Load stats fires stubbed
// fetch; canvas falls back to a table under jsdom. Run: node --test test-stats.js
'use strict';

const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { makeDom, teardownDom, flush, jsonResponse, click } = require('./helpers.js');

let importTimeCalls = 0;
global.fetch = () => {
  importTimeCalls += 1;
  throw new Error('must not be called at import');
};

const { mountStats } = require('../renderer-src/screens/stats.js');
const { mountAiRow } = require('../renderer-src/ai-row.js');

describe('stats import', () => {
  it('performs zero fetch calls at import', () => {
    assert.equal(importTimeCalls, 0);
  });
});

describe('stats screen', () => {
  let dom;
  beforeEach(() => {
    dom = makeDom();
  });
  afterEach(() => {
    teardownDom();
  });

  it('nav shows the stats screen with zero fetch calls', () => {
    let calls = 0;
    const host = document.createElement('div');
    document.body.appendChild(host);
    const h = mountStats(host, {
      mountAiRow,
      fetch: async () => { calls += 1; throw new Error('no'); },
    });
    assert.ok(host.querySelector('[data-screen="stats"]'));
    assert.ok(h.loadBtn);
    assert.ok(h.canvas, 'canvas element present');
    assert.equal(calls, 0);
  });

  it('Load stats GETs /api/stats + breakdown and renders summary + table', async () => {
    const seen = [];
    const fetchStub = async (url, opts) => {
      seen.push(url);
      if (url.endsWith('/api/stats')) {
        return jsonResponse({ counts: { nodes: 10 }, streaks: { days: 4 } });
      }
      if (url.includes('/api/stats/breakdown')) {
        return jsonResponse([
          { node_id: 'a', title: 'Alpha', kind: 'task', total_ms: 3600000 },
          { node_id: 'b', title: 'Beta', kind: 'project', total_ms: 1800000 },
        ]);
      }
      throw new Error('unexpected ' + url);
    };
    const host = document.createElement('div');
    document.body.appendChild(host);
    const h = mountStats(host, { mountAiRow, fetch: fetchStub, getKey: () => 'K' });
    h.fromInput.value = '2026-10-01';
    h.toInput.value = '2026-10-06';
    click(h.loadBtn);
    await flush();
    assert.equal(seen.length, 2);
    assert.ok(seen[0].endsWith('/api/stats'));
    assert.ok(seen[1].includes('/api/stats/breakdown?from=2026-10-01'));
    assert.match(h.summary.textContent, /nodes/);
    // jsdom has no 2d context -> table fallback, still showing the data.
    const mode = h.canvas.getAttribute('data-render-mode');
    assert.equal(mode, 'table');
    assert.match(h.tableWrap.textContent, /Alpha/);
    assert.match(h.tableWrap.textContent, /1h 0m/);
  });

  it('Load stats shows a banner when the server is down', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const h = mountStats(host, {
      fetch: async () => {
        throw new Error('down');
      },
    });
    click(h.loadBtn);
    await flush();
    const banner = host.querySelector('[data-part="banner"]');
    assert.equal(banner.hidden, false);
  });
});
