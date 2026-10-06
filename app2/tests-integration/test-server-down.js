// Chronos app2 — integration: server-down boot of the FULL renderer.
//
// fetch is stubbed to THROW synchronously (dead server). Asserts:
//  - zero fetch calls at import/boot time (offline first paint)
//  - all 5 screens render (offline empty states)
//  - nav switching works across all 5
//  - AI row present on every screen
//  - EVERY button click is safe: no sync throw, no jsdom script error,
//    global banner and/or health banner surfaces the failure
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { SCREENS, throwingFetch, boot, tick, flush, visible } = require('./harness');

test('server-down boot: zero fetch calls at import/boot time', async () => {
  const stub = throwingFetch();
  const { dom, errors } = boot(stub);
  assert.equal(stub.calls.length, 0, 'fetch called during import/boot: ' + JSON.stringify(stub.calls));
  await tick();
  await flush();
  assert.equal(stub.calls.length, 0, 'fetch called after first paint with no clicks');
  assert.equal(errors.length, 0, 'script errors at boot: ' + errors.map(String).join(' | '));
  const doc = dom.window.document;
  assert.ok(doc.getElementById('sidebar'), 'sidebar present');
  assert.ok(visible(doc, 'screen-planner'), 'planner visible by default');
  assert.equal(doc.getElementById('global-banner').hidden, true, 'no banner before any action');
});

test('server-down boot: all 5 screens render offline states', async () => {
  const { dom, errors } = boot(throwingFetch());
  await tick();
  const doc = dom.window.document;
  for (const [, section] of SCREENS) {
    assert.ok(doc.getElementById(section), `section #${section} exists`);
  }
  // Offline markers from each screen (no network needed for these).
  assert.ok(doc.getElementById('planner-calendar'), 'planner calendar mounted');
  assert.match(doc.getElementById('planner-node-list').textContent, /No nodes loaded yet/);
  assert.ok(doc.getElementById('timer-start'), 'timer start mounted');
  assert.match(doc.getElementById('timer-status').textContent, /Idle/);
  assert.ok(doc.querySelector('[data-action="briefing-load"]'), 'briefing load button mounted');
  assert.ok(doc.querySelector('[data-action="stats-load"]'), 'stats load button mounted');
  assert.ok(doc.querySelector('[data-action="settings-save"]'), 'settings save mounted');
  assert.ok(doc.querySelector('[data-action="settings-health"]'), 'settings health check mounted');
  assert.equal(errors.length, 0);
});

test('server-down boot: nav switching works across all 5 screens', async () => {
  const { dom, errors } = boot(throwingFetch());
  await tick();
  const doc = dom.window.document;
  for (const [nav, section] of SCREENS) {
    const btn = doc.querySelector(`[data-screen-nav="${nav}"]`);
    assert.ok(btn, `nav button for ${nav} exists`);
    btn.click(); // must not throw with dead server
    for (const [, sec] of SCREENS) {
      assert.equal(visible(doc, sec), sec === section, `${nav} click: ${sec} visibility`);
    }
    assert.equal(btn.getAttribute('aria-current'), 'page');
  }
  await flush();
  assert.equal(errors.length, 0, 'script errors during nav: ' + errors.map(String).join(' | '));
});

test('server-down boot: AI row present on every screen', async () => {
  const { dom, errors } = boot(throwingFetch());
  await tick();
  const doc = dom.window.document;
  for (const [, section] of SCREENS) {
    const sec = doc.getElementById(section);
    const row = sec.querySelector('[data-screen-part="ai-row"]');
    assert.ok(row, `AI row mounted in #${section}`);
    assert.ok(row.querySelector('[data-action="ai-voice"]'), `mic button in #${section}`);
    assert.ok(row.querySelector('[data-action="ai-text"]'), `text input in #${section}`);
    assert.ok(row.querySelector('[data-action="ai-send"]'), `send button in #${section}`);
  }
  assert.equal(errors.length, 0);
});

test('server-down boot: health banner element shows + Check health degrades safely', async () => {
  const { dom, errors } = boot(throwingFetch());
  await tick();
  const doc = dom.window.document;
  doc.querySelector('[data-screen-nav="settings"]').click();
  const health = doc.querySelector('[data-part="health"]');
  assert.ok(health, 'health banner element present');
  assert.match(health.textContent, /not checked yet/i, 'untouched state at boot');
  doc.querySelector('[data-action="settings-health"]').click(); // sync-throwing fetch
  assert.match(health.textContent, /down|unavailable/i, 'server-down state shown, got: ' + health.textContent);
  // Settings surfaces failures in its own local banner (not the global one).
  const localBanner = doc.querySelector('#screen-settings [data-part="banner"]');
  assert.ok(localBanner, 'settings local banner present');
  assert.equal(localBanner.hidden, false, 'local banner surfaces the failure');
  assert.match(localBanner.textContent, /Health check failed/);
  await flush();
  assert.equal(errors.length, 0);
});

test('server-down boot: EVERY button click is safe (no uncaught exceptions)', async () => {
  const stub = throwingFetch();
  const { dom, errors } = boot(stub);
  await tick();
  const doc = dom.window.document;
  const buttons = Array.from(doc.querySelectorAll('button'));
  assert.ok(buttons.length >= 20, `expected a button-rich UI, got ${buttons.length}`);
  let clicked = 0;
  for (const btn of buttons) {
    // Make each screen visible at least once so hidden-panel clicks still run handlers.
    try {
      btn.click();
      clicked++;
    } catch (err) {
      assert.fail(`button click threw synchronously (${btn.id || btn.textContent || btn.outerHTML}): ${err && err.stack || err}`);
    }
  }
  await flush(25);
  assert.equal(errors.length, 0, `jsdom script errors after clicking ${clicked} buttons: ` + errors.map((e) => e.stack || String(e)).join('\n---\n'));
  // UI is still alive and navigable after the click storm.
  doc.querySelector('[data-screen-nav="stats"]').click();
  assert.ok(visible(doc, 'screen-stats'));
  doc.querySelector('[data-screen-nav="planner"]').click();
  assert.ok(visible(doc, 'screen-planner'));
  assert.equal(clicked, buttons.length);
});

test('server-down boot: AI row mic + text degrade safely on every screen', async () => {
  const { dom, errors } = boot(throwingFetch());
  await tick();
  const doc = dom.window.document;
  for (const [, section] of SCREENS) {
    const sec = doc.getElementById(section);
    const mic = sec.querySelector('[data-action="ai-voice"]');
    assert.ok(mic, `mic in #${section}`);
    mic.click(); // sync-throwing fetch -> graceful disabled path
    const input = sec.querySelector('[data-action="ai-text"]');
    const form = sec.querySelector('[data-action="ai-form"]');
    assert.ok(input && form, `ai form in #${section}`);
    input.value = 'hello?';
    form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  }
  await flush(25);
  assert.equal(errors.length, 0, 'AI row errors: ' + errors.map(String).join(' | '));
  // Every mic is now gracefully disabled; every row shows a status/banner.
  for (const [, section] of SCREENS) {
    const sec = doc.getElementById(section);
    const mic = sec.querySelector('[data-action="ai-voice"]');
    assert.equal(mic.disabled, true, `mic disabled in #${section}`);
  }
});
