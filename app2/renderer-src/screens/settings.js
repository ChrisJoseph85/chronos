// Chronos app2 — Settings screen (UI-B owned).
//
// Sections:
//  1. Server: base URL + instance key inputs, persisted to (guarded)
//     localStorage on Save. "Check health" -> lazy GET /api/health ->
//     health banner (ok/version or error text).
//  2. Providers: lazy Refresh (GET /api/providers), add form per group
//     (POST /api/providers), reorder up/down (PUT position), delete
//     (DELETE). Key VALUES are write-only: the add-key form POSTs the value
//     then clears the input; the UI only ever shows key_ids, never values.
//  3. Autostart toggle: talks to main ONLY via a guarded IPC call at
//     click-time (window.chronosAutostart?.set / window.chronos.setAutostart
//     when the preload exposes one). Missing IPC -> local pref + banner,
//     never a crash.
//  4. Per-category notification toggles (reminders/timer/briefing),
//     persisted locally, guarded.
//
// Rules: no network at import or at mount. Every server/IPC call is lazy
// (inside a user handler) and guarded (try/catch -> banner).
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosSettings) or required under node --test.
// Exports: { mountSettings(container, ctx?) }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosSettings = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var NOTIFY_CATS = ['reminders', 'timer', 'briefing'];

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

  function storageSet(key, value) {
    try {
      if (typeof localStorage === 'undefined') return false;
      localStorage.setItem(key, value);
      return true;
    } catch (_) {
      return false;
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

  function authHeaders(ctx) {
    return { 'Content-Type': 'application/json', 'X-Chronos-Key': keyOf(ctx) };
  }

  function baseUrlOf(ctx) {
    return serverUrlOf(ctx).replace(/\/+$/, '');
  }

  function jsonOrThrow(res) {
    if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
    return typeof res.json === 'function' ? res.json() : {};
  }

  // Guarded autostart IPC, called ONLY from the toggle click handler.
  // Returns 'ipc' | 'local' | 'failed' (never throws).
  function setAutostartAtClickTime(enabled) {
    try {
      if (typeof window !== 'undefined') {
        if (window.chronosAutostart && typeof window.chronosAutostart.set === 'function') {
          var r = window.chronosAutostart.set(enabled);
          if (r && typeof r.then === 'function') {
            r.then(function () {}, function () {});
          }
          return 'ipc';
        }
        if (window.chronos && typeof window.chronos.setAutostart === 'function') {
          var r2 = window.chronos.setAutostart(enabled);
          if (r2 && typeof r2.then === 'function') {
            r2.then(function () {}, function () {});
          }
          return 'ipc';
        }
      }
    } catch (_) {
      return 'failed';
    }
    return 'local';
  }

  // mountSettings(container, ctx?) -> handles
  // ctx: { getServerUrl?, getKey?, fetch?, mountAiRow? }
  function mountSettings(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;

    var screen = el(doc, 'section', 'chronos-screen chronos-settings');
    screen.setAttribute('data-screen', 'settings');

    screen.appendChild(el(doc, 'h2', 'chronos-screen-title', 'Settings'));

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

    // ---- 1. Server ----
    screen.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Server'));
    var srvRow = el(doc, 'div', 'chronos-row');
    var urlInput = el(doc, 'input', 'chronos-server-url');
    urlInput.type = 'text';
    urlInput.setAttribute('data-action', 'settings-server-url');
    urlInput.placeholder = 'http://127.0.0.1:8080';
    try { urlInput.value = serverUrlOf(ctx); } catch (_) { /* ignore */ }
    var keyInput = el(doc, 'input', 'chronos-server-key');
    keyInput.type = 'password';
    keyInput.setAttribute('data-action', 'settings-server-key');
    keyInput.placeholder = 'Instance key (stored locally)';
    keyInput.autocomplete = 'off';
    try { keyInput.value = keyOf(ctx); } catch (_) { /* ignore */ }
    var saveBtn = el(doc, 'button', 'chronos-btn', 'Save');
    saveBtn.type = 'button';
    saveBtn.setAttribute('data-action', 'settings-save');
    var healthBtn = el(doc, 'button', 'chronos-btn', 'Check health');
    healthBtn.type = 'button';
    healthBtn.setAttribute('data-action', 'settings-health');
    srvRow.appendChild(urlInput);
    srvRow.appendChild(keyInput);
    srvRow.appendChild(saveBtn);
    srvRow.appendChild(healthBtn);
    screen.appendChild(srvRow);

    var healthBanner = el(doc, 'div', 'chronos-health');
    healthBanner.setAttribute('data-part', 'health');
    healthBanner.setAttribute('role', 'status');
    healthBanner.textContent = 'Health not checked yet.';
    screen.appendChild(healthBanner);

    saveBtn.addEventListener('click', function () {
      hideBanner();
      var okU = true;
      var okK = true;
      try { okU = storageSet('chronos.serverUrl', urlInput.value.trim()); } catch (_) { okU = false; }
      try { okK = storageSet('chronos.key', keyInput.value); } catch (_) { okK = false; }
      if (okU && okK) {
        healthBanner.textContent = 'Server settings saved locally.';
        safeNotify('Chronos settings', 'Server settings saved.');
      } else {
        showBanner('Could not persist settings (storage unavailable).');
      }
    });

    healthBtn.addEventListener('click', function () {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        healthBanner.textContent = 'Health check unavailable (no network layer).';
        showBanner('Health check failed: no fetch implementation.');
        return;
      }
      var base = baseUrlOf(ctx);
      healthBanner.textContent = 'Checking…';
      var p;
      try {
        p = fetchFn(base + '/api/health', { method: 'GET' });
      } catch (err) {
        healthBanner.textContent = 'Server down.';
        showBanner('Health check failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(jsonOrThrow).then(
        function (data) {
          var v = data && data.version ? ' v' + data.version : '';
          healthBanner.textContent = 'OK' + v + ' (' + (data && data.status ? data.status : 'ok') + ')';
          safeNotify('Chronos health', 'Server OK' + v + '.');
        },
        function (err) {
          healthBanner.textContent = 'Server down.';
          showBanner('Health check failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // ---- 2. Providers ----
    screen.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Providers'));
    var provControls = el(doc, 'div', 'chronos-row');
    var provRefresh = el(doc, 'button', 'chronos-btn', 'Refresh providers');
    provRefresh.type = 'button';
    provRefresh.setAttribute('data-action', 'providers-refresh');
    provControls.appendChild(provRefresh);
    screen.appendChild(provControls);

    var provList = el(doc, 'div', 'chronos-providers');
    provList.setAttribute('data-part', 'providers-list');
    provList.textContent = 'Press “Refresh providers”. (No server calls until you do.)';
    screen.appendChild(provList);

    var addForm = el(doc, 'form', 'chronos-row');
    addForm.setAttribute('data-action', 'provider-add-form');
    var groupSel = el(doc, 'select', 'chronos-provider-group');
    groupSel.setAttribute('data-action', 'provider-group');
    ['stt', 'text', 'embeddings'].forEach(function (g) {
      var opt = el(doc, 'option', null, g);
      opt.value = g;
      groupSel.appendChild(opt);
    });
    var nameInput = el(doc, 'input', 'chronos-provider-name');
    nameInput.type = 'text';
    nameInput.placeholder = 'Name';
    nameInput.setAttribute('data-action', 'provider-name');
    var urlInputP = el(doc, 'input', 'chronos-provider-url');
    urlInputP.type = 'text';
    urlInputP.placeholder = 'Base URL';
    urlInputP.setAttribute('data-action', 'provider-url');
    var modelInput = el(doc, 'input', 'chronos-provider-model');
    modelInput.type = 'text';
    modelInput.placeholder = 'Model (optional)';
    modelInput.setAttribute('data-action', 'provider-model');
    var addBtn = el(doc, 'button', 'chronos-btn', 'Add provider');
    addBtn.type = 'submit';
    addBtn.setAttribute('data-action', 'provider-add');
    addForm.appendChild(groupSel);
    addForm.appendChild(nameInput);
    addForm.appendChild(urlInputP);
    addForm.appendChild(modelInput);
    addForm.appendChild(addBtn);
    screen.appendChild(addForm);

    function keyIdsOf(entry) {
      if (entry.key_ids && typeof entry.key_ids.length === 'number') return entry.key_ids;
      if (typeof entry.key_count === 'number') {
        var arr = [];
        for (var i = 0; i < entry.key_count; i++) arr.push('#' + (i + 1));
        return arr;
      }
      return [];
    }

    function renderProviders(data) {
      while (provList.firstChild) provList.removeChild(provList.firstChild);
      var groups = ['stt', 'text', 'embeddings'];
      var any = false;
      groups.forEach(function (g) {
        var entries = (data && data[g]) || [];
        if (!entries.length) return;
        any = true;
        provList.appendChild(el(doc, 'h4', 'chronos-provider-group-title', g));
        entries.forEach(function (entry, idx) {
          var card = el(doc, 'div', 'chronos-provider');
          card.setAttribute('data-provider-id', String(entry.id));
          card.setAttribute('data-provider-group', g);
          var title = el(doc, 'span', 'chronos-provider-name',
            (entry.name || entry.id) + ' — ' + (entry.base_url || ''));
          card.appendChild(title);
          // Key ids only — VALUES are never rendered.
          var kids = keyIdsOf(entry);
          var kWrap = el(doc, 'span', 'chronos-provider-keys',
            'keys: ' + (kids.length ? kids.join(', ') : 'none'));
          card.appendChild(kWrap);

          var upBtn = el(doc, 'button', 'chronos-btn', 'Up');
          upBtn.type = 'button';
          upBtn.setAttribute('data-action', 'provider-up');
          upBtn.disabled = idx === 0;
          upBtn.addEventListener('click', function () {
            moveProvider(g, entry, idx, idx - 1);
          });
          var downBtn = el(doc, 'button', 'chronos-btn', 'Down');
          downBtn.type = 'button';
          downBtn.setAttribute('data-action', 'provider-down');
          downBtn.disabled = idx === entries.length - 1;
          downBtn.addEventListener('click', function () {
            moveProvider(g, entry, idx, idx + 1);
          });
          var delBtn = el(doc, 'button', 'chronos-btn', 'Delete');
          delBtn.type = 'button';
          delBtn.setAttribute('data-action', 'provider-delete');
          delBtn.addEventListener('click', function () {
            deleteProvider(entry);
          });
          card.appendChild(upBtn);
          card.appendChild(downBtn);
          card.appendChild(delBtn);

          // Add-key form: value POSTed once, input cleared, never displayed.
          var kForm = el(doc, 'form', 'chronos-row');
          kForm.setAttribute('data-action', 'provider-key-form');
          var kInput = el(doc, 'input', 'chronos-provider-key-value');
          kInput.type = 'password';
          kInput.placeholder = 'New key value (write-only)';
          kInput.autocomplete = 'off';
          kInput.setAttribute('data-action', 'provider-key-value');
          var kAdd = el(doc, 'button', 'chronos-btn', 'Add key');
          kAdd.type = 'submit';
          kAdd.setAttribute('data-action', 'provider-key-add');
          kForm.appendChild(kInput);
          kForm.appendChild(kAdd);
          kForm.addEventListener('submit', function (ev) {
            try { ev.preventDefault(); } catch (_) { /* ignore */ }
            addProviderKey(entry, kInput);
          });
          card.appendChild(kForm);

          // Delete-key buttons (ids only).
          kids.forEach(function (kid) {
            var kd = el(doc, 'button', 'chronos-btn', 'Del key ' + kid);
            kd.type = 'button';
            kd.setAttribute('data-action', 'provider-key-delete');
            kd.setAttribute('data-key-id', String(kid));
            kd.addEventListener('click', function () {
              deleteProviderKey(entry, kid);
            });
            card.appendChild(kd);
          });

          provList.appendChild(card);
        });
      });
      if (!any) provList.textContent = 'No providers configured.';
    }

    function refreshProviders() {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot load providers: no fetch implementation.');
        return;
      }
      provList.textContent = 'Loading…';
      var p;
      try {
        p = fetchFn(baseUrlOf(ctx) + '/api/providers', {
          method: 'GET',
          headers: { 'X-Chronos-Key': keyOf(ctx) },
        });
      } catch (err) {
        provList.textContent = 'Load failed.';
        showBanner('Providers load failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(jsonOrThrow).then(
        function (data) { renderProviders(data); },
        function (err) {
          provList.textContent = 'Load failed.';
          showBanner('Providers load failed: ' + (err && err.message ? err.message : err));
        }
      );
    }

    function moveProvider(group, entry, fromIdx, toIdx) {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot reorder: no fetch implementation.');
        return;
      }
      var p;
      try {
        p = fetchFn(baseUrlOf(ctx) + '/api/providers/' + encodeURIComponent(entry.id), {
          method: 'PUT',
          headers: authHeaders(ctx),
          body: JSON.stringify({ position: toIdx }),
        });
      } catch (err) {
        showBanner('Reorder failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(jsonOrThrow).then(
        function () { refreshProviders(); },
        function (err) {
          showBanner('Reorder failed: ' + (err && err.message ? err.message : err));
        }
      );
      void fromIdx;
      void group;
    }

    function deleteProvider(entry) {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot delete: no fetch implementation.');
        return;
      }
      var p;
      try {
        p = fetchFn(baseUrlOf(ctx) + '/api/providers/' + encodeURIComponent(entry.id), {
          method: 'DELETE',
          headers: { 'X-Chronos-Key': keyOf(ctx) },
        });
      } catch (err) {
        showBanner('Delete failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(jsonOrThrow).then(
        function () { refreshProviders(); },
        function (err) {
          showBanner('Delete failed: ' + (err && err.message ? err.message : err));
        }
      );
    }

    function addProviderKey(entry, kInput) {
      hideBanner();
      var value = '';
      try { value = (kInput.value || ''); } catch (_) { value = ''; }
      if (!value) {
        showBanner('Key value is empty.');
        return;
      }
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot add key: no fetch implementation.');
        return;
      }
      // Clear the input BEFORE the round-trip: the value must not linger.
      try { kInput.value = ''; } catch (_) { /* ignore */ }
      var p;
      try {
        p = fetchFn(baseUrlOf(ctx) + '/api/providers/' + encodeURIComponent(entry.id) + '/keys', {
          method: 'POST',
          headers: authHeaders(ctx),
          body: JSON.stringify({ key: value }),
        });
        value = '';
      } catch (err) {
        showBanner('Add key failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(jsonOrThrow).then(
        function () { refreshProviders(); },
        function (err) {
          showBanner('Add key failed: ' + (err && err.message ? err.message : err));
        }
      );
    }

    function deleteProviderKey(entry, keyId) {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot delete key: no fetch implementation.');
        return;
      }
      var p;
      try {
        p = fetchFn(baseUrlOf(ctx) + '/api/providers/' + encodeURIComponent(entry.id) +
          '/keys/' + encodeURIComponent(keyId), {
          method: 'DELETE',
          headers: { 'X-Chronos-Key': keyOf(ctx) },
        });
      } catch (err) {
        showBanner('Delete key failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(jsonOrThrow).then(
        function () { refreshProviders(); },
        function (err) {
          showBanner('Delete key failed: ' + (err && err.message ? err.message : err));
        }
      );
    }

    provRefresh.addEventListener('click', refreshProviders);

    addForm.addEventListener('submit', function (ev) {
      try { ev.preventDefault(); } catch (_) { /* ignore */ }
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot add provider: no fetch implementation.');
        return;
      }
      var payload = {};
      try {
        payload = {
          group: groupSel.value,
          name: nameInput.value.trim(),
          base_url: urlInputP.value.trim(),
        };
        if (modelInput.value.trim()) payload.model = modelInput.value.trim();
      } catch (_) { /* ignore */ }
      if (!payload.name || !payload.base_url) {
        showBanner('Name and base URL are required.');
        return;
      }
      var p;
      try {
        p = fetchFn(baseUrlOf(ctx) + '/api/providers', {
          method: 'POST',
          headers: authHeaders(ctx),
          body: JSON.stringify(payload),
        });
      } catch (err) {
        showBanner('Add provider failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.resolve(p).then(jsonOrThrow).then(
        function () {
          try {
            nameInput.value = '';
            urlInputP.value = '';
            modelInput.value = '';
          } catch (_) { /* ignore */ }
          refreshProviders();
        },
        function (err) {
          showBanner('Add provider failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // ---- 3. Autostart ----
    screen.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Autostart'));
    var autoRow = el(doc, 'label', 'chronos-row');
    var autoToggle = el(doc, 'input', 'chronos-autostart');
    autoToggle.type = 'checkbox';
    autoToggle.setAttribute('data-action', 'settings-autostart');
    try {
      autoToggle.checked = storageGet('chronos.autostart', 'off') === 'on';
    } catch (_) { /* ignore */ }
    autoRow.appendChild(autoToggle);
    autoRow.appendChild(el(doc, 'span', null, 'Start Chronos on login'));
    screen.appendChild(autoRow);
    var autoStatus = el(doc, 'div', 'chronos-autostart-status');
    autoStatus.setAttribute('data-part', 'autostart-status');
    autoStatus.setAttribute('role', 'status');
    screen.appendChild(autoStatus);

    // IPC touch happens HERE at click-time only — never at import/mount.
    autoToggle.addEventListener('click', function () {
      hideBanner();
      var enabled = false;
      try { enabled = !!autoToggle.checked; } catch (_) { enabled = false; }
      var how = setAutostartAtClickTime(enabled);
      try { storageSet('chronos.autostart', enabled ? 'on' : 'off'); } catch (_) { /* ignore */ }
      if (how === 'ipc') {
        autoStatus.textContent = 'Autostart ' + (enabled ? 'enabled' : 'disabled') + ' (via app).';
      } else if (how === 'local') {
        autoStatus.textContent = 'Autostart ' + (enabled ? 'enabled' : 'disabled') +
          ' (saved locally; app IPC unavailable).';
      } else {
        autoStatus.textContent = 'Autostart request failed.';
        showBanner('Autostart IPC call failed.');
      }
    });

    // ---- 4. Notification toggles ----
    screen.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Notifications'));
    var notifToggles = {};
    NOTIFY_CATS.forEach(function (cat) {
      var row = el(doc, 'label', 'chronos-row');
      var t = el(doc, 'input', 'chronos-notif-toggle');
      t.type = 'checkbox';
      t.setAttribute('data-action', 'settings-notif-' + cat);
      t.setAttribute('data-category', cat);
      try {
        t.checked = storageGet('chronos.notify.' + cat, 'on') !== 'off';
      } catch (_) { /* ignore */ }
      row.appendChild(t);
      row.appendChild(el(doc, 'span', null, cat));
      screen.appendChild(row);
      notifToggles[cat] = t;
      t.addEventListener('click', function () {
        var on = true;
        try { on = !!t.checked; } catch (_) { on = true; }
        try { storageSet('chronos.notify.' + cat, on ? 'on' : 'off'); } catch (_) { /* ignore */ }
        safeNotify('Chronos settings', 'Notifications for ' + cat + ' ' + (on ? 'on' : 'off') + '.');
      });
    });

    container.appendChild(screen);

    var aiRow = null;
    try {
      var m = (ctx && typeof ctx.mountAiRow === 'function') ? ctx.mountAiRow :
        (typeof globalThis !== 'undefined' && globalThis.ChronosAiRow &&
         typeof globalThis.ChronosAiRow.mountAiRow === 'function'
          ? globalThis.ChronosAiRow.mountAiRow : null);
      if (m) aiRow = m(screen, ctx);
    } catch (_) {
      aiRow = null;
    }

    return {
      screen: screen,
      urlInput: urlInput,
      keyInput: keyInput,
      saveBtn: saveBtn,
      healthBtn: healthBtn,
      healthBanner: healthBanner,
      provRefresh: provRefresh,
      provList: provList,
      addForm: addForm,
      groupSel: groupSel,
      nameInput: nameInput,
      urlInputP: urlInputP,
      modelInput: modelInput,
      autoToggle: autoToggle,
      autoStatus: autoStatus,
      notifToggles: notifToggles,
      aiRow: aiRow,
    };
  }

  return { mountSettings: mountSettings };
});
