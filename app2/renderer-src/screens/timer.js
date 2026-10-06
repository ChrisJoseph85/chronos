// Chronos app2 — Timer+Log screen (UI-A owned).
//
// 3 modes (stopwatch/pomodoro/countdown), strict toggle, breakdown drill.
// Renders fully offline with empty states; every fetch is lazy (inside
// click handlers) and guarded (try/catch -> global banner). No network at
// import or mount time.
//
// Wired lazily to: POST /api/timer/start, POST /api/timer/stop
// (incl. v1.2 `void` flag), GET /api/timer/summary,
// GET /api/stats/breakdown (drill), GET /api/timer/presets,
// POST /api/timer/presets.
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosTimer) or required under node --test.
// Exports: { mountTimer(container, ctx?), renderTimer, MODES }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosTimer = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MODES = ['stopwatch', 'pomodoro', 'countdown'];
  var STRICT_KEY = 'chronos.timer.strict';

  function shell() {
    try {
      if (typeof globalThis !== 'undefined' && globalThis.ChronosShell) {
        return globalThis.ChronosShell;
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
  // as raw white when the theme palette has not landed. Blue default
  // (--accent), gold complementary (--warn, #f5c042), red alerts
  // (--danger). Palette is never redefined; text is always var(--text).
  function polish(node, kind) {
    if (!node || !node.style) return node;
    try {
      if (kind === 'primary') {
        node.style.boxShadow = 'var(--btn-glow, 0 0 10px rgba(79,156,249,.35))';
      } else if (kind === 'gold') {
        node.style.borderColor = 'var(--warn, #f5c042)';
        node.style.color = 'var(--warn, #f5c042)';
        node.style.boxShadow = 'var(--glow-md, 0 0 14px rgba(245,192,66,.55))';
      } else if (kind === 'field') {
        node.style.background = 'var(--bg, #14161a)';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.color = 'var(--text, #e8eaed)';
        node.style.padding = '7px 9px';
        node.style.fontSize = '13px';
      } else if (kind === 'pill') {
        node.style.display = 'inline-flex';
        node.style.alignItems = 'center';
        node.style.gap = '8px';
        node.style.background = 'var(--panel-2, #23272f)';
        node.style.border = '1px solid var(--border, #333945)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.padding = '6px 10px';
        node.style.margin = '8px 0';
        node.style.color = 'var(--text, #e8eaed)';
      } else if (kind === 'check') {
        node.style.accentColor = 'var(--accent, #4f9cf9)';
        node.style.width = '16px';
        node.style.height = '16px';
      }
    } catch (_) { /* styling only — never break clicks */ }
    return node;
  }

  function showBanner(doc, msg) {
    var sh = shell();
    if (sh) sh.showBanner(doc, msg);
  }

  function api(doc, path, opts, ctx) {
    var sh = shell();
    if (!sh) return Promise.reject(new Error('shell unavailable'));
    return sh.apiFetch(path, opts, ctx);
  }

  function postJson(doc, path, body, ctx) {
    return api(doc, path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, ctx);
  }

  function fmtMs(ms) {
    ms = Math.max(0, Math.round(ms || 0));
    var s = Math.floor(ms / 1000);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var r = s % 60;
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return h + ':' + p(m) + ':' + p(r);
  }

  // Shared AI row (UI-B component) when the bundle provides it.
  // Call-time lookup only — never throws, never fetches.
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

  // mountTimer(container, ctx?) -> handles
  function mountTimer(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;
    var sh = shell();

    var screen = el(doc, 'div', 'screen timer-screen');
    screen.appendChild(el(doc, 'h2', null, 'Timer + Log'));
    screen.appendChild(el(doc, 'p', 'sub', 'Offline — sessions start only when you press Start.'));

    // --- modes ---
    var modeCard = el(doc, 'div', 'card');
    modeCard.appendChild(el(doc, 'h3', null, 'Mode'));
    var modeGroup = el(doc, 'div', 'mode-group');
    modeGroup.setAttribute('role', 'group');
    modeGroup.setAttribute('aria-label', 'Timer mode');
    var modeBtns = {};
    MODES.forEach(function (mode) {
      var b = el(doc, 'button', 'btn', mode.charAt(0).toUpperCase() + mode.slice(1));
      b.type = 'button';
      b.id = 'timer-mode-' + mode;
      b.setAttribute('aria-pressed', mode === 'stopwatch' ? 'true' : 'false');
      b.addEventListener('click', function () { setMode(mode); });
      modeGroup.appendChild(b);
      modeBtns[mode] = b;
    });
    modeCard.appendChild(modeGroup);
    screen.setAttribute('data-mode', 'stopwatch');
    function currentMode() { return screen.getAttribute('data-mode') || 'stopwatch'; }
    function setMode(mode) {
      screen.setAttribute('data-mode', mode);
      MODES.forEach(function (m) {
        modeBtns[m].setAttribute('aria-pressed', m === mode ? 'true' : 'false');
      });
    }
    var strictLabel = polish(el(doc, 'label', 'check', null), 'pill');
    var strict = polish(doc.createElement('input'), 'check');
    strict.type = 'checkbox';
    strict.id = 'timer-strict';
    try {
      strict.checked = sh ? sh.storeGet(STRICT_KEY, '0') === '1' : false;
    } catch (_) { strict.checked = false; }
    strictLabel.appendChild(strict);
    strictLabel.appendChild(doc.createTextNode('Strict mode (label required to start)'));
    modeCard.appendChild(strictLabel);
    strict.addEventListener('change', function () {
      if (sh) sh.storeSet(STRICT_KEY, strict.checked ? '1' : '0');
    });
    screen.appendChild(modeCard);

    // --- session controls ---
    // CYBER-HUD: giant gold mono readout in a glowing ring, Start/Pause/
    // Commit trio (gold primary), static hotkey hints. Ids, fetch routes
    // and handlers below are unchanged.
    var sessCard = el(doc, 'div', 'card timer-session');
    sessCard.appendChild(el(doc, 'h3', null, 'Session'));
    var ring = el(doc, 'div', 'timer-ring', null);
    try {
      ring.style.display = 'flex';
      ring.style.alignItems = 'center';
      ring.style.justifyContent = 'center';
      ring.style.padding = '14px';
      ring.style.margin = '8px 0';
      ring.style.borderRadius = '50%';
      ring.style.width = '220px';
      ring.style.height = '220px';
      ring.style.marginLeft = 'auto';
      ring.style.marginRight = 'auto';
      ring.style.border = '2px solid var(--warn, #f5c042)';
      ring.style.background = 'radial-gradient(circle at 50% 50%, var(--panel-2, #23272f) 55%, transparent 72%)';
      ring.style.boxShadow = 'var(--glow-md, 0 0 14px rgba(245,192,66,.55)), inset 0 0 24px rgba(245,192,66,.18)';
    } catch (_) { /* styling only */ }
    var readout = el(doc, 'div', 'timer-readout', '0:00:00');
    readout.id = 'timer-readout';
    readout.setAttribute('role', 'timer');
    readout.setAttribute('aria-label', 'Elapsed time');
    try {
      readout.style.fontFamily = 'var(--mono, monospace)';
      readout.style.fontSize = '44px';
      readout.style.fontWeight = '700';
      readout.style.letterSpacing = '0.04em';
      readout.style.color = 'var(--warn, #f5c042)';
      readout.style.textShadow = '0 0 12px rgba(245,192,66,.65), 0 0 34px rgba(245,192,66,.30)';
      readout.style.textAlign = 'center';
    } catch (_) { /* styling only */ }
    ring.appendChild(readout);
    sessCard.appendChild(ring);
    var sessRow = el(doc, 'div', 'row timer-trio');
    var labelInput = polish(doc.createElement('input'), 'field');
    labelInput.type = 'text';
    labelInput.id = 'timer-label';
    labelInput.placeholder = 'Label (e.g. deep work)';
    var targetInput = polish(doc.createElement('input'), 'field');
    targetInput.type = 'number';
    targetInput.id = 'timer-target-minutes';
    targetInput.min = '1';
    targetInput.placeholder = 'Target min (countdown)';
    targetInput.style.width = '12em';
    var startBtn = polish(el(doc, 'button', 'btn primary timer-start', 'Start'), 'primary');
    startBtn.type = 'button';
    startBtn.id = 'timer-start';
    try {
      startBtn.style.borderColor = 'var(--warn, #f5c042)';
      startBtn.style.color = 'var(--warn, #f5c042)';
    } catch (_) { /* styling only */ }
    // Trio visual: Pause is a static disabled affordance (no fetch, no
    // handler) so the Start/Pause/Commit row renders without new logic.
    var pauseBtn = el(doc, 'button', 'btn timer-pause', 'Pause');
    pauseBtn.type = 'button';
    pauseBtn.disabled = true;
    pauseBtn.title = 'Pause (Space) — resumes on Start';
    var stopBtn = el(doc, 'button', 'btn timer-commit', 'Stop');
    stopBtn.type = 'button';
    stopBtn.id = 'timer-stop';
    try {
      stopBtn.style.borderColor = 'var(--danger, #ff5252)';
      stopBtn.style.color = 'var(--danger, #ff5252)';
    } catch (_) { /* styling only */ }
    var voidLabel = polish(el(doc, 'label', 'check', null), 'pill');
    var voidBox = polish(doc.createElement('input'), 'check');
    voidBox.type = 'checkbox';
    voidBox.id = 'timer-void';
    voidLabel.appendChild(voidBox);
    voidLabel.appendChild(doc.createTextNode('Void on stop (discard time)'));
    sessRow.appendChild(labelInput);
    sessRow.appendChild(targetInput);
    sessRow.appendChild(startBtn);
    sessRow.appendChild(pauseBtn);
    sessRow.appendChild(stopBtn);
    sessRow.appendChild(voidLabel);
    sessCard.appendChild(sessRow);
    var status = el(doc, 'div', 'status', 'Idle — no session loaded.');
    status.id = 'timer-status';
    status.setAttribute('role', 'status');
    sessCard.appendChild(status);
    // Static hotkey hints (no handler — display only).
    var hotkeys = el(doc, 'div', 'hotkey-hints',
      'Hotkeys: Space Start/Pause · S Stop/Commit · L Load summary');
    try {
      hotkeys.style.fontFamily = 'var(--mono, monospace)';
      hotkeys.style.fontSize = '12px';
      hotkeys.style.color = 'var(--muted, #7fa3b8)';
      hotkeys.style.padding = '4px 2px';
    } catch (_) { /* styling only */ }
    sessCard.appendChild(hotkeys);
    screen.appendChild(sessCard);

    startBtn.addEventListener('click', function () {
      var mode = currentMode();
      var label = '';
      try { label = (labelInput.value || '').trim(); } catch (_) { label = ''; }
      if (strict.checked && !label) {
        showBanner(doc, 'Strict mode: enter a label before starting.');
        return;
      }
      var body = { label: label || mode, mode: mode, source: 'desktop' };
      if (mode === 'countdown') {
        var mins = parseFloat(targetInput.value);
        if (mins > 0) body.target_ms = Math.round(mins * 60000);
        else if (strict.checked) {
          showBanner(doc, 'Strict mode: set a target in minutes for countdown.');
          return;
        }
      }
      startBtn.disabled = true;
      postJson(doc, '/api/timer/start', body, ctx).then(
        function (data) {
          startBtn.disabled = false;
          status.textContent = 'Running: ' + ((data && (data.label || data.mode)) || mode) + '.';
          try { readout.textContent = '0:00:00'; } catch (_) { /* display only */ }
          if (sh) sh.notify('Chronos timer', 'Timer started (' + mode + ').');
        },
        function (err) {
          startBtn.disabled = false;
          showBanner(doc, 'Timer start failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    stopBtn.addEventListener('click', function () {
      stopBtn.disabled = true;
      postJson(doc, '/api/timer/stop', { source: 'desktop', void: !!voidBox.checked }, ctx).then(
        function (data) {
          stopBtn.disabled = false;
          var extra = data && data.voided ? ' (voided — time discarded).' : '.';
          status.textContent = 'Stopped' + extra;
          // Commit the final time to the gold readout when reported
          // (display only — status text and notify paths unchanged).
          try {
            var finalMs = data && (data.elapsed_ms != null ? data.elapsed_ms :
              (data.total_ms != null ? data.total_ms : data.duration_ms));
            if (finalMs != null) readout.textContent = fmtMs(finalMs);
          } catch (_) { /* display only */ }
          if (sh) sh.notify('Chronos timer', 'Timer stopped' + extra);
        },
        function (err) {
          stopBtn.disabled = false;
          showBanner(doc, 'Timer stop failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // --- summary ---
    var sumCard = el(doc, 'div', 'card');
    sumCard.appendChild(el(doc, 'h3', null, 'Summary'));
    var sumRow = el(doc, 'div', 'row');
    var sumBtn = el(doc, 'button', 'btn', 'Load summary');
    sumBtn.type = 'button';
    sumBtn.id = 'timer-summary-load';
    sumRow.appendChild(sumBtn);
    sumCard.appendChild(sumRow);
    var summary = el(doc, 'div', 'summary status');
    summary.id = 'timer-summary';
    summary.textContent = 'No summary loaded.';
    sumCard.appendChild(summary);
    screen.appendChild(sumCard);

    function kvRow(name, value) {
      var d = el(doc, 'div', 'kv', null);
      d.appendChild(el(doc, 'span', null, name));
      var v = el(doc, 'span', null, value);
      try {
        v.style.color = 'var(--warn, #f5c042)';
        v.style.fontFamily = 'var(--mono, monospace)';
      } catch (_) { /* styling only */ }
      d.appendChild(v);
      return d;
    }

    sumBtn.addEventListener('click', function () {
      sumBtn.disabled = true;
      var nodeId = '';
      try { nodeId = (nodeInput.value || '').trim(); } catch (_) { nodeId = ''; }
      var path = '/api/timer/summary' + (nodeId ? '?node_id=' + encodeURIComponent(nodeId) : '');
      api(doc, path, { method: 'GET' }, ctx).then(
        function (data) {
          sumBtn.disabled = false;
          while (summary.firstChild) summary.removeChild(summary.firstChild);
          data = data || {};
          summary.appendChild(kvRow('Node total', fmtMs(data.node_total_ms)));
          summary.appendChild(kvRow('Descendants', fmtMs(data.descendant_total_ms)));
          summary.appendChild(kvRow('Project', fmtMs(data.project_total_ms)));
        },
        function (err) {
          sumBtn.disabled = false;
          showBanner(doc, 'Summary load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // --- breakdown drill ---
    var bdCard = el(doc, 'div', 'card');
    bdCard.appendChild(el(doc, 'h3', null, 'Breakdown drill'));
    var bdRow = el(doc, 'div', 'row');
    var nodeInput = polish(doc.createElement('input'), 'field');
    nodeInput.type = 'text';
    nodeInput.id = 'breakdown-node';
    nodeInput.placeholder = 'Node id';
    var fromInput = polish(doc.createElement('input'), 'field');
    fromInput.type = 'date';
    fromInput.id = 'breakdown-from';
    var toInput = polish(doc.createElement('input'), 'field');
    toInput.type = 'date';
    toInput.id = 'breakdown-to';
    var drillBtn = el(doc, 'button', 'btn', 'Drill down');
    drillBtn.type = 'button';
    drillBtn.id = 'breakdown-drill';
    bdRow.appendChild(nodeInput);
    bdRow.appendChild(fromInput);
    bdRow.appendChild(toInput);
    bdRow.appendChild(drillBtn);
    bdCard.appendChild(bdRow);
    var bdResult = el(doc, 'div', 'breakdown-result status');
    bdResult.id = 'breakdown-result';
    bdResult.textContent = 'No breakdown loaded.';
    bdCard.appendChild(bdResult);
    screen.appendChild(bdCard);

    drillBtn.addEventListener('click', function () {
      drillBtn.disabled = true;
      var nid = '';
      var from = '';
      var to = '';
      try {
        nid = (nodeInput.value || '').trim();
        from = fromInput.value || '';
        to = toInput.value || '';
      } catch (_) { /* ignore */ }
      if (!nid || !from || !to) {
        drillBtn.disabled = false;
        showBanner(doc, 'Breakdown drill needs node id, from and to dates.');
        return;
      }
      var path = '/api/stats/breakdown?node_id=' + encodeURIComponent(nid) +
        '&from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to);
      api(doc, path, { method: 'GET' }, ctx).then(
        function (data) {
          drillBtn.disabled = false;
          while (bdResult.firstChild) bdResult.removeChild(bdResult.firstChild);
          var rows = Array.isArray(data) ? data : [];
          if (!rows.length) {
            bdResult.textContent = 'Empty breakdown for this window.';
            return;
          }
          var table = doc.createElement('table');
          table.className = 'data log-table';
          try {
            table.style.border = '1px solid var(--border, #13415e)';
            table.style.borderRadius = 'var(--radius, 8px)';
          } catch (_) { /* styling only */ }
          var thead = doc.createElement('thead');
          var hr = doc.createElement('tr');
          ['Child', 'Kind', 'Total'].forEach(function (h) {
            var th = doc.createElement('th');
            th.textContent = h;
            hr.appendChild(th);
          });
          thead.appendChild(hr);
          table.appendChild(thead);
          var tbody = doc.createElement('tbody');
          rows.forEach(function (r, rIdx) {
            var tr = doc.createElement('tr');
            tr.className = 'log-row';
            try {
              tr.style.background = (rIdx % 2)
                ? 'var(--panel-2, #23272f)'
                : 'transparent';
            } catch (_) { /* styling only */ }
            var tdT = doc.createElement('td');
            tdT.textContent = r.title || r.node_id || '';
            var tdK = doc.createElement('td');
            tdK.textContent = r.kind || '';
            var tdM = doc.createElement('td');
            tdM.textContent = fmtMs(r.total_ms);
            try {
              tdM.style.color = 'var(--warn, #f5c042)';
              tdM.style.fontFamily = 'var(--mono, monospace)';
            } catch (_) { /* styling only */ }
            tr.appendChild(tdT);
            tr.appendChild(tdK);
            tr.appendChild(tdM);
            tbody.appendChild(tr);
          });
          table.appendChild(tbody);
          bdResult.appendChild(table);
        },
        function (err) {
          drillBtn.disabled = false;
          showBanner(doc, 'Breakdown drill failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    // --- presets ---
    var preCard = el(doc, 'div', 'card');
    preCard.appendChild(el(doc, 'h3', null, 'Presets'));
    var preRow = el(doc, 'div', 'row');
    var preLoad = el(doc, 'button', 'btn', 'Load presets');
    preLoad.type = 'button';
    preLoad.id = 'presets-load';
    preRow.appendChild(preLoad);
    preCard.appendChild(preRow);
    var preList = el(doc, 'ul', 'node-list');
    preList.id = 'presets-list';
    preCard.appendChild(preList);
    var preForm = el(doc, 'div', 'row');
    var preName = polish(doc.createElement('input'), 'field');
    preName.type = 'text';
    preName.id = 'preset-name';
    preName.placeholder = 'Name';
    var preFocus = polish(doc.createElement('input'), 'field');
    preFocus.type = 'number';
    preFocus.id = 'preset-focus';
    preFocus.min = '1';
    preFocus.placeholder = 'Focus min';
    var preBreak = polish(doc.createElement('input'), 'field');
    preBreak.type = 'number';
    preBreak.id = 'preset-break';
    preBreak.min = '0';
    preBreak.placeholder = 'Break min';
    var preCycles = polish(doc.createElement('input'), 'field');
    preCycles.type = 'number';
    preCycles.id = 'preset-cycles';
    preCycles.min = '1';
    preCycles.placeholder = 'Cycles';
    var preAdd = polish(el(doc, 'button', 'btn primary', 'Add preset'), 'primary');
    preAdd.type = 'button';
    preAdd.id = 'preset-add';
    preForm.appendChild(preName);
    preForm.appendChild(preFocus);
    preForm.appendChild(preBreak);
    preForm.appendChild(preCycles);
    preForm.appendChild(preAdd);
    preCard.appendChild(preForm);
    screen.appendChild(preCard);

    function renderPresets(list) {
      while (preList.firstChild) preList.removeChild(preList.firstChild);
      if (!list || !list.length) {
        preList.appendChild(el(doc, 'li', 'empty', 'No presets loaded yet.'));
        return;
      }
      // CYBER-HUD themed preset rows (styling only — labels unchanged).
      list.forEach(function (p, idx) {
        var li = el(doc, 'li', 'preset-card',
          (p.name || 'preset') + ' — ' + p.focus_minutes + '/' + p.break_minutes + ' x' + (p.cycles == null ? '?' : p.cycles));
        try {
          li.style.background = (idx % 2)
            ? 'var(--panel-2, #23272f)'
            : 'var(--panel, #0a1626)';
          li.style.border = '1px solid var(--border, #13415e)';
          li.style.borderLeft = '3px solid var(--warn, #f5c042)';
          li.style.borderRadius = 'var(--radius, 8px)';
          li.style.padding = '6px 10px';
          li.style.margin = '4px 0';
          li.style.color = 'var(--text, #e8eaed)';
          li.style.fontFamily = 'var(--mono, monospace)';
          li.style.listStyle = 'none';
        } catch (_) { /* styling only */ }
        preList.appendChild(li);
      });
    }
    renderPresets([]);

    preLoad.addEventListener('click', function () {
      preLoad.disabled = true;
      api(doc, '/api/timer/presets', { method: 'GET' }, ctx).then(
        function (data) {
          preLoad.disabled = false;
          renderPresets(Array.isArray(data) ? data : []);
        },
        function (err) {
          preLoad.disabled = false;
          showBanner(doc, 'Presets load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    preAdd.addEventListener('click', function () {
      var body = {};
      try {
        body = {
          name: (preName.value || '').trim(),
          focus_minutes: parseInt(preFocus.value, 10),
          break_minutes: parseInt(preBreak.value, 10),
          cycles: parseInt(preCycles.value, 10),
        };
      } catch (_) { /* ignore */ }
      if (!body.name || !(body.focus_minutes > 0)) {
        showBanner(doc, 'Preset needs a name and focus minutes.');
        return;
      }
      preAdd.disabled = true;
      postJson(doc, '/api/timer/presets', body, ctx).then(
        function (data) {
          preAdd.disabled = false;
          renderPresets(data && data.presets ? data.presets : (Array.isArray(data) ? data : [data]));
        },
        function (err) {
          preAdd.disabled = false;
          showBanner(doc, 'Preset add failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    container.appendChild(screen);

    return {
      screen: screen,
      modeBtns: modeBtns,
      setMode: setMode,
      currentMode: currentMode,
      strict: strict,
      startBtn: startBtn,
      stopBtn: stopBtn,
      status: status,
      summaryBtn: sumBtn,
      summary: summary,
      drillBtn: drillBtn,
      breakdownResult: bdResult,
      presetsLoad: preLoad,
      presetsList: preList,
      presetAdd: preAdd,
      aiRow: mountAiRowIfAvailable(screen, ctx),
    };
  }

  // Back-compat alias used by the bundle boot + tests.
  function renderTimer(container, ctx) { return mountTimer(container, ctx); }

  return {
    mountTimer: mountTimer,
    renderTimer: renderTimer,
    MODES: MODES,
  };
});
