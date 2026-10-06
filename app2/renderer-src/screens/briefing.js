// Chronos app2 — Briefing screen (UI-B owned).
//
// Briefing + question box, plus the shared AI row (mounted when the
// inliner provides it via ctx.mountAiRow or globalThis.ChronosAiRow).
//
// Rules: no network at import or at mount — fetches fire only inside user
// click/submit handlers, each guarded (try/catch -> banner). Storage access
// is guarded (a dead localStorage must never kill clicks).
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosBriefing) or required under node --test.
// Exports: { mountBriefing(container, ctx?) }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosBriefing = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function safeNotify(title, body) {
    try {
      if (typeof window !== 'undefined' && typeof window.chronosNotify === 'function') {
        window.chronosNotify({ title: title, body: body });
        return;
      }
    } catch (_) { /* fall through */ }
    try {
      if (typeof window !== 'undefined' && window.chronos &&
          typeof window.chronos.notify === 'function') {
        window.chronos.notify({ title: title, body: body });
      }
    } catch (_) { /* best-effort */ }
  }

  function storageGet(key, fallback) {
    try {
      if (typeof localStorage === 'undefined') return fallback;
      var v = localStorage.getItem(key);
      return v == null ? fallback : v;
    } catch (_) {
      return fallback;
    }
  }

  function serverUrlOf(ctx) {
    if (ctx && typeof ctx.getServerUrl === 'function') {
      try { return ctx.getServerUrl(); } catch (_) { /* fall through */ }
    }
    return storageGet('chronos.serverUrl', 'http://127.0.0.1:8080');
  }

  function keyOf(ctx) {
    if (ctx && typeof ctx.getKey === 'function') {
      try { return ctx.getKey(); } catch (_) { /* fall through */ }
    }
    return storageGet('chronos.key', '');
  }

  function fetchOf(ctx) {
    if (ctx && typeof ctx.fetch === 'function') return ctx.fetch;
    try {
      if (typeof globalThis !== 'undefined' && typeof globalThis.fetch === 'function') {
        return globalThis.fetch.bind(globalThis);
      }
    } catch (_) { /* ignore */ }
    return null;
  }

  function el(doc, tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function todayISO() {
    try {
      var d = new Date();
      var m = ('0' + (d.getMonth() + 1)).slice(-2);
      var day = ('0' + d.getDate()).slice(-2);
      return d.getFullYear() + '-' + m + '-' + day;
    } catch (_) {
      return '';
    }
  }

  function mountAiRowIfAvailable(container, ctx) {
    var m = null;
    try {
      if (ctx && typeof ctx.mountAiRow === 'function') m = ctx.mountAiRow;
      else if (typeof globalThis !== 'undefined' && globalThis.ChronosAiRow &&
               typeof globalThis.ChronosAiRow.mountAiRow === 'function') {
        m = globalThis.ChronosAiRow.mountAiRow;
      }
    } catch (_) { m = null; }
    if (!m) return null;
    try {
      return m(container, ctx);
    } catch (_) {
      return null;
    }
  }

  // mountBriefing(container, ctx?) -> handles
  // ctx: { getServerUrl?, getKey?, fetch?, mountAiRow?, onAsk? }
  function mountBriefing(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;

    var screen = el(doc, 'section', 'chronos-screen chronos-briefing');
    screen.setAttribute('data-screen', 'briefing');

    screen.appendChild(el(doc, 'h2', 'chronos-screen-title', 'Briefing'));

    var banner = el(doc, 'div', 'chronos-banner');
    banner.setAttribute('data-part', 'banner');
    banner.hidden = true;
    screen.appendChild(banner);

    function showBanner(msg) {
      banner.textContent = msg;
      banner.hidden = false;
    }
    function hideBanner() {
      banner.hidden = true;
      banner.textContent = '';
    }

    // --- briefing loader ---
    var controls = el(doc, 'div', 'chronos-row');
    var dateInput = el(doc, 'input', 'chronos-date');
    dateInput.type = 'date';
    dateInput.setAttribute('data-action', 'briefing-date');
    try { dateInput.value = todayISO(); } catch (_) { /* ignore */ }
    var loadBtn = el(doc, 'button', 'chronos-btn', 'Load briefing');
    loadBtn.type = 'button';
    loadBtn.setAttribute('data-action', 'briefing-load');
    controls.appendChild(dateInput);
    controls.appendChild(loadBtn);
    screen.appendChild(controls);

    var result = el(doc, 'div', 'chronos-briefing-result');
    result.setAttribute('data-part', 'briefing-result');
    result.textContent = 'Pick a date and press “Load briefing”. (No server calls until you do.)';
    screen.appendChild(result);

    function renderBriefing(data) {
      while (result.firstChild) result.removeChild(result.firstChild);
      if (!data || typeof data !== 'object') {
        result.textContent = 'Empty briefing response.';
        return;
      }
      var dl = el(doc, 'dl', 'chronos-briefing-list');
      function addTerm(term, value) {
        var dt = el(doc, 'dt', null, term);
        var dd = el(doc, 'dd');
        dd.textContent = String(value == null ? '—' : (typeof value === 'object' ? JSON.stringify(value) : value));
        dl.appendChild(dt);
        dl.appendChild(dd);
      }
      if (data.date != null) addTerm('Date', data.date);
      if (data.unallocated_tasks != null) addTerm('Unallocated tasks', data.unallocated_tasks);
      if (data.rollover != null) addTerm('Rollover', data.rollover);
      if (data.due_reviews != null) addTerm('Due reviews', data.due_reviews);
      if (data.question != null) addTerm('Question', data.question);
      if (!dl.firstChild) {
        result.textContent = JSON.stringify(data);
      } else {
        result.appendChild(dl);
      }
    }

    loadBtn.addEventListener('click', function () {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot load briefing: no fetch implementation.');
        return;
      }
      var date = '';
      try { date = dateInput.value || todayISO(); } catch (_) { date = todayISO(); }
      var serverUrl = serverUrlOf(ctx);
      var key = keyOf(ctx);
      result.textContent = 'Loading…';
      var p;
      try {
        p = fetchFn(serverUrl + '/api/briefing?date=' + encodeURIComponent(date), {
          method: 'GET',
          headers: { 'X-Chronos-Key': key },
        });
      } catch (err) {
        result.textContent = 'Load failed.';
        showBanner('Briefing load failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(
        function (res) {
          if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
          return typeof res.json === 'function' ? res.json() : {};
        }
      ).then(
        function (data) {
          renderBriefing(data);
          safeNotify('Chronos briefing', 'Briefing loaded for ' + date + '.');
        },
        function (err) {
          result.textContent = 'Load failed.';
          showBanner('Briefing load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // --- question box ---
    var qTitle = el(doc, 'h3', 'chronos-sub-title', 'Ask a question');
    screen.appendChild(qTitle);
    var qForm = el(doc, 'form', 'chronos-row');
    qForm.setAttribute('data-action', 'briefing-question-form');
    var qInput = el(doc, 'input', 'chronos-question-input');
    qInput.type = 'text';
    qInput.placeholder = 'e.g. What needs my attention today?';
    qInput.setAttribute('data-action', 'briefing-question');
    var qBtn = el(doc, 'button', 'chronos-btn', 'Ask');
    qBtn.type = 'submit';
    qBtn.setAttribute('data-action', 'briefing-ask');
    qForm.appendChild(qInput);
    qForm.appendChild(qBtn);
    screen.appendChild(qForm);
    var qAnswer = el(doc, 'div', 'chronos-question-answer');
    qAnswer.setAttribute('data-part', 'question-answer');
    qAnswer.setAttribute('role', 'status');
    screen.appendChild(qAnswer);

    qForm.addEventListener('submit', function (ev) {
      try { ev.preventDefault(); } catch (_) { /* ignore */ }
      hideBanner();
      var text = '';
      try { text = (qInput.value || '').trim(); } catch (_) { text = ''; }
      if (!text) {
        qAnswer.textContent = 'Type a question first.';
        return;
      }
      qAnswer.textContent = 'Asking…';
      var askFn;
      if (typeof ctx.onAsk === 'function') {
        askFn = function () { return ctx.onAsk(text); };
      } else {
        var fetchFn = fetchOf(ctx);
        if (!fetchFn) {
          qAnswer.textContent = 'Unavailable.';
          showBanner('Cannot ask: no fetch implementation.');
          return;
        }
        var serverUrl = serverUrlOf(ctx);
        var key = keyOf(ctx);
        askFn = function () {
          return fetchFn(serverUrl + '/api/say', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Chronos-Key': key },
            body: JSON.stringify({ text: text, device_id: 'chronos-app2' }),
          }).then(function (res) {
            if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
            return typeof res.json === 'function' ? res.json() : {};
          }).then(function (data) {
            return (data && (data.message || data.question)) || 'OK';
          });
        };
      }
      var r;
      try {
        r = askFn();
      } catch (err) {
        qAnswer.textContent = 'Ask failed.';
        showBanner('Ask failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(r).then(
        function (msg) {
          qAnswer.textContent = String(msg == null ? 'OK' : msg);
          safeNotify('Chronos answer', String(msg == null ? 'OK' : msg));
        },
        function (err) {
          qAnswer.textContent = 'Ask failed.';
          showBanner('Ask failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    container.appendChild(screen);

    // Shared AI row at the bottom of the screen (when the inliner provides it).
    var aiRow = mountAiRowIfAvailable(screen, ctx);

    return {
      screen: screen,
      dateInput: dateInput,
      loadBtn: loadBtn,
      result: result,
      qForm: qForm,
      qInput: qInput,
      qBtn: qBtn,
      qAnswer: qAnswer,
      aiRow: aiRow,
    };
  }

  return { mountBriefing: mountBriefing };
});
