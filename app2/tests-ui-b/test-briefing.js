// UI-B: Briefing screen — nav/mount is network-free; load + question box
// buttons fire stubbed fetch. Run: node --test test-briefing.js
'use strict';

const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { makeDom, teardownDom, flush, jsonResponse, click, submitForm } = require('./helpers.js');

let importTimeCalls = 0;
global.fetch = () => {
  importTimeCalls += 1;
  throw new Error('must not be called at import');
};

const { mountBriefing } = require('../renderer-src/screens/briefing.js');
const { mountAiRow } = require('../renderer-src/ai-row.js');

describe('briefing import', () => {
  it('performs zero fetch calls at import', () => {
    assert.equal(importTimeCalls, 0);
  });
});

describe('briefing screen', () => {
  let dom;
  beforeEach(() => {
    dom = makeDom();
  });
  afterEach(() => {
    teardownDom();
  });

  function nav(ctx) {
    // Simulates sidebar nav: a fresh host node + mount = screen visible.
    const host = document.createElement('div');
    host.id = 'screen-host';
    document.body.appendChild(host);
    const h = mountBriefing(host, { mountAiRow, ...(ctx || {}) });
    return { host, h };
  }

  it('nav shows the briefing screen with zero fetch calls', () => {
    let calls = 0;
    const { host, h } = nav({ fetch: async () => { calls += 1; throw new Error('no'); } });
    const screen = host.querySelector('[data-screen="briefing"]');
    assert.ok(screen, 'briefing screen visible after nav');
    assert.ok(h.loadBtn);
    assert.ok(h.qInput && h.qBtn);
    assert.equal(calls, 0);
    // AI row mounted at the bottom of the screen.
    assert.ok(screen.querySelector('[data-screen-part="ai-row"]'));
  });

  it('Load briefing GETs /api/briefing and renders fields', async () => {
    const seen = [];
    const fetchStub = async (url, opts) => {
      seen.push({ url, opts });
      return jsonResponse({
        date: '2026-10-06',
        unallocated_tasks: 3,
        rollover: 1,
        due_reviews: 2,
        question: 'Focus?',
      });
    };
    const { h } = nav({ fetch: fetchStub, getServerUrl: () => 'http://127.0.0.1:8080', getKey: () => 'K' });
    h.dateInput.value = '2026-10-06';
    click(h.loadBtn);
    await flush();
    assert.equal(seen.length, 1);
    assert.ok(seen[0].url.includes('/api/briefing?date=2026-10-06'));
    assert.equal(seen[0].opts.headers['X-Chronos-Key'], 'K');
    assert.match(h.result.textContent, /Unallocated tasks/);
    assert.match(h.result.textContent, /Focus\?/);
  });

  it('Load briefing shows a banner when the server is down', async () => {
    const { host, h } = nav({
      fetch: async () => {
        throw new Error('down');
      },
    });
    click(h.loadBtn);
    await flush();
    const banner = host.querySelector('[data-part="banner"]');
    assert.equal(banner.hidden, false);
    assert.match(h.result.textContent, /failed/i);
  });

  it('question box POSTs and renders the answer', async () => {
    const seen = [];
    const fetchStub = async (url, opts) => {
      seen.push({ url, opts });
      return jsonResponse({ message: 'answer-text' });
    };
    const { h } = nav({ fetch: fetchStub, getKey: () => 'K' });
    h.qInput.value = 'What needs attention?';
    submitForm(h.qForm);
    await flush();
    assert.equal(seen.length, 1);
    assert.ok(seen[0].url.endsWith('/api/say'));
    assert.match(h.qAnswer.textContent, /answer-text/);
  });
});
