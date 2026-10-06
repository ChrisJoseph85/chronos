// UI-B: AI row — mount is network-free; mic/text buttons fire stubbed
// fetch; server-down disables gracefully. Run: node --test test-ai-row.js
'use strict';

const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { makeDom, teardownDom, flush, jsonResponse, click, submitForm } = require('./helpers.js');

// Counting fetch installed BEFORE require: mount + import must not call it.
let importTimeCalls = 0;
global.fetch = () => {
  importTimeCalls += 1;
  throw new Error('must not be called at import');
};

const { mountAiRow } = require('../renderer-src/ai-row.js');

describe('ai-row import', () => {
  it('performs zero fetch calls at import', () => {
    assert.equal(importTimeCalls, 0);
  });
});

describe('ai-row clicks', () => {
  let dom;
  beforeEach(() => {
    dom = makeDom();
  });
  afterEach(() => {
    teardownDom();
  });

  it('mount performs zero fetch calls', () => {
    let calls = 0;
    const box = document.createElement('div');
    document.body.appendChild(box);
    mountAiRow(box, { fetch: async () => { calls += 1; throw new Error('no'); } });
    assert.ok(box.querySelector('[data-action="ai-voice"]'));
    assert.ok(box.querySelector('[data-action="ai-text"]'));
    assert.equal(calls, 0);
  });

  it('mic button POSTs /api/voice via stubbed fetch', async () => {
    const seen = [];
    const fetchStub = async (url, opts) => {
      seen.push({ url, opts });
      return jsonResponse({ transcript: 'hello world' });
    };
    const notified = [];
    global.window.chronosNotify = (p) => notified.push(p);
    const box = document.createElement('div');
    document.body.appendChild(box);
    const h = mountAiRow(box, {
      fetch: fetchStub,
      getServerUrl: () => 'http://127.0.0.1:8080',
      getKey: () => 'K',
    });
    click(h.micBtn);
    await flush();
    assert.equal(seen.length, 1);
    assert.ok(seen[0].url.endsWith('/api/voice'));
    assert.equal(seen[0].opts.method, 'POST');
    assert.match(h.statusEl.textContent, /hello world/);
    assert.equal(notified.length, 1);
    assert.equal(h.micBtn.disabled, false);
  });

  it('mic button disables gracefully when the server is down', async () => {
    const fetchStub = async () => {
      throw new Error('connection refused');
    };
    const box = document.createElement('div');
    document.body.appendChild(box);
    const h = mountAiRow(box, { fetch: fetchStub });
    click(h.micBtn); // must not throw
    await flush();
    assert.equal(h.micBtn.disabled, true);
    assert.match(h.statusEl.textContent, /unavailable/i);
    const banner = box.querySelector('[data-part="ai-banner"]');
    assert.equal(banner.hidden, false);
  });

  it('text input POSTs contextually via stubbed fetch', async () => {
    const seen = [];
    const fetchStub = async (url, opts) => {
      seen.push({ url, opts });
      return jsonResponse({ message: 'done-thing' });
    };
    const box = document.createElement('div');
    document.body.appendChild(box);
    const h = mountAiRow(box, { fetch: fetchStub, getKey: () => 'K' });
    h.input.value = 'log 30m on chronos';
    submitForm(h.form);
    await flush();
    assert.equal(seen.length, 1);
    assert.ok(seen[0].url.endsWith('/api/say'));
    const body = JSON.parse(seen[0].opts.body);
    assert.equal(body.text, 'log 30m on chronos');
    assert.match(h.statusEl.textContent, /done-thing/);
  });

  it('text input uses ctx.onAsk when provided', async () => {
    let asked = null;
    const box = document.createElement('div');
    document.body.appendChild(box);
    const h = mountAiRow(box, {
      onAsk: async (t) => {
        asked = t;
        return 'context-answer';
      },
    });
    h.input.value = 'ctx q';
    submitForm(h.form);
    await flush();
    assert.equal(asked, 'ctx q');
    assert.match(h.statusEl.textContent, /context-answer/);
  });

  it('works with no preload notify and no storage (no crash)', async () => {
    const box = document.createElement('div');
    document.body.appendChild(box);
    const h = mountAiRow(box, {
      fetch: async () => jsonResponse({ message: 'ok' }),
    });
    h.input.value = 'hi';
    submitForm(h.form);
    await flush();
    assert.match(h.statusEl.textContent, /ok/);
  });
});
