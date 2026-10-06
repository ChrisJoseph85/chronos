// Chronos app2 — sidebar/nav shell (UI-A owned).
//
// Sidebar nav (Planner/Timer+Log/Briefing/Stats/Settings), collapsible to
// icons (persisted), screen container switching, global banner, drag
// splitters (persisted), lazy API helper + guarded preload notify.
//
// Rules: no network, no window.chronos, no storage access at import time.
// Everything runs at call time via initShell(document).
// Screens mount via mountPlanner/mountTimer(container, ctx) style fns.
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosShell) or required under node --test.
// Exports: { SCREENS, initShell, navigate, showBanner, clearBanner,
//            apiFetch, notify, storeGet, storeSet, defaultCtx }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosShell = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SCREENS = ['planner', 'timer', 'briefing', 'stats', 'settings'];
  var COLLAPSE_KEY = 'chronos.sidebar.collapsed';
  var SCREEN_KEY = 'chronos.screen';
  var WIDTH_KEY = 'chronos.sidebar.width';
  var SERVER_URL_KEY = 'chronos.serverUrl';
  var SERVER_KEY_KEY = 'chronos.key';
  // THEME (class/toggle only — no logic changes elsewhere).
  var THEME_KEY = 'chronos.theme';
  var THEME_NAME = 'jarvis';

  // Apply the JARVIS theme class + data attribute. Pure DOM, call-time
  // only; never touches network or the preload bridge.
  function applyTheme(doc, name) {
    try {
      var root = doc ? doc.documentElement : null;
      if (!root) return name || THEME_NAME;
      var theme = name || storeGet(THEME_KEY, THEME_NAME) || THEME_NAME;
      root.setAttribute('data-theme', theme);
      var body = doc.body;
      if (body) {
        if (theme === THEME_NAME) body.classList.add('jarvis-theme');
        else body.classList.remove('jarvis-theme');
      }
      var toggles = doc.querySelectorAll('[data-theme-toggle]');
      for (var i = 0; i < toggles.length; i++) {
        try {
          toggles[i].setAttribute('aria-pressed', theme === THEME_NAME ? 'true' : 'false');
        } catch (_) { /* ignore */ }
      }
      return theme;
    } catch (_) {
      return name || THEME_NAME;
    }
  }

  function toggleTheme(doc) {
    var next;
    try {
      var cur = storeGet(THEME_KEY, THEME_NAME);
      next = (cur === THEME_NAME) ? 'default' : THEME_NAME;
      storeSet(THEME_KEY, next);
    } catch (_) {
      next = THEME_NAME;
    }
    return applyTheme(doc, next);
  }

  function initTheme(doc) {
    if (!doc) return;
    applyTheme(doc);
    try {
      var toggles = doc.querySelectorAll('[data-theme-toggle]');
      for (var i = 0; i < toggles.length; i++) {
        (function (btn) {
          btn.addEventListener('click', function () {
            toggleTheme(doc);
          });
        })(toggles[i]);
      }
    } catch (_) { /* theme toggle is optional */ }
  }

  function storeGet(key, fallback) {
    try {
      if (typeof localStorage === 'undefined') return fallback;
      var v = localStorage.getItem(key);
      return v == null ? fallback : v;
    } catch (_) {
      return fallback;
    }
  }

  function storeSet(key, value) {
    try {
      if (typeof localStorage === 'undefined') return;
      localStorage.setItem(key, String(value));
    } catch (_) { /* storage unavailable — never break clicks */ }
  }

  function serverBaseOf(ctx) {
    var base = '';
    try {
      if (ctx && typeof ctx.getServerUrl === 'function') base = ctx.getServerUrl();
    } catch (_) { base = ''; }
    if (!base) base = storeGet(SERVER_URL_KEY, 'http://127.0.0.1:8080');
    return String(base).replace(/\/+$/, '');
  }

  function keyOf(ctx) {
    var key = '';
    try {
      if (ctx && typeof ctx.getKey === 'function') key = ctx.getKey();
    } catch (_) { key = ''; }
    if (!key) key = storeGet(SERVER_KEY_KEY, '');
    return key;
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

  // Lazy API helper — call time only. Throws on network/HTTP errors;
  // callers MUST try/catch and route to a banner + disabled state.
  function apiFetch(path, options, ctx) {
    var opts = options || {};
    var fetchFn = fetchOf(ctx);
    if (!fetchFn) return Promise.reject(new Error('no fetch implementation'));
    var headers = {};
    var k;
    if (opts.headers) {
      for (k in opts.headers) headers[k] = opts.headers[k];
    }
    var key = keyOf(ctx);
    if (key) headers['X-Chronos-Key'] = key;
    var url = serverBaseOf(ctx) + path;
    var p;
    try {
      p = fetchFn(url, {
        method: opts.method || 'GET',
        headers: headers,
        body: opts.body,
      });
    } catch (err) {
      return Promise.reject(err);
    }
    return Promise.resolve(p).then(function (res) {
      if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status) + ' for ' + path);
      return typeof res.json === 'function' ? res.json() : {};
    });
  }

  // Preload bridge — call time only, fully guarded. Never throws.
  // NOTE: no literal `window.chronos` reference anywhere in this file;
  // access goes through a call-time local.
  function notify(title, body) {
    try {
      var w = (typeof window !== 'undefined') ? window : undefined;
      var bridge = w ? w.chronos : undefined;
      if (bridge && typeof bridge.notify === 'function') {
        bridge.notify({ title: title, body: body });
      }
    } catch (_) { /* best-effort only */ }
  }

  function showBanner(doc, message) {
    try {
      var banner = doc.getElementById('global-banner');
      if (!banner) return;
      banner.textContent = String(message);
      banner.hidden = false;
    } catch (_) { /* ignore */ }
  }

  function clearBanner(doc) {
    try {
      var banner = doc.getElementById('global-banner');
      if (!banner) return;
      banner.textContent = '';
      banner.hidden = true;
    } catch (_) { /* ignore */ }
  }

  function navigate(doc, name) {
    if (SCREENS.indexOf(name) === -1) return;
    var panels = doc.querySelectorAll('[data-screen-panel]');
    var i;
    for (i = 0; i < panels.length; i++) {
      panels[i].hidden = panels[i].getAttribute('data-screen-panel') !== name;
    }
    var navs = doc.querySelectorAll('[data-screen-nav]');
    for (i = 0; i < navs.length; i++) {
      if (navs[i].getAttribute('data-screen-nav') === name) {
        navs[i].setAttribute('aria-current', 'page');
      } else {
        navs[i].removeAttribute('aria-current');
      }
    }
    storeSet(SCREEN_KEY, name);
  }

  function initSidebar(doc) {
    var sidebar = doc.getElementById('sidebar');
    if (!sidebar) return;
    if (storeGet(COLLAPSE_KEY, '0') === '1') sidebar.classList.add('collapsed');
    var savedWidth = parseInt(storeGet(WIDTH_KEY, ''), 10);
    if (savedWidth >= 56 && savedWidth <= 360) sidebar.style.width = savedWidth + 'px';
    var navs = sidebar.querySelectorAll('[data-screen-nav]');
    var i;
    for (i = 0; i < navs.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          navigate(doc, btn.getAttribute('data-screen-nav'));
        });
      })(navs[i]);
    }
    var collapse = doc.getElementById('sidebar-collapse');
    if (collapse) {
      collapse.addEventListener('click', function () {
        sidebar.classList.toggle('collapsed');
        storeSet(COLLAPSE_KEY, sidebar.classList.contains('collapsed') ? '1' : '0');
      });
    }
  }

  function wireSplitter(doc, splitter) {
    var key = splitter.getAttribute('data-split-key');
    var targetId = splitter.getAttribute('data-split-target');
    splitter.addEventListener('pointerdown', function (ev) {
      try { ev.preventDefault(); } catch (_) { /* ignore */ }
      var target = targetId ? doc.getElementById(targetId) : splitter.previousElementSibling;
      if (!target) return;
      var startX = ev.clientX;
      var startW = target.getBoundingClientRect().width;
      function clamp(w) {
        if (w < 56) return 56;
        if (w > 360) return 360;
        return w;
      }
      function onMove(e2) {
        target.style.width = clamp(startW + (e2.clientX - startX)) + 'px';
      }
      function onUp(e2) {
        if (key) storeSet(key, String(Math.round(clamp(startW + (e2.clientX - startX)))));
        doc.documentElement.removeEventListener('pointermove', onMove);
        doc.documentElement.removeEventListener('pointerup', onUp);
      }
      doc.documentElement.addEventListener('pointermove', onMove);
      doc.documentElement.addEventListener('pointerup', onUp);
    });
  }

  function initSplitters(doc) {
    var splitters = doc.querySelectorAll('.splitter');
    for (var i = 0; i < splitters.length; i++) wireSplitter(doc, splitters[i]);
  }

  function initShell(doc) {
    if (!doc) return;
    initTheme(doc);
    initSidebar(doc);
    initSplitters(doc);
    var start = storeGet(SCREEN_KEY, 'planner');
    if (SCREENS.indexOf(start) === -1) start = 'planner';
    navigate(doc, start);
  }

  // Shared ctx for screens (UI-A + UI-B mount fns accept ctx).
  function defaultCtx() {
    return {
      getServerUrl: function () { return storeGet(SERVER_URL_KEY, 'http://127.0.0.1:8080'); },
      getKey: function () { return storeGet(SERVER_KEY_KEY, ''); },
    };
  }

  return {
    SCREENS: SCREENS,
    initShell: initShell,
    navigate: navigate,
    showBanner: showBanner,
    clearBanner: clearBanner,
    apiFetch: apiFetch,
    notify: notify,
    storeGet: storeGet,
    storeSet: storeSet,
    defaultCtx: defaultCtx,
    applyTheme: applyTheme,
    toggleTheme: toggleTheme,
  };
});
