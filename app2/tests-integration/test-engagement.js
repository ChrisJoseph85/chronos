// Chronos app2 — integration: engagement polish (ENGAGEMENT-POLISH owned).
//
//  - Proactive briefing fires (urgent card + notify) when server URL+key
//    are configured and the briefing flags urgency.
//  - Proactive briefing stays fully silent when unconfigured (zero fetch,
//    zero notify, zero banner spam).
//  - Notify text assertions: Title Case headlines, one-line butler-voiced
//    bodies, capped at 120 chars, never raw JSON/ids (renderer payloads +
//    the central main/notify.js polish that also covers timer paths).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { fixtureFetch, throwingFetch, boot, tick, flush } = require('./harness');
const { formatNotify, NOTIFY_BODY_MAX } = require('../main/notify');

function isTitleCase(title) {
  const words = String(title).split(' ').filter((w) => w.length > 0);
  return words.length > 0 && words.every((w) => /^[A-Z]/.test(w));
}

function urgentBriefingFetch(calls) {
  const fn = (url, opts) => {
    calls.push({ url: String(url), opts: opts || {} });
    if (String(url).includes('/api/briefing')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          date: '2026-10-06',
          unallocated_tasks: 3,
          rollover: 1,
          due_reviews: 2,
          question: 'Focus?',
          urgent: true,
        }),
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
  };
  fn.calls = calls;
  return fn;
}

test('proactive briefing fires when configured and the briefing is urgent', async () => {
  const calls = [];
  const stub = urgentBriefingFetch(calls);
  const { dom, errors } = boot(stub, {
    'chronos.serverUrl': 'http://127.0.0.1:8080',
    'chronos.key': 'K-TEST',
  });
  const notified = [];
  dom.window.chronosNotify = (p) => notified.push(p);
  await tick(50);
  await flush(30);
  const proactive = calls.filter((c) => c.url.includes('/api/briefing?date='));
  assert.ok(proactive.length >= 1, 'proactive GET /api/briefing?date= fired: ' + JSON.stringify(calls.map((c) => c.url)));
  assert.equal(proactive[0].opts.method, 'GET');
  assert.equal(proactive[0].opts.headers['X-Chronos-Key'], 'K-TEST');
  const doc = dom.window.document;
  const card = doc.querySelector('#screen-briefing [data-part="urgent-briefing"]');
  assert.ok(card, 'urgent-briefing card mounted');
  assert.equal(card.hidden, false, 'urgent card surfaced, got: ' + card.textContent);
  assert.match(card.textContent, /Urgent Briefing/);
  assert.equal(errors.length, 0, 'script errors: ' + errors.map(String).join(' | '));
  assert.ok(notified.length >= 1, 'proactive notify fired');
  const n = notified[0];
  assert.ok(isTitleCase(n.title), 'Title Case headline, got: ' + n.title);
  assert.ok(!n.body.includes('\n'), 'one-line body');
  assert.ok(n.body.length <= NOTIFY_BODY_MAX, 'capped body, got ' + n.body.length);
  assert.match(n.body, /sir/i, 'butler voice, got: ' + n.body);
  dom.window.close();
});

test('proactive briefing stays silent when unconfigured', async () => {
  const stub = throwingFetch();
  const { dom, errors } = boot(stub); // no seeded storage: URL+key unconfigured
  const notified = [];
  dom.window.chronosNotify = (p) => notified.push(p);
  await tick(50);
  await flush(30);
  assert.equal(stub.calls.length, 0, 'zero fetch when unconfigured: ' + JSON.stringify(stub.calls));
  assert.equal(notified.length, 0, 'zero notifies when unconfigured');
  const doc = dom.window.document;
  const card = doc.querySelector('#screen-briefing [data-part="urgent-briefing"]');
  assert.ok(card, 'urgent-briefing card mounted');
  assert.equal(card.hidden, true, 'card stays hidden when unconfigured');
  assert.equal(doc.getElementById('global-banner').hidden, true, 'no banner spam');
  assert.equal(errors.length, 0, 'script errors: ' + errors.map(String).join(' | '));
  dom.window.close();
});

test('notify text is polished: Title Case, one-line, capped, never raw JSON', async () => {
  // Central polish (main process) — covers every path including timer.
  const timerish = formatNotify({ title: 'chronos timer', body: 'Timer started (stopwatch).' });
  assert.equal(timerish.title, 'Chronos Timer');
  const long = formatNotify({ title: 'briefing update', body: 'x'.repeat(200) });
  assert.equal(long.title, 'Briefing Update');
  assert.ok(long.body.length <= NOTIFY_BODY_MAX, 'truncated, got ' + long.body.length);
  assert.match(long.body, /…$/);
  const wrapped = formatNotify({ title: 'reminder', body: 'line one\nline two\nline three' });
  assert.ok(!wrapped.body.includes('\n'), 'one-line, got: ' + wrapped.body);
  const dumped = formatNotify({ title: 'proposal', body: '{"proposal_id":"p-9","ops":[]}' });
  assert.ok(!dumped.body.includes('proposal_id'), 'no raw JSON/ids, got: ' + dumped.body);
  assert.ok(!dumped.body.includes('{'), 'no raw JSON, got: ' + dumped.body);

  // Renderer-emitted payloads through the full bundle (unconfigured boot:
  // proactive stays silent, clicks drive everything).
  const stub = fixtureFetch();
  const { dom, errors } = boot(stub);
  const notified = [];
  dom.window.chronosNotify = (p) => notified.push(p);
  await tick();
  const doc = dom.window.document;
  doc.querySelector('[data-screen-nav="briefing"]').click();
  doc.querySelector('[data-action="briefing-date"]').value = '2026-10-06';
  doc.querySelector('[data-action="briefing-load"]').click();
  await flush();
  const bn = notified.find((p) => /Briefing/.test(p.title));
  assert.ok(bn, 'briefing-load notify fired: ' + JSON.stringify(notified));
  assert.ok(isTitleCase(bn.title), 'Title Case headline, got: ' + bn.title);
  assert.ok(!bn.body.includes('\n') && bn.body.length <= NOTIFY_BODY_MAX, 'one-line capped body, got: ' + bn.body);
  assert.match(bn.body, /sir/i, 'butler voice, got: ' + bn.body);
  assert.ok(!bn.body.includes('{"'), 'no raw JSON, got: ' + bn.body);

  doc.querySelector('[data-screen-nav="settings"]').click();
  const toggle = doc.querySelector('[data-action="settings-notif-timer"]');
  assert.ok(toggle, 'timer toggle mounted');
  toggle.click();
  await tick();
  const tn = notified.find((p) => /timer/.test(p.body));
  assert.ok(tn, 'toggle notify carries the category, got: ' + JSON.stringify(notified));
  assert.ok(isTitleCase(tn.title), 'Title Case headline, got: ' + tn.title);
  assert.ok(tn.body.length <= NOTIFY_BODY_MAX, 'capped body');

  doc.querySelector('[data-screen-nav="briefing"]').click();
  doc.querySelector('#screen-briefing [data-action="ai-voice"]').click();
  await flush();
  const vn = notified.find((p) => /Voice/.test(p.title));
  assert.ok(vn, 'voice notify fired: ' + JSON.stringify(notified));
  assert.ok(isTitleCase(vn.title), 'Title Case headline, got: ' + vn.title);
  assert.ok(!vn.body.includes('\n') && vn.body.length <= NOTIFY_BODY_MAX, 'one-line capped body, got: ' + vn.body);

  assert.equal(errors.length, 0, 'script errors: ' + errors.map(String).join(' | '));
  dom.window.close();
});
