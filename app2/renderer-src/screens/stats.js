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
  // as raw white when the theme palette has not landed. Palette is owned
  // by shell.css — never redefine --accent/--warn/--danger here, only
  // consume them (blue default via --accent, gold complementary via
  // --warn with #f5c042 fallback, red alerts via --danger).
  // Kinds: 'primary' | 'banner' | 'field' | 'kpi' | 'kpi-gold' |
  // 'kpi-alert' | 'insight' | 'deck' | 'chip' (all styling-only).
  function polish(node, kind) {
    if (!node || !node.style) return node;
    try {
      if (kind === 'primary') {
        node.style.boxShadow = 'var(--glow-md, var(--btn-glow, 0 0 10px rgba(79,156,249,.35)))';
      } else if (kind === 'banner') {
        node.style.background = 'var(--danger-tint, rgba(255,82,82,.10))';
        node.style.border = '1px solid var(--danger, #e5534b)';
        node.style.color = 'var(--banner-text, #ffd7d5)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '8px 12px';
        node.style.margin = '8px 0';
      } else if (kind === 'field') {
        node.style.background = 'var(--bg-2, var(--bg, #14161a))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.color = 'var(--text, #e8eaed)';
        node.style.padding = '7px 9px';
        node.style.fontSize = '13px';
      } else if (kind === 'deck') {
        node.style.background = 'linear-gradient(180deg, var(--panel-2, rgba(14,30,51,.95)), var(--panel, rgba(8,18,33,.95)))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '12px';
        node.style.marginBottom = '12px';
        node.style.boxShadow = 'inset 0 0 24px var(--accent-dim, rgba(0,212,255,.05))';
      } else if (kind === 'kpi') {
        node.style.background = 'linear-gradient(180deg, var(--panel-2, #23272f), var(--panel, #1a1e26))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderLeft = '3px solid var(--accent, #4f9cf9)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.minWidth = '0';
        node.style.boxShadow = 'var(--glow-sm, 0 0 6px rgba(79,156,249,.25))';
      } else if (kind === 'kpi-gold') {
        node.style.background = 'linear-gradient(180deg, var(--panel-2, #23272f), var(--panel, #1a1e26))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderLeft = '3px solid var(--warn, #f5c042)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.minWidth = '0';
        node.style.boxShadow = '0 0 6px var(--warn-glow, rgba(245,192,66,.25))';
      } else if (kind === 'kpi-alert') {
        node.style.background = 'linear-gradient(180deg, var(--panel-2, #23272f), var(--panel, #1a1e26))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderLeft = '3px solid var(--danger, #e5534b)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.minWidth = '0';
      } else if (kind === 'insight') {
        node.style.background = 'var(--bg-2, var(--bg, #14161a))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.color = 'var(--text, #e8eaed)';
      } else if (kind === 'chip') {
        node.style.display = 'inline-block';
        node.style.background = 'var(--accent-dim, rgba(79,156,249,.12))';
        node.style.border = '1px solid var(--accent, #4f9cf9)';
        node.style.borderRadius = '20px';
        node.style.padding = '3px 10px';
        node.style.margin = '2px 4px 2px 0';
        node.style.fontSize = '12px';
        node.style.color = 'var(--accent, #4f9cf9)';
      }
    } catch (_) { /* styling only — never break clicks */ }
    return node;
  }

  // Styling-only helpers (no fetch, no handlers): apply Cyber-HUD accents
  // via consumed shell variables. Never redefine palette.
  function styleKpiLabel(node) {
    try {
      node.style.color = 'var(--muted, #7fa3b8)';
      node.style.fontSize = '11px';
      node.style.letterSpacing = '0.08em';
      node.style.textTransform = 'uppercase';
    } catch (_) { /* ignore */ }
    return node;
  }

  function styleKpiValue(node, tone) {
    try {
      node.style.fontFamily = 'var(--mono, monospace)';
      node.style.fontSize = '20px';
      node.style.fontWeight = '700';
      node.style.color = tone === 'gold' ? 'var(--warn, #f5c042)'
        : tone === 'alert' ? 'var(--danger, #e5534b)'
        : 'var(--accent, #4f9cf9)';
      node.style.textShadow = 'var(--glow-sm, 0 0 6px rgba(79,156,249,.3))';
    } catch (_) { /* ignore */ }
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
        // Cyber-HUD palette (canvas cannot resolve var()): blue default
        // bars, gold #f5c042 leader, ice-cyan labels. Hand-rolled rects stay.
        try { ctx2d.fillStyle = j === 0 ? '#f5c042' : '#4a90d9'; } catch (_) { /* ignore */ }
        ctx2d.fillRect(labelW, y, bw, barH);
        try { ctx2d.fillStyle = '#d7f3ff'; } catch (_) { /* ignore */ }
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

    var rangeCard = polish(el(doc, 'div', 'card chronos-deck chronos-range-deck'), 'deck');
    rangeCard.setAttribute('data-deck', 'range');
    rangeCard.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Range'));
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

    // --- Cyber-HUD KPI strip: 4 cards (styling/DOM only; values mirror the
    // same /api/stats payload rendered into the summary below). ---
    var kpiStrip = el(doc, 'div', 'chronos-kpi-strip');
    kpiStrip.setAttribute('data-part', 'kpi-strip');
    try {
      kpiStrip.style.display = 'grid';
      kpiStrip.style.gridTemplateColumns = 'repeat(4, minmax(0, 1fr))';
      kpiStrip.style.gap = '8px';
      kpiStrip.style.margin = '8px 0';
    } catch (_) { /* ignore */ }
    var kpiDefs = [
      { label: 'Focus', tone: 'blue', kind: 'kpi' },
      { label: 'Sessions', tone: 'gold', kind: 'kpi-gold' },
      { label: 'Streak', tone: 'blue', kind: 'kpi' },
      { label: 'Attention', tone: 'alert', kind: 'kpi-alert' },
    ];
    var kpiValues = [];
    kpiDefs.forEach(function (def, i) {
      var card = polish(el(doc, 'div', 'chronos-kpi card'), def.kind);
      card.setAttribute('data-part', 'kpi-' + i);
      var lab = styleKpiLabel(el(doc, 'div', 'chronos-kpi-label', def.label));
      var val = styleKpiValue(el(doc, 'div', 'chronos-kpi-value', '—'), def.tone);
      val.setAttribute('data-part', 'kpi-value-' + i);
      card.appendChild(lab);
      card.appendChild(val);
      kpiStrip.appendChild(card);
      kpiValues.push(val);
    });
    screen.appendChild(kpiStrip);

    var summary = el(doc, 'div', 'chronos-stats-summary status');
    summary.setAttribute('data-part', 'stats-summary');
    summary.textContent = 'Press “Load stats”. (No server calls until you do.)';
    try {
      summary.style.fontFamily = 'var(--mono, monospace)';
      summary.style.fontSize = '12px';
    } catch (_) { /* ignore */ }
    screen.appendChild(summary);

    var chartCard = polish(el(doc, 'div', 'card chronos-deck chronos-chart-deck'), 'deck');
    chartCard.setAttribute('data-deck', 'chart');
    chartCard.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Chart — line / donut / heatmap'));
    // Presentational legend chips for the hand-rolled canvas views
    // (no SVG port; canvas stays the renderer).
    var legend = el(doc, 'div', 'chronos-chart-legend');
    legend.setAttribute('data-part', 'chart-legend');
    try {
      legend.style.display = 'flex';
      legend.style.gap = '6px';
      legend.style.flexWrap = 'wrap';
      legend.style.margin = '0 0 8px';
    } catch (_) { /* ignore */ }
    [['line', 'kpi'], ['donut', 'kpi-gold'], ['heatmap', 'kpi-alert']].forEach(function (pair) {
      var chip = polish(el(doc, 'span', 'tag-chip chronos-legend-chip', pair[0]), 'chip');
      try {
        if (pair[1] === 'kpi-gold') {
          chip.style.borderColor = 'var(--warn, #f5c042)';
          chip.style.color = 'var(--warn, #f5c042)';
        } else if (pair[1] === 'kpi-alert') {
          chip.style.borderColor = 'var(--danger, #e5534b)';
          chip.style.color = 'var(--danger, #e5534b)';
        }
      } catch (_) { /* ignore */ }
      legend.appendChild(chip);
    });
    chartCard.appendChild(legend);
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

    var tableWrap = polish(el(doc, 'div', 'chronos-stats-table-wrap card chronos-deck'), 'deck');
    tableWrap.setAttribute('data-part', 'stats-table');
    tableWrap.setAttribute('data-deck', 'breakdown');
    screen.appendChild(tableWrap);

    // --- Insight panels (styling/DOM only; mirror of the same payloads). ---
    var insights = el(doc, 'div', 'chronos-insights');
    insights.setAttribute('data-part', 'insights');
    try {
      insights.style.display = 'grid';
      insights.style.gridTemplateColumns = 'repeat(2, minmax(0, 1fr))';
      insights.style.gap = '8px';
      insights.style.margin = '8px 0';
    } catch (_) { /* ignore */ }
    var insightTop = polish(el(doc, 'div', 'chronos-insight card'), 'insight');
    insightTop.setAttribute('data-part', 'insight-top');
    insightTop.appendChild(el(doc, 'h4', 'chronos-insight-title', 'Top focus'));
    var insightTopBody = el(doc, 'p', 'chronos-insight-body', 'Load stats to see your top focus area.');
    try { insightTopBody.style.color = 'var(--text, #e8eaed)'; } catch (_) { /* ignore */ }
    insightTop.appendChild(insightTopBody);
    var insightCov = polish(el(doc, 'div', 'chronos-insight card'), 'insight');
    insightCov.setAttribute('data-part', 'insight-coverage');
    try { insightCov.style.borderLeft = '3px solid var(--warn, #f5c042)'; } catch (_) { /* ignore */ }
    insightCov.appendChild(el(doc, 'h4', 'chronos-insight-title', 'Coverage'));
    var insightCovBody = el(doc, 'p', 'chronos-insight-body', 'Coverage appears after loading.');
    try { insightCovBody.style.color = 'var(--muted, #7fa3b8)'; } catch (_) { /* ignore */ }
    insightCov.appendChild(insightCovBody);
    insights.appendChild(insightTop);
    insights.appendChild(insightCov);
    screen.appendChild(insights);

    function setKpi(i, text) {
      try {
        if (kpiValues[i]) kpiValues[i].textContent = String(text);
      } catch (_) { /* styling-only mirror */ }
    }

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
      // KPI mirror (same data, no new fetch): first count, count of keys,
      // first streak, streak-key count. Keeps textContent-based tests green.
      try {
        var ck = Object.keys(counts);
        var sk = Object.keys(streaks);
        setKpi(0, ck.length ? counts[ck[0]] : '—');
        setKpi(1, ck.length ? String(ck.length) : '—');
        setKpi(2, sk.length ? streaks[sk[0]] : '—');
        setKpi(3, sk.length ? String(sk.length) : '0');
      } catch (_) { /* ignore */ }
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
      // Themed via consumed shell variables (accent headers, mono cells).
      var table = el(doc, 'table', 'chronos-stats-table data');
      try {
        table.style.width = '100%';
        table.style.borderCollapse = 'collapse';
        table.style.fontFamily = 'var(--mono, monospace)';
        table.style.fontSize = '13px';
        table.style.color = 'var(--text, #e8eaed)';
      } catch (_) { /* ignore */ }
      var head = el(doc, 'tr');
      ['Item', 'Time'].forEach(function (t) {
        var th = el(doc, 'th', null, t);
        try {
          th.style.color = 'var(--accent, #4f9cf9)';
          th.style.textAlign = 'left';
          th.style.padding = '5px 6px';
          th.style.borderBottom = '1px solid var(--border, #333945)';
          th.style.letterSpacing = '0.06em';
          th.style.textTransform = 'uppercase';
          th.style.fontSize = '11px';
        } catch (_) { /* ignore */ }
        head.appendChild(th);
      });
      table.appendChild(head);
      rows.forEach(function (r, idx) {
        var tr = el(doc, 'tr');
        try {
          if (idx === 0) tr.style.background = 'var(--accent-dim, rgba(79,156,249,.08))';
          tr.style.borderBottom = '1px solid var(--border, #333945)';
        } catch (_) { /* ignore */ }
        var td0 = el(doc, 'td', null, r.label);
        var td1 = el(doc, 'td', null, fmtMs(r.value));
        try {
          td0.style.padding = '5px 6px';
          td1.style.padding = '5px 6px';
          td1.style.color = idx === 0 ? 'var(--warn, #f5c042)' : 'var(--text, #e8eaed)';
        } catch (_) { /* ignore */ }
        tr.appendChild(td0);
        tr.appendChild(td1);
        table.appendChild(tr);
      });
      tableWrap.appendChild(table);
      // Insight mirror (same rows, no new fetch).
      try {
        if (rows.length) {
          var total = rows.reduce(function (a, r) { return a + (Number(r.value) || 0); }, 0);
          insightTopBody.textContent = rows[0].label + ' leads at ' + fmtMs(rows[0].value) + '.';
          insightCovBody.textContent = rows.length + ' areas · ' + fmtMs(total) + ' total tracked.';
        } else {
          insightTopBody.textContent = 'No breakdown rows returned.';
          insightCovBody.textContent = 'Nothing tracked in this range yet.';
        }
      } catch (_) { /* ignore */ }
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

    var aiCard = polish(el(doc, 'div', 'card chronos-deck'), 'deck');
    aiCard.setAttribute('data-deck', 'ask');
    aiCard.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Ask Chronos'));
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
