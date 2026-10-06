// UI-B: Settings screen — mount is network-free; save/health/providers/
// autostart/notif toggles all click-tested with stubbed fetch + IPC.
// Key VALUES are never rendered. Run: node --test test-settings.js
'use strict';

const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const { makeDom, teardownDom, flush, jsonResponse, click, submitForm } = require('./helpers.js');

let importTimeCalls = 0;
global.fetch = () => {
  importTimeCalls += 1;
  throw new Error('must not be called at import');
};

const { mountSettings } = require('../renderer-src/screens/settings.js');
const { mountAiRow } = require('../renderer-src/ai-row.js');

describe('settings import', () => {
  it('performs zero fetch calls at import', () => {
    assert.equal(importTimeCalls, 0);
  });
});

describe('settings screen', () => {
  let dom;
  beforeEach(() => {
    dom = makeDom();
    delete global.window.chronosNotify;
    delete global.window.chronosAutostart;
    if (global.window.chronos) delete global.window.chronos;
  });
  afterEach(() => {
    teardownDom();
  });

  function nav(ctx) {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const h = mountSettings(host, { mountAiRow, ...(ctx || {}) });
    return { host, h };
  }

  it('nav shows the settings screen with zero fetch calls', () => {
    let calls = 0;
    const { host, h } = nav({ fetch: async () => { calls += 1; throw new Error('no'); } });
    assert.ok(host.querySelector('[data-screen="settings"]'));
    assert.ok(h.saveBtn && h.healthBtn && h.provRefresh && h.addForm);
    assert.ok(h.autoToggle);
    assert.ok(h.notifToggles.reminders && h.notifToggles.timer && h.notifToggles.briefing);
    assert.equal(calls, 0);
  });

  it('Save persists server URL + key to localStorage', () => {
    const { h } = nav({});
    h.urlInput.value = 'http://192.168.1.9:8080';
    h.keyInput.value = 'SECRET-K';
    click(h.saveBtn);
    assert.equal(global.localStorage.getItem('chronos.serverUrl'), 'http://192.168.1.9:8080');
    assert.equal(global.localStorage.getItem('chronos.key'), 'SECRET-K');
  });

  it('Check health renders the health banner from stubbed fetch', async () => {
    const seen = [];
    const { h } = nav({
      getServerUrl: () => 'http://127.0.0.1:8080',
      fetch: async (url, opts) => {
        seen.push(url);
        return jsonResponse({ status: 'ok', version: '9.9.9' });
      },
    });
    click(h.healthBtn);
    await flush();
    assert.equal(seen.length, 1);
    assert.ok(seen[0].endsWith('/api/health'));
    assert.match(h.healthBanner.textContent, /OK.*9\.9\.9/);
  });

  it('Check health shows server-down in the banner without crashing', async () => {
    const { host, h } = nav({
      fetch: async () => {
        throw new Error('refused');
      },
    });
    click(h.healthBtn);
    await flush();
    assert.match(h.healthBanner.textContent, /down/i);
    assert.equal(host.querySelector('[data-part="banner"]').hidden, false);
  });

  it('Refresh providers lists entries with key ids only (never values)', async () => {
    const { h } = nav({
      getKey: () => 'K',
      fetch: async (url) => {
        assert.ok(url.endsWith('/api/providers'));
        return jsonResponse({
          stt: [],
          text: [
            {
              id: 'p1',
              name: 'Main',
              base_url: 'http://x/v1',
              key_ids: ['k1', 'k2'],
              key_count: 2,
            },
          ],
          embeddings: [],
        });
      },
    });
    click(h.provRefresh);
    await flush();
    assert.match(h.provList.textContent, /Main/);
    assert.match(h.provList.textContent, /k1, k2/);
    assert.ok(!h.provList.textContent.includes('sk-secret'));
    // Delete-key buttons exist per key id.
    assert.ok(h.provList.querySelector('[data-action="provider-key-delete"]'));
  });

  it('Add provider POSTs name/base_url and refreshes', async () => {
    const seen = [];
    let refreshed = false;
    const { h } = nav({
      getKey: () => 'K',
      fetch: async (url, opts) => {
        seen.push({ url, opts });
        if (url.endsWith('/api/providers') && opts.method === 'GET') {
          refreshed = true;
          return jsonResponse({ stt: [], text: [], embeddings: [] });
        }
        return jsonResponse({ id: 'p9' });
      },
    });
    h.nameInput.value = 'Second';
    h.urlInputP.value = 'http://y/v1';
    submitForm(h.addForm);
    await flush();
    const post = seen.find((s) => s.opts.method === 'POST');
    assert.ok(post);
    const body = JSON.parse(post.opts.body);
    assert.equal(body.name, 'Second');
    assert.equal(body.base_url, 'http://y/v1');
    assert.ok(refreshed, 'list refreshed after add');
  });

  it('Add key POSTs the value once, clears the input, never displays it', async () => {
    const seen = [];
    const providers = {
      stt: [],
      text: [{ id: 'p1', name: 'Main', base_url: 'http://x', key_ids: ['k1'], key_count: 1 }],
      embeddings: [],
    };
    const { h } = nav({
      getKey: () => 'K',
      fetch: async (url, opts) => {
        seen.push({ url, opts });
        if (url.endsWith('/providers/p1/keys') && opts.method === 'POST') {
          return jsonResponse({ key_id: 'k2' });
        }
        return jsonResponse(providers);
      },
    });
    click(h.provRefresh);
    await flush();
    const kInput = h.provList.querySelector('[data-action="provider-key-value"]');
    assert.ok(kInput, 'key input rendered');
    kInput.value = 'sk-super-secret';
    const kForm = h.provList.querySelector('[data-action="provider-key-form"]');
    submitForm(kForm);
    await flush();
    const posts = seen.filter((s) => s.opts.method === 'POST');
    assert.equal(posts.length, 1);
    assert.equal(JSON.parse(posts[0].opts.body).key, 'sk-super-secret');
    assert.ok(!h.provList.textContent.includes('sk-super-secret'), 'value never displayed');
  });

  it('autostart toggle calls guarded IPC at click-time when exposed', () => {
    const ipcSeen = [];
    global.window.chronosAutostart = { set: (v) => { ipcSeen.push(v); return Promise.resolve(true); } };
    const { h } = nav({});
    assert.equal(ipcSeen.length, 0, 'no IPC at mount');
    assert.equal(h.autoToggle.checked, false);
    click(h.autoToggle); // jsdom toggles checked on click
    assert.equal(h.autoToggle.checked, true);
    assert.deepEqual(ipcSeen, [true]);
    assert.match(h.autoStatus.textContent, /via app/);
  });

  it('autostart toggle degrades gracefully with no IPC exposed', () => {
    const { h } = nav({});
    assert.equal(h.autoToggle.checked, false);
    click(h.autoToggle); // jsdom toggles checked on click -> true
    assert.equal(h.autoToggle.checked, true);
    assert.match(h.autoStatus.textContent, /saved locally/);
    assert.equal(global.localStorage.getItem('chronos.autostart'), 'on');
  });

  it('per-category notification toggles persist locally', () => {
    const notified = [];
    global.window.chronosNotify = (p) => notified.push(p);
    const { h } = nav({});
    const t = h.notifToggles.timer;
    const before = t.checked;
    click(t);
    assert.equal(t.checked, !before);
    assert.equal(global.localStorage.getItem('chronos.notify.timer'), t.checked ? 'on' : 'off');
    assert.equal(notified.length, 1);
    assert.match(notified[0].body, /timer/);
  });
});
