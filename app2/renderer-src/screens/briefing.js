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

  // SCREENS-STYLE polish only (no logic, no fetch): consume the shell
  // :root theme variables with local fallbacks, so controls never render
  // as raw white when the theme palette has not landed. Palette owned by
  // shell.css — never redefine --accent/--warn/--danger here (blue default
  // via --accent, gold complementary via --warn/#f5c042, red alerts via
  // --danger). Kinds: 'primary' | 'banner' | 'field' | 'deck' | 'metric' |
  // 'metric-gold' | 'metric-alert' | 'answer' | 'queue'.
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
      } else if (kind === 'metric') {
        node.style.background = 'linear-gradient(180deg, var(--panel-2, #23272f), var(--panel, #1a1e26))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderTop = '3px solid var(--accent, #4f9cf9)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.minWidth = '0';
      } else if (kind === 'metric-gold') {
        node.style.background = 'linear-gradient(180deg, var(--panel-2, #23272f), var(--panel, #1a1e26))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderTop = '3px solid var(--warn, #f5c042)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.minWidth = '0';
        node.style.boxShadow = '0 0 6px var(--warn-glow, rgba(245,192,66,.25))';
      } else if (kind === 'metric-alert') {
        node.style.background = 'linear-gradient(180deg, var(--panel-2, #23272f), var(--panel, #1a1e26))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderTop = '3px solid var(--danger, #e5534b)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.minWidth = '0';
      } else if (kind === 'answer') {
        node.style.background = 'var(--bg-2, var(--bg, #14161a))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderLeft = '3px solid var(--warn, #f5c042)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '10px 12px';
        node.style.margin = '8px 0 0';
        node.style.fontSize = '13px';
        node.style.color = 'var(--text, #e8eaed)';
      } else if (kind === 'queue') {
        node.style.background = 'var(--bg-2, var(--bg, #14161a))';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '8px 10px';
        node.style.margin = '8px 0 0';
      }
    } catch (_) { /* styling only — never break clicks */ }
    return node;
  }

  // Styling-only label/value helpers (consume shell vars, never redefine).
  function styleMetricLabel(node) {
    try {
      node.style.color = 'var(--muted, #7fa3b8)';
      node.style.fontSize = '11px';
      node.style.letterSpacing = '0.08em';
      node.style.textTransform = 'uppercase';
    } catch (_) { /* ignore */ }
    return node;
  }

  function styleMetricValue(node, tone) {
    try {
      node.style.fontFamily = 'var(--mono, monospace)';
      node.style.fontSize = '20px';
      node.style.fontWeight = '700';
      node.style.color = tone === 'gold' ? 'var(--warn, #f5c042)'
        : tone === 'alert' ? 'var(--danger, #e5534b)'
        : 'var(--accent, #4f9cf9)';
    } catch (_) { /* ignore */ }
    return node;
  }

  // ENGAGEMENT-POLISH: notification copy helpers (TEXT ONLY — no styling;
  // the palette belongs to the theme siblings). Headlines are Title Case,
  // bodies are one-line Iron-Man-butler-voiced one-liners capped at 120
  // chars, never raw JSON/ids. All total (never throw).
  var NOTIFY_TEXT_MAX = 120;

  function titleCase(s) {
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

  function oneLine(s) {
    try {
      return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    } catch (_) {
      return '';
    }
  }

  function truncText(s, max) {
    var t = oneLine(s);
    if (t.length > max) return t.slice(0, max - 1) + '…';
    return t;
  }

  // Wrap safeNotify payloads: one line, no raw JSON dumps, capped.
  function notifyText(s) {
    var t = oneLine(s);
    if (!t) return t;
    if (/^[{[]/.test(t)) {
      try {
        JSON.parse(t);
        return 'The details are ready in the app, sir.';
      } catch (_) { /* not JSON — fall through */ }
    }
    return truncText(t, NOTIFY_TEXT_MAX);
  }

  function polishedNotify(title, body) {
    try {
      safeNotify(titleCase(title), notifyText(body));
    } catch (_) { /* best-effort */ }
  }

  function briefCount(v) {
    try {
      if (typeof v === 'number' && isFinite(v)) return String(v);
      if (typeof v === 'string' && v.length < 24) return v;
      if (Array.isArray(v)) return String(v.length);
    } catch (_) { /* ignore */ }
    return null;
  }

  // "3 unallocated, 1 rollover, 2 reviews due" — counts only, never raw JSON.
  function briefingSummary(data) {
    try {
      var parts = [];
      var n;
      n = briefCount(data.unallocated_tasks);
      if (n != null) parts.push(n + ' unallocated');
      n = briefCount(data.rollover);
      if (n != null) parts.push(n + ' rollover');
      n = briefCount(data.due_reviews);
      if (n != null) parts.push(n + ' reviews due');
      return parts.join(', ');
    } catch (_) {
      return '';
    }
  }

  // True when the briefing itself flags anything urgent: an explicit urgent
  // marker, a non-empty alerts/attention list, or outstanding counts.
  function briefingIsUrgent(data) {
    try {
      if (!data || typeof data !== 'object') return false;
      if (data.urgent === true) return true;
      var pri = data.priority || data.severity || data.flag;
      if (typeof pri === 'string' && pri.toLowerCase() === 'urgent') return true;
      if (Array.isArray(data.alerts) && data.alerts.length > 0) return true;
      if (Array.isArray(data.attention) && data.attention.length > 0) return true;
      var keys = ['unallocated_tasks', 'rollover', 'due_reviews', 'overdue', 'due_count'];
      for (var i = 0; i < keys.length; i++) {
        var n = Number(data[keys[i]]);
        if (isFinite(n) && n > 0) return true;
      }
    } catch (_) { /* ignore */ }
    return false;
  }

  // Explicit local configuration only (persisted via Settings Save): never
  // ctx stubs, never defaults — unconfigured boots stay fully silent.
  function configuredServer() {
    try {
      var url = storageGet('chronos.serverUrl', '');
      var key = storageGet('chronos.key', '');
      if (typeof url !== 'string' || typeof key !== 'string') return null;
      url = url.trim().replace(/\/+$/, '');
      key = key.trim();
      if (!url || !key) return null;
      return { url: url, key: key };
    } catch (_) {
      return null;
    }
  }

  function briefingAlertsEnabled() {
    try {
      return storageGet('chronos.notify.briefing', 'on') !== 'off';
    } catch (_) {
      return true;
    }
  }

  function todayISO() {    try {
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

    var screen = el(doc, 'section', 'chronos-screen chronos-briefing screen');
    screen.setAttribute('data-screen', 'briefing');

    screen.appendChild(el(doc, 'h2', 'chronos-screen-title', 'Briefing'));
    screen.appendChild(el(doc, 'p', 'sub', 'Offline — no server calls until you press a button.'));

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

    // --- briefing loader ---
    var loadCard = polish(el(doc, 'div', 'card chronos-deck chronos-briefing-loader'), 'deck');
    loadCard.setAttribute('data-deck', 'briefing-loader');
    loadCard.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Briefing for date'));
    var controls = el(doc, 'div', 'chronos-row row');
    var dateInput = polish(el(doc, 'input', 'chronos-date'), 'field');
    dateInput.type = 'date';
    dateInput.setAttribute('data-action', 'briefing-date');
    try { dateInput.value = todayISO(); } catch (_) { /* ignore */ }
    var loadBtn = polish(el(doc, 'button', 'chronos-btn btn primary', 'Load briefing'), 'primary');
    loadBtn.type = 'button';
    loadBtn.setAttribute('data-action', 'briefing-load');
    controls.appendChild(dateInput);
    controls.appendChild(loadBtn);
    loadCard.appendChild(controls);

    var result = el(doc, 'div', 'chronos-briefing-result status');
    result.setAttribute('data-part', 'briefing-result');
    result.textContent = 'Pick a date and press “Load briefing”. (No server calls until you do.)';
    loadCard.appendChild(result);

    // --- Cyber-HUD metric trio: Focus / Friction / Recommendation
    // (styling/DOM only; values mirror the same /api/briefing payload). ---
    var metricTrio = el(doc, 'div', 'chronos-metric-trio');
    metricTrio.setAttribute('data-part', 'metric-trio');
    try {
      metricTrio.style.display = 'grid';
      metricTrio.style.gridTemplateColumns = 'repeat(3, minmax(0, 1fr))';
      metricTrio.style.gap = '8px';
      metricTrio.style.margin = '8px 0 0';
    } catch (_) { /* ignore */ }
    var metricDefs = [
      { label: 'Focus', tone: 'blue', kind: 'metric', part: 'metric-focus' },
      { label: 'Friction', tone: 'alert', kind: 'metric-alert', part: 'metric-friction' },
      { label: 'Recommendation', tone: 'gold', kind: 'metric-gold', part: 'metric-recommendation' },
    ];
    var metricValues = [];
    metricDefs.forEach(function (def) {
      var card = polish(el(doc, 'div', 'chronos-metric card'), def.kind);
      card.setAttribute('data-part', def.part);
      card.appendChild(styleMetricLabel(el(doc, 'div', 'chronos-metric-label', def.label)));
      var mv = styleMetricValue(el(doc, 'div', 'chronos-metric-value', '—'), def.tone);
      mv.setAttribute('data-part', def.part + '-value');
      card.appendChild(mv);
      metricTrio.appendChild(card);
      metricValues.push(mv);
    });
    loadCard.appendChild(metricTrio);

    // --- Directives queue (styling/DOM only; mirrors briefing counts). ---
    var directives = polish(el(doc, 'div', 'chronos-directives'), 'queue');
    directives.setAttribute('data-part', 'directives-queue');
    directives.appendChild(el(doc, 'h4', 'chronos-sub-title', 'Directives queue'));
    var directivesList = el(doc, 'ol', 'chronos-directives-list');
    directivesList.setAttribute('data-part', 'directives-list');
    try {
      directivesList.style.margin = '4px 0 0';
      directivesList.style.paddingLeft = '20px';
      directivesList.style.color = 'var(--text, #e8eaed)';
      directivesList.style.fontSize = '13px';
    } catch (_) { /* ignore */ }
    var directivesEmpty = el(doc, 'li', 'chronos-directive-empty', 'Load a briefing to queue directives.');
    directivesList.appendChild(directivesEmpty);
    directives.appendChild(directivesList);
    loadCard.appendChild(directives);

    // --- Energy-curve container (static-styled, no new libs; decorative). ---
    var energy = el(doc, 'div', 'chronos-energy-curve jarvis-hud');
    energy.setAttribute('data-part', 'energy-curve');
    energy.setAttribute('aria-hidden', 'true');
    try {
      energy.style.display = 'flex';
      energy.style.alignItems = 'flex-end';
      energy.style.gap = '3px';
      energy.style.height = '40px';
      energy.style.margin = '8px 0 0';
      energy.style.padding = '6px 8px';
    } catch (_) { /* ignore */ }
    [8, 14, 22, 18, 28, 34, 26, 20, 30, 24, 16, 10].forEach(function (hh, i) {
      var bar = el(doc, 'span', 'chronos-energy-bar');
      try {
        bar.style.display = 'inline-block';
        bar.style.width = '8px';
        bar.style.height = String(hh) + 'px';
        bar.style.borderRadius = '2px';
        bar.style.background = i % 4 === 1
          ? 'var(--warn, #f5c042)'
          : 'linear-gradient(180deg, var(--accent, #4f9cf9), var(--accent-2, #1899d6))';
        bar.style.opacity = String(0.55 + (hh / 80));
      } catch (_) { /* ignore */ }
      energy.appendChild(bar);
    });
    loadCard.appendChild(energy);
    screen.appendChild(loadCard);

    // --- proactive urgent-briefing card (hidden until an urgent briefing
    // lands via the after-first-paint check below; never banner spam) ---
    // Red-alert deck styling via consumed --danger (never redefined).
    var urgentCard = polish(el(doc, 'div', 'chronos-briefing-urgent card'), 'deck');
    urgentCard.setAttribute('data-part', 'urgent-briefing');
    urgentCard.setAttribute('role', 'status');
    try {
      urgentCard.style.borderLeft = '3px solid var(--danger, #e5534b)';
      urgentCard.style.display = 'none';
    } catch (_) { /* ignore */ }
    urgentCard.hidden = true;
    screen.appendChild(urgentCard);

    function renderUrgentBriefing(data, date) {
      try {
        while (urgentCard.firstChild) urgentCard.removeChild(urgentCard.firstChild);
        try { urgentCard.style.display = ''; } catch (_) { /* ignore */ }
        urgentCard.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Urgent Briefing'));
        var summary = briefingSummary(data);
        var text = 'Sir, ' + date + ' needs your attention';
        if (summary) text += ': ' + summary;
        text += ' — I have flagged it here for you.';
        var up = el(doc, 'p', null, text);
        try { up.style.color = 'var(--danger, #e5534b)'; } catch (_) { /* ignore */ }
        urgentCard.appendChild(up);
        urgentCard.hidden = false;
      } catch (_) { /* never break boot */ }
    }

    // Mirror the same briefing payload into the metric trio + directives
    // queue (presentation only; fetch/handler logic untouched).
    function renderHudMirrors(data) {
      try {
        var un = data && data.unallocated_tasks;
        var ro = data && data.rollover;
        var du = data && data.due_reviews;
        var q = data && (data.question || data.recommendation);
        if (metricValues[0]) metricValues[0].textContent = String(du == null ? '—' : (typeof du === 'object' ? briefCount(du) || '—' : du));
        if (metricValues[1]) metricValues[1].textContent = String(un == null ? '—' : (typeof un === 'object' ? briefCount(un) || '—' : un));
        if (metricValues[2]) metricValues[2].textContent = String(q == null ? (ro == null ? '—' : (typeof ro === 'object' ? briefCount(ro) || '—' : ro)) : (typeof q === 'object' ? JSON.stringify(q) : q)).slice(0, 48);
        while (directivesList.firstChild) directivesList.removeChild(directivesList.firstChild);
        var items = [];
        if (un != null && Number(un) > 0) items.push('Triage ' + un + ' unallocated task(s)');
        else if (un != null) items.push('Unallocated: ' + String(typeof un === 'object' ? JSON.stringify(un) : un));
        if (ro != null && Number(ro) > 0) items.push('Carry over ' + ro + ' rollover item(s)');
        else if (ro != null) items.push('Rollover: ' + String(typeof ro === 'object' ? JSON.stringify(ro) : ro));
        if (du != null && Number(du) > 0) items.push('Complete ' + du + ' due review(s)');
        else if (du != null) items.push('Due reviews: ' + String(typeof du === 'object' ? JSON.stringify(du) : du));
        if (!items.length) items.push(q != null ? String(typeof q === 'object' ? JSON.stringify(q) : q) : 'Nothing urgent — hold the line.');
        items.slice(0, 5).forEach(function (t, i) {
          var li = el(doc, 'li', 'chronos-directive', (i + 1) + '. ' + t);
          try {
            if (i === 0) {
              li.style.color = 'var(--warn, #f5c042)';
              li.style.fontWeight = '600';
            }
          } catch (_) { /* ignore */ }
          directivesList.appendChild(li);
        });
      } catch (_) { /* mirrors never break clicks */ }
    }

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
      renderHudMirrors(data);
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
          setConfidence('high', 88);
          var summary = briefingSummary(data);
          var body = 'Your briefing for ' + date + ' is ready, sir';
          if (summary) body += ' — ' + summary + ' on the list';
          polishedNotify('Briefing Ready', body + '.');
        },
        function (err) {
          result.textContent = 'Load failed.';
          showBanner('Briefing load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // --- question box ---
    var qCard = polish(el(doc, 'div', 'card chronos-deck chronos-answer-deck'), 'deck');
    qCard.setAttribute('data-deck', 'answer');
    var qTitle = el(doc, 'h3', 'chronos-sub-title', 'Ask a question');
    qCard.appendChild(qTitle);
    var qForm = el(doc, 'form', 'chronos-row row');
    qForm.setAttribute('data-action', 'briefing-question-form');
    var qInput = polish(el(doc, 'input', 'chronos-question-input'), 'field');
    qInput.type = 'text';
    qInput.placeholder = 'e.g. What needs my attention today?';
    qInput.setAttribute('data-action', 'briefing-question');
    try { qInput.style.flex = '1'; qInput.style.minWidth = '12em'; } catch (_) { /* ignore */ }
    var qBtn = polish(el(doc, 'button', 'chronos-btn btn primary', 'Ask'), 'primary');
    qBtn.type = 'submit';
    qBtn.setAttribute('data-action', 'briefing-ask');
    qForm.appendChild(qInput);
    qForm.appendChild(qBtn);
    qCard.appendChild(qForm);
    var qAnswer = polish(el(doc, 'div', 'chronos-question-answer status'), 'answer');
    qAnswer.setAttribute('data-part', 'question-answer');
    qAnswer.setAttribute('role', 'status');
    qAnswer.textContent = 'Answers appear here.';
    qCard.appendChild(qAnswer);
    // Confidence line (styling/DOM only): static-styled meter + label that
    // mirrors answer state; gold complementary accent, no new libs.
    var qConf = el(doc, 'div', 'chronos-answer-confidence');
    qConf.setAttribute('data-part', 'answer-confidence');
    try {
      qConf.style.display = 'flex';
      qConf.style.alignItems = 'center';
      qConf.style.gap = '8px';
      qConf.style.marginTop = '6px';
      qConf.style.fontSize = '12px';
      qConf.style.color = 'var(--muted, #7fa3b8)';
    } catch (_) { /* ignore */ }
    var qConfLabel = el(doc, 'span', 'chronos-confidence-label', 'Confidence: —');
    var qConfBar = el(doc, 'span', 'chronos-confidence-bar');
    qConfBar.setAttribute('aria-hidden', 'true');
    try {
      qConfBar.style.display = 'inline-block';
      qConfBar.style.width = '96px';
      qConfBar.style.height = '6px';
      qConfBar.style.borderRadius = '3px';
      qConfBar.style.background = 'var(--bg-2, #14161a)';
      qConfBar.style.border = '1px solid var(--border, #333945)';
      qConfBar.style.overflow = 'hidden';
    } catch (_) { /* ignore */ }
    var qConfFill = el(doc, 'span', 'chronos-confidence-fill');
    try {
      qConfFill.style.display = 'block';
      qConfFill.style.width = '0%';
      qConfFill.style.height = '100%';
      qConfFill.style.background = 'linear-gradient(90deg, var(--accent, #4f9cf9), var(--warn, #f5c042))';
    } catch (_) { /* ignore */ }
    qConfBar.appendChild(qConfFill);
    qConf.appendChild(qConfLabel);
    qConf.appendChild(qConfBar);
    qCard.appendChild(qConf);
    screen.appendChild(qCard);

    // Presentation-only confidence mirror (no fetch/handler changes).
    function setConfidence(label, pct) {
      try {
        qConfLabel.textContent = 'Confidence: ' + label;
        qConfFill.style.width = String(pct) + '%';
      } catch (_) { /* ignore */ }
    }

    qForm.addEventListener('submit', function (ev) {
      try { ev.preventDefault(); } catch (_) { /* ignore */ }
      hideBanner();
      var text = '';
      try { text = (qInput.value || '').trim(); } catch (_) { text = ''; }
      if (!text) {
        qAnswer.textContent = 'Type a question first.';
        setConfidence('—', 0);
        return;
      }
      qAnswer.textContent = 'Asking…';
      setConfidence('checking…', 35);
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
          setConfidence(String(msg == null || msg === 'OK' ? 'medium' : 'high'), msg === 'OK' || msg == null ? 60 : 88);
          polishedNotify('Briefing Answer', 'At your service, sir — ' + String(msg == null ? 'OK' : msg));
        },
        function (err) {
          qAnswer.textContent = 'Ask failed.';
          setConfidence('low — server unreachable', 12);
          showBanner('Ask failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // Shared AI row in its own themed card at the bottom of the screen
    // (mic/send buttons are styled by the shell theme; the card keeps the
    // row from rendering raw when the palette has not landed).
    var aiCard = polish(el(doc, 'div', 'card chronos-deck'), 'deck');
    aiCard.setAttribute('data-deck', 'ask-chronos');
    aiCard.appendChild(el(doc, 'h3', 'chronos-sub-title', 'Ask Chronos'));
    screen.appendChild(aiCard);

    container.appendChild(screen);

    // Shared AI row at the bottom of the screen (when the inliner provides it).
    var aiRow = mountAiRowIfAvailable(aiCard, ctx);

    // PROACTIVE BRIEFING: one lazy GET /api/briefing?date=today after first
    // paint, ONLY when server URL+key are explicitly configured. Fully
    // guarded (try/catch, silent fail — never banner spam, never blocks
    // boot). On urgency: surface the urgent-briefing card + fire a guarded
    // window.chronos notify (honoring the briefing notification toggle).
    function runProactiveBriefing() {
      var cfg = null;
      try { cfg = configuredServer(); } catch (_) { cfg = null; }
      if (!cfg) return;
      var fetchFn = null;
      try { fetchFn = fetchOf(ctx); } catch (_) { fetchFn = null; }
      if (!fetchFn) return;
      var date = '';
      try { date = todayISO(); } catch (_) { date = ''; }
      if (!date) return;
      var p = null;
      try {
        p = fetchFn(cfg.url + '/api/briefing?date=' + encodeURIComponent(date), {
          method: 'GET',
          headers: { 'X-Chronos-Key': cfg.key },
        });
      } catch (_) {
        return; // silent: a dead server at boot must not spam banners
      }
      Promise.resolve(p).then(
        function (res) {
          if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
          return typeof res.json === 'function' ? res.json() : {};
        }
      ).then(
        function (data) {
          var urgent = false;
          try { urgent = briefingIsUrgent(data); } catch (_) { urgent = false; }
          if (!urgent) return;
          try { renderUrgentBriefing(data, date); } catch (_) { /* ignore */ }
          if (!briefingAlertsEnabled()) return;
          var summary = '';
          try { summary = briefingSummary(data); } catch (_) { summary = ''; }
          var body = 'Sir, ' + date + ' needs your attention';
          if (summary) body += ': ' + summary;
          polishedNotify('Urgent Briefing', body + ' — I have flagged it on your briefing.');
        },
        function () { /* silent fail — no banner spam */ }
      );
    }

    // After first paint only: async + guarded, mount/boot never block.
    try {
      if (typeof setTimeout === 'function') {
        setTimeout(function () {
          try { runProactiveBriefing(); } catch (_) { /* silent */ }
        }, 0);
      }
    } catch (_) { /* ignore */ }

    return {
      screen: screen,
      dateInput: dateInput,
      loadBtn: loadBtn,
      result: result,
      urgentCard: urgentCard,
      runProactiveBriefing: runProactiveBriefing,
      qForm: qForm,
      qInput: qInput,
      qBtn: qBtn,
      qAnswer: qAnswer,
      aiRow: aiRow,
    };
  }

  return { mountBriefing: mountBriefing };
});
