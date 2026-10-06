// Chronos app2 — Stats screen (UI-B owned).
//
// Counts/streaks + per-child breakdown, drawn as hand-rolled canvas charts
// (no chart libs — plain 2D rects + labels). Canvas work is guarded: when
// getContext() is unavailable (e.g. jsdom without the canvas package) the
// screen falls back to a data table and clicks keep working.
//
// Rules: no network at import or at mount — fetches fire only inside the
// "Load stats" click handler, guarded (try/catch -> banner).
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosStats) or required under node --test.
// Exports: { mountStats(container, ctx?) }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosStats = factory();
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

  // SCREENS-STYLE polish only (no logic, no fetch): consume the shell
  // :root theme variables with local fallbacks, so controls never render
  // as raw white when the theme palette has not landed.
  function polish(node, kind) {
    if (!node || !node.style) return node;
    try {
      if (kind === 'primary') {
        node.style.boxShadow = 'var(--btn-glow, 0 0 10px rgba(79,156,249,.35))';
      } else if (kind === 'banner') {
        node.style.background = 'var(--danger-tint, #3d1f1d)';
        node.style.border = '1px solid var(--danger, #e5534b)';
        node.style.color = 'var(--banner-text, #ffd7d5)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '8px 12px';
        node.style.margin = '8px 0';
      } else if (kind === 'field') {
        node.style.background = 'var(--bg, #14161a)';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.color = 'var(--text, #e8eaed)';
        node.style.padding = '7px 9px';
        node.style.fontSize = '13px';
      }
    } catch (_) { /* styling only — never break clicks */ }
    return node;
  }

  function fmtMs(ms) {
    ms = Number(ms) || 0;
    var mins = Math.round(ms / 60000);
    if (mins < 60) return mins + 'm';
    var h = Math.floor(mins / 60);
    var m = mins % 60;
    return h + 'h ' + m + 'm';
  }

  // Hand-rolled horizontal bar chart. rows: [{label, value(ms)}].
  // Pure canvas 2D — no libraries. Throws nothing; returns 'canvas' or 'table'.
  function drawBars(canvas, rows) {
    var tableFallback = function () { return 'table'; };
    var ctx2d = null;
    try {
      ctx2d = canvas.getContext('2d');
    } catch (_) {
      return tableFallback();
    }
    if (!ctx2d) return tableFallback();
    try {
      var W = canvas.width || 600;
      var H = canvas.height || 240;
      ctx2d.clearRect(0, 0, W, H);
      var max = 0;
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].value > max) max = rows[i].value;
      }
      if (max <= 0) max = 1;
      var barH = 22;
      var gap = 10;
      var labelW = 150;
      var y = 12;
      ctx2d.font = '12px sans-serif';
      for (var j = 0; j < rows.length; j++) {
        if (y + barH > H) break;
        var r = rows[j];
        var bw = Math.max(2, ((W - labelW - 90) * r.value) / max);
        try { ctx2d.fillStyle = '#4a90d9'; } catch (_) { /* ignore */ }
        ctx2d.fillRect(labelW, y, bw, barH);
        try { ctx2d.fillStyle = '#000'; } catch (_) { /* ignore */ }
        var label = String(r.label).slice(0, 22);
        ctx2d.fillText(label, 6, y + 15);
        ctx2d.fillText(fmtMs(r.value), labelW + bw + 6, y + 15);
        y += barH + gap;
      }
      return 'canvas';
    } catch (_) {
      return tableFallback();
    }
  }

  // mountStats(container, ctx?) -> handles
  // ctx: { getServerUrl?, getKey?, fetch?, mountAiRow? }
  function mountStats(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;

    var screen = el(doc, 'section', 'chronos-screen chronos-stats screen');
    screen.setAttribute('data-screen', 'stats');

    screen.appendChild(el(doc, 'h2', 'chronos-screen-title', 'Stats'));
    screen.appendChild(el(doc, 'p', 'sub', 'Offline — no server calls until you press “Load stats”.'));

    var banner = polish(el(doc, 'div', 'chronos-banner status'), 'banner');
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

    var rangeCard = el(doc, 'div', 'card');
    rangeCard.appendChild(el(doc, 'h3', null, 'Range'));
    var controls = el(doc, 'div', 'chronos-row row');
    var fromInput = polish(el(doc, 'input', 'chronos-from'), 'field');
    fromInput.type = 'date';
    fromInput.setAttribute('data-action', 'stats-from');
    var toInput = polish(el(doc, 'input', 'chronos-to'), 'field');
    toInput.type = 'date';
    toInput.setAttribute('data-action', 'stats-to');
    var loadBtn = polish(el(doc, 'button', 'chronos-btn btn primary', 'Load stats'), 'primary');
    loadBtn.type = 'button';
    loadBtn.setAttribute('data-action', 'stats-load');
    controls.appendChild(el(doc, 'span', null, 'From '));
    controls.appendChild(fromInput);
    controls.appendChild(el(doc, 'span', null, 'To '));
    controls.appendChild(toInput);
    controls.appendChild(loadBtn);
    rangeCard.appendChild(controls);
    screen.appendChild(rangeCard);

    var summary = el(doc, 'div', 'chronos-stats-summary status');
    summary.setAttribute('data-part', 'stats-summary');
    summary.textContent = 'Press “Load stats”. (No server calls until you do.)';
    screen.appendChild(summary);

    var chartCard = el(doc, 'div', 'card');
    chartCard.appendChild(el(doc, 'h3', null, 'Chart'));
    var canvas = null;
    try {
      canvas = doc.createElement('canvas');
      canvas.className = 'chronos-stats-chart';
      canvas.setAttribute('data-part', 'stats-chart');
      canvas.width = 600;
      canvas.height = 240;
      try {
        canvas.style.maxWidth = '100%';
        canvas.style.borderRadius = 'var(--radius, 8px)';
        canvas.style.border = '1px solid var(--border, #333945)';
        canvas.style.background = 'var(--bg, #14161a)';
      } catch (_) { /* ignore */ }
      chartCard.appendChild(canvas);
    } catch (_) {
      canvas = null;
    }
    screen.appendChild(chartCard);

    var tableWrap = el(doc, 'div', 'chronos-stats-table-wrap card');
    tableWrap.setAttribute('data-part', 'stats-table');
    screen.appendChild(tableWrap);

    function renderSummary(stats) {
      while (summary.firstChild) summary.removeChild(summary.firstChild);
      var counts = (stats && stats.counts) || {};
      var streaks = (stats && stats.streaks) || {};
      var dl = el(doc, 'dl', 'chronos-stats-list');
      function add(term, value) {
        var dt = el(doc, 'dt', null, term);
        var dd = el(doc, 'dd');
        dd.textContent = String(value == null ? '—' : (typeof value === 'object' ? JSON.stringify(value) : value));
        dl.appendChild(dt);
        dl.appendChild(dd);
      }
      Object.keys(counts).forEach(function (k) { add('count.' + k, counts[k]); });
      Object.keys(streaks).forEach(function (k) { add('streak.' + k, streaks[k]); });
      if (!dl.firstChild) summary.textContent = JSON.stringify(stats || {});
      else summary.appendChild(dl);
    }

    function renderBreakdown(items) {
      while (tableWrap.firstChild) tableWrap.removeChild(tableWrap.firstChild);
      var rows = (items || []).map(function (it) {
        return {
          label: it.title || it.node_id || '?',
          value: Number(it.total_ms) || 0,
        };
      });
      var mode = 'table';
      if (canvas) {
        try {
          canvas.setAttribute('data-render-mode', 'pending');
          mode = drawBars(canvas, rows);
          canvas.setAttribute('data-render-mode', mode);
        } catch (_) {
          mode = 'table';
        }
      }
      // Always render the accessible table too (and as the fallback).
      var table = el(doc, 'table', 'chronos-stats-table data');
      var head = el(doc, 'tr');
      head.appendChild(el(doc, 'th', null, 'Item'));
      head.appendChild(el(doc, 'th', null, 'Time'));
      table.appendChild(head);
      rows.forEach(function (r) {
        var tr = el(doc, 'tr');
        tr.appendChild(el(doc, 'td', null, r.label));
        tr.appendChild(el(doc, 'td', null, fmtMs(r.value)));
        table.appendChild(tr);
      });
      tableWrap.appendChild(table);
      return mode;
    }

    loadBtn.addEventListener('click', function () {
      hideBanner();
      var fetchFn = fetchOf(ctx);
      if (!fetchFn) {
        showBanner('Cannot load stats: no fetch implementation.');
        return;
      }
      var serverUrl = serverUrlOf(ctx);
      var key = keyOf(ctx);
      var from = '';
      var to = '';
      try {
        from = fromInput.value || '';
        to = toInput.value || '';
      } catch (_) { /* ignore */ }
      summary.textContent = 'Loading…';
      var headers = { 'X-Chronos-Key': key };
      var pStats, pBreak;
      try {
        pStats = fetchFn(serverUrl + '/api/stats', { method: 'GET', headers: headers });
        var bUrl = serverUrl + '/api/stats/breakdown';
        if (from && to) {
          bUrl += '?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to);
        }
        pBreak = fetchFn(bUrl, { method: 'GET', headers: headers });
      } catch (err) {
        summary.textContent = 'Load failed.';
        showBanner('Stats load failed: ' + (err && err.message ? err.message : err));
        return;
      }
      Promise.all([pStats, pBreak]).then(
        function (ress) {
          var ok0 = ress[0] && ress[0].ok;
          if (!ok0) throw new Error('HTTP ' + (ress[0] && ress[0].status));
          return Promise.all([
            typeof ress[0].json === 'function' ? ress[0].json() : {},
            ress[1] && ress[1].ok && typeof ress[1].json === 'function' ? ress[1].json() : [],
          ]);
        }
      ).then(
        function (pair) {
          renderSummary(pair[0]);
          renderBreakdown(pair[1]);
          safeNotify('Chronos stats', 'Stats loaded.');
        },
        function (err) {
          summary.textContent = 'Load failed.';
          showBanner('Stats load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    var aiCard = el(doc, 'div', 'card');
    aiCard.appendChild(el(doc, 'h3', null, 'Ask Chronos'));
    screen.appendChild(aiCard);

    container.appendChild(screen);

    var aiRow = null;
    try {
      var m = (ctx && typeof ctx.mountAiRow === 'function') ? ctx.mountAiRow :
        (typeof globalThis !== 'undefined' && globalThis.ChronosAiRow &&
         typeof globalThis.ChronosAiRow.mountAiRow === 'function'
          ? globalThis.ChronosAiRow.mountAiRow : null);
      if (m) aiRow = m(aiCard, ctx);
    } catch (_) {
      aiRow = null;
    }

    return {
      screen: screen,
      fromInput: fromInput,
      toInput: toInput,
      loadBtn: loadBtn,
      summary: summary,
      canvas: canvas,
      tableWrap: tableWrap,
      aiRow: aiRow,
    };
  }

  return { mountStats: mountStats };
});
