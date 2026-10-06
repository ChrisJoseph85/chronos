// Chronos app2 — AI schedule-context feed (PLANNER-REBUILD owned).
//
// Tiny shared module: records recent schedule changes (drag-drop
// reschedules) so the AI row can include them in its context. Pure logic,
// zero network: no fetch, no storage, no DOM at import or call time.
// In-memory ring buffer (capped), timestamped records.
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosAiContext) or required under node --test.
// Exports: { pushScheduleEvent(ev), getRecentEvents(n), clearEvents(),
//            summarizeRecent(n), MAX_EVENTS }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosAiContext = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Cap for the in-memory feed (oldest records drop off).
  var MAX_EVENTS = 100;
  var DEFAULT_N = 10;

  var feed = [];

  function nowMs() {
    try {
      return Date.now();
    } catch (_) {
      return 0;
    }
  }

  // pushScheduleEvent(ev) -> record.
  // ev: { id?, title?, from?, to?, kind? } where from/to are human-readable
  // slot labels (e.g. "2026-10-07 09:00"); missing fields become ''.
  // The record gains `at` (epoch ms) and `type` (default 'reschedule').
  // Pure: never throws, never touches network/DOM/storage.
  function pushScheduleEvent(ev) {
    var src = ev || {};
    var rec = {
      at: typeof src.at === 'number' ? src.at : nowMs(),
      type: src.type != null ? String(src.type) : 'reschedule',
      id: src.id != null ? String(src.id) : '',
      title: src.title != null ? String(src.title) : '',
      from: src.from != null ? String(src.from) : '',
      to: src.to != null ? String(src.to) : '',
    };
    feed.push(rec);
    while (feed.length > MAX_EVENTS) feed.shift();
    return rec;
  }

  // getRecentEvents(n?) -> newest-first array copy (default 10).
  // Non-positive / non-numeric n returns []. Never throws.
  function getRecentEvents(n) {
    var count = (n == null) ? DEFAULT_N : Math.floor(Number(n));
    if (!(count > 0)) return [];
    var out = feed.slice(-count);
    out.reverse();
    return out;
  }

  // clearEvents() -> undefined. Test/privacy helper; pure.
  function clearEvents() {
    feed = [];
  }

  // summarizeRecent(n?) -> one-line human summary of recent schedule
  // changes, '' when the feed is empty. Used by the AI-row context hook.
  function summarizeRecent(n) {
    var recent = getRecentEvents(n);
    if (!recent.length) return '';
    var parts = recent.map(function (r) {
      var what = r.title || r.id || 'event';
      if (r.from && r.to) return what + ' moved ' + r.from + ' -> ' + r.to;
      if (r.to) return what + ' scheduled ' + r.to;
      return what + ' ' + r.type;
    });
    return 'Recent schedule changes: ' + parts.join('; ');
  }

  return {
    MAX_EVENTS: MAX_EVENTS,
    pushScheduleEvent: pushScheduleEvent,
    getRecentEvents: getRecentEvents,
    clearEvents: clearEvents,
    summarizeRecent: summarizeRecent,
  };
});
