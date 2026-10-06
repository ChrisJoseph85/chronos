'use strict';

// notify validation: frozen IPC contract chronos-notify{title,body}.

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

const { validateNotify, handleNotifyIpc, MAX_TITLE_LEN, MAX_BODY_LEN } = require('../main/notify');

describe('validateNotify', () => {
  it('accepts a valid {title, body}', () => {
    const r = validateNotify({ title: 'Hi', body: 'World' });
    assert.equal(r.ok, true);
    assert.equal(r.title, 'Hi');
    assert.equal(r.body, 'World');
  });

  it('trims surrounding whitespace', () => {
    const r = validateNotify({ title: '  Hi  ', body: '  World  ' });
    assert.equal(r.ok, true);
    assert.equal(r.title, 'Hi');
    assert.equal(r.body, 'World');
  });

  it('rejects non-object payloads', () => {
    for (const bad of [null, undefined, 42, 'x', ['title'], []]) {
      assert.equal(validateNotify(bad).ok, false, JSON.stringify(bad));
    }
  });

  it('rejects missing/empty title', () => {
    assert.equal(validateNotify({ body: 'b' }).ok, false);
    assert.equal(validateNotify({ title: '', body: 'b' }).ok, false);
    assert.equal(validateNotify({ title: '   ', body: 'b' }).ok, false);
    assert.equal(validateNotify({ title: 42, body: 'b' }).ok, false);
  });

  it('rejects missing/empty body', () => {
    assert.equal(validateNotify({ title: 't' }).ok, false);
    assert.equal(validateNotify({ title: 't', body: '' }).ok, false);
    assert.equal(validateNotify({ title: 't', body: '   ' }).ok, false);
    assert.equal(validateNotify({ title: 't', body: null }).ok, false);
  });

  it('rejects over-long title/body', () => {
    assert.equal(validateNotify({ title: 'x'.repeat(MAX_TITLE_LEN + 1), body: 'b' }).ok, false);
    assert.equal(validateNotify({ title: 't', body: 'x'.repeat(MAX_BODY_LEN + 1) }).ok, false);
  });

  it('accepts boundary lengths', () => {
    const r = validateNotify({ title: 'x'.repeat(MAX_TITLE_LEN), body: 'y'.repeat(MAX_BODY_LEN) });
    assert.equal(r.ok, true);
  });

  it('ignores extra fields', () => {
    const r = validateNotify({ title: 't', body: 'b', evil: 'require("fs")' });
    assert.equal(r.ok, true);
    assert.equal(r.title, 't');
  });
});

describe('handleNotifyIpc', () => {
  it('calls showFn once with trimmed {title, body} on valid payload', () => {
    const calls = [];
    const shown = handleNotifyIpc({ title: ' T ', body: ' B ' }, (o) => calls.push(o));
    assert.equal(shown, true);
    assert.deepEqual(calls, [{ title: 'T', body: 'B' }]);
  });

  it('never calls showFn on invalid payload', () => {
    let called = 0;
    const shown = handleNotifyIpc({ title: '', body: '' }, () => { called += 1; });
    assert.equal(shown, false);
    assert.equal(called, 0);
  });

  it('returns false (never throws) when showFn throws', () => {
    const shown = handleNotifyIpc({ title: 't', body: 'b' }, () => { throw new Error('no display'); });
    assert.equal(shown, false);
  });
});
