// Chronos app2 — AI row shared component (UI-B owned).
//
// Mounted at the bottom of every screen: mic button -> POST /api/voice
// (multipart audio, lazy + guarded, disabled gracefully when the server is
// down) and a text input -> contextual POST (ctx.onAsk, default /api/say).
//
// Rules: no network at import or at mount — fetches fire only inside user
// click/submit handlers, each wrapped in try/catch -> inline status + banner.
// Notification calls are defensive: window.chronosNotify?.() first, then the
// frozen-contract window.chronos.notify(), all guarded so a missing preload
// (or jsdom) never breaks clicks.
//
// UMD-lite: concatenated into the renderer bundle (globalThis.ChronosAiRow)
// or required under node --test.
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosAiRow = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function safeNotify(title, body) {
    var polishedTitle = title;
    var polishedBody = body;
    try {
      polishedTitle = notifyTitle(title);
      polishedBody = notifyText(body);
    } catch (_) { /* fall back to raw text */ }
    try {
      if (typeof window !== 'undefined' && typeof window.chronosNotify === 'function') {
        window.chronosNotify({ title: polishedTitle, body: polishedBody });
        return;
      }
    } catch (_) { /* fall through to contract shape */ }
    try {
      if (typeof window !== 'undefined' && window.chronos &&
          typeof window.chronos.notify === 'function') {
        window.chronos.notify({ title: polishedTitle, body: polishedBody });
      }
    } catch (_) { /* notifications are best-effort */ }
  }

  // ENGAGEMENT-POLISH: notification copy helpers (TEXT ONLY — no styling).
  // Crisp Title Case headlines + one-line Iron-Man-butler-voiced bodies,
  // capped at 120 chars, never raw JSON/ids. All total (never throw).
  var NOTIFY_TEXT_MAX = 120;

  function notifyTitle(s) {
    try {
      return String(s == null ? '' : s).split(/\s+/).filter(function (w) {
        return w.length > 0;
      }).map(function (w) {
        return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
      }).join(' ');
    } catch (_) {
      return '';
    }
  }

  function notifyText(s) {
    var t = '';
    try {
      t = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    } catch (_) {
      return '';
    }
    if (!t) return t;
    if (/^[{[]/.test(t)) {
      try {
        JSON.parse(t);
        return 'The details are ready in the app, sir.';
      } catch (_) { /* not JSON — fall through */ }
    }
    if (t.length > NOTIFY_TEXT_MAX) return t.slice(0, NOTIFY_TEXT_MAX - 1) + '…';
    return t;
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

  // Default contextual POST: /api/say {text, device_id}. Returns the
  // server message (or null on failure — caller renders status).
  function defaultAsk(fetchFn, serverUrl, key, text) {
    var body = JSON.stringify({ text: text, device_id: 'chronos-app2' });
    return fetchFn(serverUrl + '/api/say', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Chronos-Key': key },
      body: body,
    }).then(function (res) {
      if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
      return res.json();
    }).then(function (data) {
      if (data && data.message) return data.message;
      if (data && data.question) return data.question;
      return 'OK';
    });
  }

  // PLANNER-REBUILD read-hook (CALL TIME ONLY — no styling/logic changes).
  // Returns a one-line summary of recent planner schedule changes, or ''
  // when the shared feed (globalThis.ChronosAiContext) is absent/empty.
  // Guarded: never throws, never fetches. All data-action attributes and
  // fetch paths below are byte-identical.
  function recentScheduleLine() {
    try {
      var g = (typeof globalThis !== 'undefined') ? globalThis.ChronosAiContext : null;
      if (g && typeof g.summarizeRecent === 'function') {
        var s = g.summarizeRecent(3);
        if (s) return String(s);
      }
    } catch (_) { /* best-effort only */ }
    return '';
  }

  // mountAiRow(container, ctx?) -> { row, micBtn, form, input, statusEl }
  // ctx: { getServerUrl?, getKey?, fetch?, onAsk?(text)->Promise<string>,
  //        contextLabel?, voiceBlob?() }
  function mountAiRow(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;

    // SHELL-THEME omnibar skin (classes only — data-action/fetch identical).
    var row = el(doc, 'div', 'chronos-ai-row jarvis-ai-row chronos-omnibar is-floating');
    row.setAttribute('data-screen-part', 'ai-row');
    row.setAttribute('data-theme', 'jarvis');

    var micBtn = el(doc, 'button', 'chronos-ai-mic jarvis-mic mic-ring', 'Mic');
    micBtn.type = 'button';
    micBtn.setAttribute('data-action', 'ai-voice');
    micBtn.title = 'Send voice note (POST /api/voice)';

    var form = el(doc, 'form', 'chronos-ai-form jarvis-ai-form');
    form.setAttribute('data-action', 'ai-form');
    var input = el(doc, 'input', 'chronos-ai-input jarvis-ai-input');
    input.type = 'text';
    input.name = 'ai-text';
    input.placeholder = 'Ask Chronos / Execute →';
    input.setAttribute('data-action', 'ai-text');
    input.setAttribute('aria-label', 'Ask Chronos');
    var sendBtn = el(doc, 'button', 'chronos-ai-send btn primary jarvis-send', 'Send');
    sendBtn.type = 'submit';
    sendBtn.setAttribute('data-action', 'ai-send');
    form.appendChild(input);
    form.appendChild(sendBtn);

    var statusEl = el(doc, 'div', 'chronos-ai-status jarvis-ai-status');
    statusEl.setAttribute('data-part', 'ai-status');
    statusEl.setAttribute('role', 'status');

    var banner = el(doc, 'div', 'chronos-banner jarvis-banner');
    banner.setAttribute('data-part', 'ai-banner');
    banner.hidden = true;

    function showBanner(msg) {
      banner.textContent = msg;
      banner.hidden = false;
    }
    function hideBanner() {
      banner.hidden = true;
      banner.textContent = '';
    }
    function setStatus(msg) {
      statusEl.textContent = msg;
    }

    row.appendChild(micBtn);
    row.appendChild(form);
    row.appendChild(statusEl);
    row.appendChild(banner);
    container.appendChild(row);

    function doVoice() {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        setStatus('Voice unavailable (no network layer).');
        showBanner('Voice unavailable: no fetch implementation.');
        return;
      }
      var serverUrl = serverUrlOf(ctx);
      var key = keyOf(ctx);
      setStatus('Listening… sending…');
      micBtn.disabled = true;
      try { micBtn.classList.add('recording'); } catch (_) { /* styling only */ }
      var audioBlob = null;
      try {
        if (typeof ctx.voiceBlob === 'function') {
          audioBlob = ctx.voiceBlob();
        } else if (typeof Blob !== 'undefined') {
          audioBlob = new Blob([''], { type: 'audio/webm' });
        }
      } catch (_) { audioBlob = null; }
      var fd = null;
      try {
        if (typeof FormData !== 'undefined') {
          fd = new FormData();
          if (audioBlob) fd.append('audio', audioBlob, 'note.webm');
          else fd.append('audio', 'empty');
        }
      } catch (_) { fd = null; }
      var p;
      try {
        p = fetchFn(serverUrl + '/api/voice', {
          method: 'POST',
          headers: { 'X-Chronos-Key': key },
          body: fd,
        });
      } catch (err) {
        micBtn.disabled = true; // stay disabled: server down
        setStatus('Voice unavailable (server down).');
        showBanner('Voice failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(
        function (res) {
          if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
          return typeof res.json === 'function' ? res.json() : {};
        }
      ).then(
        function (data) {
          micBtn.disabled = false;
          try { micBtn.classList.remove('recording'); } catch (_) { /* styling only */ }
          var t = (data && (data.transcript || data.message)) || 'Voice note sent.';
          setStatus(t);
          safeNotify('Voice Note Transcribed', 'Transcribed for you, sir — ' + t);
        },
        function (err) {
          micBtn.disabled = true; // graceful disabled when server down
          try { micBtn.classList.remove('recording'); } catch (_) { /* styling only */ }
          setStatus('Voice unavailable (server down).');
          showBanner('Voice failed: ' + (err && err.message ? err.message : err));
        }
      );
    }

    function doAsk(text) {
      hideBanner();
      text = (text || '').trim();
      if (!text) {
        setStatus('Type a message first.');
        return;
      }
      setStatus('Sending…');
      var askFn = null;
      // Include recent planner schedule changes in the ask context
      // (no-op '' when the feed is absent/empty — payloads unchanged).
      var sendText = text;
      try {
        var scheduleLine = recentScheduleLine();
        if (scheduleLine) sendText = text + '\n\n[' + scheduleLine + ']';
      } catch (_) { sendText = text; }
      if (typeof ctx.onAsk === 'function') {
        askFn = (function (t) { return function () { return ctx.onAsk(t); }; })(sendText);
      } else {
        var fetchFn = fetchOf(ctx);
        if (!fetchFn) {
          setStatus('Unavailable (no network layer).');
          showBanner('Cannot send: no fetch implementation.');
          return;
        }
        var serverUrl = serverUrlOf(ctx);
        var key = keyOf(ctx);
        askFn = (function (t) { return function () { return defaultAsk(fetchFn, serverUrl, key, t); }; })(sendText);
      }
      var result;
      try {
        result = askFn();
      } catch (err) {
        setStatus('Send failed.');
        showBanner('Send failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(result).then(
        function (msg) {
          setStatus(String(msg == null ? 'OK' : msg));
          try { input.value = ''; } catch (_) { /* ignore */ }
          safeNotify('Chronos Reply', 'At your service, sir — ' + String(msg == null ? 'OK' : msg));
        },
        function (err) {
          setStatus('Send failed (server down?).');
          showBanner('Send failed: ' + (err && err.message ? err.message : err));
        }
      );
    }

    micBtn.addEventListener('click', function () { doVoice(); });
    form.addEventListener('submit', function (ev) {
      try { ev.preventDefault(); } catch (_) { /* ignore */ }
      doAsk(input.value);
    });

    return { row: row, micBtn: micBtn, form: form, input: input, statusEl: statusEl };
  }

  return {
    mountAiRow: mountAiRow,
    safeNotify: safeNotify,
  };
});
