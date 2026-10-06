'use strict';

// load-target resolution: renderer file when present, clean fallback page
// when missing (never crash, never throw).

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  resolveLoadTarget,
  defaultRendererIndexPath,
  FALLBACK_HTML,
} = require('../main/main');

describe('defaultRendererIndexPath', () => {
  it('points at app2/renderer-dist/index.html relative to main/', () => {
    const p = defaultRendererIndexPath('/x/app2/main');
    assert.equal(p, path.join('/x/app2/main', '..', 'renderer-dist', 'index.html'));
    assert.ok(p.endsWith(path.join('renderer-dist', 'index.html')));
  });
});

describe('resolveLoadTarget', () => {
  it('returns a file target when the bundle exists', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-rt-'));
    const index = path.join(dir, 'index.html');
    fs.writeFileSync(index, '<html></html>');
    try {
      const t = resolveLoadTarget(index);
      assert.equal(t.type, 'file');
      assert.equal(t.filePath, index);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it('returns a fallback page (never throws) when the bundle is missing', () => {
    const t = resolveLoadTarget(path.join(os.tmpdir(), 'chronos-definitely-missing', 'index.html'));
    assert.equal(t.type, 'fallback-html');
    assert.ok(t.html.includes('Renderer not built'));
    assert.ok(t.html.includes('renderer-dist'));
  });

  it('falls back cleanly when the exists check itself throws', () => {
    const t = resolveLoadTarget('/whatever', () => { throw new Error('fs blew up'); });
    assert.equal(t.type, 'fallback-html');
    assert.ok(typeof t.html === 'string' && t.html.length > 0);
  });

  it('fallback page is self-contained (no external refs, no server calls)', () => {
    assert.ok(!FALLBACK_HTML.match(/src="http|href="http|fetch\(|XMLHttpRequest/), 'no network');
    assert.ok(FALLBACK_HTML.includes('<!doctype html>'));
  });
});
