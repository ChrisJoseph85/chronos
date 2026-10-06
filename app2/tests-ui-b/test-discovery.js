// UI-B: discovery — zero calls at import, Android §9 candidate order,
// saved-key-only probe. Run: node --test test-discovery.js
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

// Install a counting fetch BEFORE requiring the module: the module must
// perform zero network calls at import time.
let importTimeCalls = 0;
global.fetch = () => {
  importTimeCalls += 1;
  throw new Error('must not be called at import');
};

const discovery = require('../renderer-src/discovery.js');

describe('discovery import', () => {
  it('performs zero fetch calls at import', () => {
    assert.equal(importTimeCalls, 0);
  });

  it('exports the expected surface', () => {
    assert.equal(discovery.DEFAULT_PORT, 693);
    assert.equal(typeof discovery.subnet24, 'function');
    assert.equal(typeof discovery.candidates, 'function');
    assert.equal(typeof discovery.scan, 'function');
  });
});

describe('subnet24', () => {
  it('rejects null/garbage/loopback like Android', () => {
    assert.equal(discovery.subnet24(null), null);
    assert.equal(discovery.subnet24('not-an-ip'), null);
    assert.equal(discovery.subnet24('127.0.0.1'), null);
    assert.equal(discovery.subnet24('10.0.0.9'), '10.0.0');
  });
});

describe('candidates', () => {
  it('is 127.0.0.1 first, then the /24 minus self', () => {
    const c = discovery.candidates('192.168.7.50');
    assert.equal(c[0], '127.0.0.1');
    assert.ok(c.includes('192.168.7.1'));
    assert.ok(c.includes('192.168.7.254'));
    assert.ok(!c.includes('192.168.7.50'));
    assert.ok(!c.some((h) => h.startsWith('192.168.8.')));
    assert.equal(c.length, 1 + 253);
  });

  it('is localhost-only without a LAN ip', () => {
    assert.deepEqual(discovery.candidates(null), ['127.0.0.1']);
  });
});

describe('scan', () => {
  it('first healthy+authorized host wins and only ever sees the saved key', async () => {
    const order = [];
    const keysSeen = [];
    const fetchFn = async (url, opts) => {
      order.push(url);
      if (url.endsWith('/api/health')) {
        const host = url.replace('http://', '').split(':')[0];
        const healthy = host === '127.0.0.1' || host === '192.168.7.9';
        return { ok: healthy, status: healthy ? 200 : 404, json: async () => ({}) };
      }
      keysSeen.push(opts && opts.headers && opts.headers['X-Chronos-Key']);
      const host = url.replace('http://', '').split(':')[0];
      const authed = host === '192.168.7.9';
      return { ok: authed, status: authed ? 200 : 401, json: async () => ({}) };
    };
    const found = await discovery.scan({
      port: 693,
      localIp: '192.168.7.50',
      savedKey: 'SAVED-KEY',
      fetchFn,
    });
    assert.equal(found, 'http://192.168.7.9:693');
    assert.ok(order[0].includes('127.0.0.1'), 'localhost probed first');
    assert.ok(keysSeen.length > 0);
    assert.ok(keysSeen.every((k) => k === 'SAVED-KEY'));
  });

  it('makes zero calls when the saved key is empty', async () => {
    let calls = 0;
    const fetchFn = async () => {
      calls += 1;
      return { ok: true, status: 200, json: async () => ({}) };
    };
    const found = await discovery.scan({ localIp: '10.0.0.5', savedKey: '', fetchFn });
    assert.equal(found, null);
    assert.equal(calls, 0);
  });

  it('returns null when nothing answers', async () => {
    const fetchFn = async () => {
      throw new Error('down');
    };
    // localhost-only scan keeps this fast.
    const found = await discovery.scan({ savedKey: 'K', fetchFn, localIp: null });
    assert.equal(found, null);
  });

  it('honours cancellation', async () => {
    let calls = 0;
    const fetchFn = async () => {
      calls += 1;
      return { ok: false, status: 404, json: async () => ({}) };
    };
    let n = 0;
    const found = await discovery.scan({
      localIp: '192.168.7.50',
      savedKey: 'K',
      fetchFn,
      isCancelled: () => ++n > 3,
    });
    assert.equal(found, null);
    assert.ok(calls <= 4);
  });
});
