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
    try {
      if (typeof window !== 'undefined' && typeof window.chronosNotify === 'function') {
        window.chronosNotify({ title: title, body: body });
        return;
      }
    } catch (_) { /* fall through to contract shape */ }
    try {
      if (typeof window !== 'undefined' && window.chronos &&
          typeof window.chronos.notify === 'function') {
        window.chronos.notify({ title: title, body: body });
      }
    } catch (_) { /* notifications are best-effort */ }
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

  // mountAiRow(container, ctx?) -> { row, micBtn, form, input, statusEl }
  // ctx: { getServerUrl?, getKey?, fetch?, onAsk?(text)->Promise<string>,
  //        contextLabel?, voiceBlob?() }
  function mountAiRow(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;

    var row = el(doc, 'div', 'chronos-ai-row');
    row.setAttribute('data-screen-part', 'ai-row');

    var micBtn = el(doc, 'button', 'chronos-ai-mic', 'Mic');
    micBtn.type = 'button';
    micBtn.setAttribute('data-action', 'ai-voice');
    micBtn.title = 'Send voice note (POST /api/voice)';

    var form = el(doc, 'form', 'chronos-ai-form');
    form.setAttribute('data-action', 'ai-form');
    var input = el(doc, 'input', 'chronos-ai-input');
    input.type = 'text';
    input.name = 'ai-text';
    input.placeholder = 'Ask Chronos…';
    input.setAttribute('data-action', 'ai-text');
    var sendBtn = el(doc, 'button', 'chronos-ai-send', 'Send');
    sendBtn.type = 'submit';
    sendBtn.setAttribute('data-action', 'ai-send');
    form.appendChild(input);
    form.appendChild(sendBtn);

    var statusEl = el(doc, 'div', 'chronos-ai-status');
    statusEl.setAttribute('data-part', 'ai-status');
    statusEl.setAttribute('role', 'status');

    var banner = el(doc, 'div', 'chronos-banner');
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
          var t = (data && (data.transcript || data.message)) || 'Voice note sent.';
          setStatus(t);
          safeNotify('Chronos voice', t);
        },
        function (err) {
          micBtn.disabled = true; // graceful disabled when server down
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
      if (typeof ctx.onAsk === 'function') {
        askFn = function () { return ctx.onAsk(text); };
      } else {
        var fetchFn = fetchOf(ctx);
        if (!fetchFn) {
          setStatus('Unavailable (no network layer).');
          showBanner('Cannot send: no fetch implementation.');
          return;
        }
        var serverUrl = serverUrlOf(ctx);
        var key = keyOf(ctx);
        askFn = function () { return defaultAsk(fetchFn, serverUrl, key, text); };
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
          safeNotify('Chronos', String(msg == null ? 'OK' : msg));
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
