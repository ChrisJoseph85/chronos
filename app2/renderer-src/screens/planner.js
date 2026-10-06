// Chronos app2 — Planner screen (PLANNER-REBUILD owned).
//
// Google-Calendar-style planner. Renders fully offline with empty states;
// every fetch is lazy (inside click/drop handlers) and guarded
// (try/catch -> global banner). Zero network at import or mount time.
//
// Layout (documented choices):
//   - WEEK GRID default: 7 day columns (Mon..Sun) x hourly rows
//     (HOUR_START..HOUR_END, constants at top). Events render as blocks
//     inside their day/hour slot.
//   - TWO INDEPENDENT SCROLL REGIONS: the day/time grid scrolls in its own
//     container (#planner-week-scroll) AND the buckets strip
//     (#planner-buckets) scrolls separately above it.
//   - WEEKLY-BUCKETS SIDEBAR DOCKED RIGHT (#planner-side): vertical bucket
//     list beside the grid (calendar keeps visual priority on the left).
//   - EXPANDED DAY: clicking a day-column header toggles a focused view of
//     that day + the next adjacent day, large, with an agenda list; click
//     the header again (or the X button) to return to the week.
//   - MONTH VIEW + YEAR OVERVIEW: toolbar buttons; month = compact month
//     grid (clicking a day jumps to the week with that day focused);
//     year = 12 mini months (clicking a month opens the month view).
//   - DRAG + DROP: buckets/events are HTML5 draggable; dropping onto a day
//     column hour slot RESCHEDULES via POST /api/commands
//     {tool:'update_event', arguments:{id,start_ms,end_ms}} (the frozen
//     API.md route for moves — no dedicated move tool exists), guarded with
//     optimistic UI update + rollback on failure, and appends a
//     timestamped schedule-event record to ai-context.js so the AI row can
//     include recent schedule changes in its context.
//
// Wired lazily to: GET /api/events?from=ISO&to=ISO (week),
// GET /api/buckets?level=W|D&date= (buckets/day drill),
// GET /api/nodes?parent=&tag= (tree + tags),
// POST /api/commands (reschedule).
//
// Theme: consumes the shell (Jarvis) :root variables, never redefines the
// palette, never uses raw white controls — all controls reuse shell
// classes (.btn/.tag-chip/.card/.status/.cal-*) plus layout-only inline
// styles (no colors/backgrounds inline).
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosPlanner) or required under node --test.
// Exports: { mountPlanner, renderPlanner, renderCalendar, renderNodeTree,
//            renderTagList, collectTags, HOUR_START, HOUR_END,
//            RESCHEDULE_ROUTE, RESCHEDULE_TOOL }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosPlanner = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // ---- planner constants (hour range + reschedule contract) ----
  var HOUR_START = 6; // first hour row (06:00), inclusive
  var HOUR_END = 22; // end of last hour row (22:00), exclusive
  var RESCHEDULE_ROUTE = '/api/commands';
  var RESCHEDULE_TOOL = 'update_event';

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
  var DOWS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var DOWS_MON = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function shell() {
    try {
      if (typeof globalThis !== 'undefined' && globalThis.ChronosShell) {
        return globalThis.ChronosShell;
      }
    } catch (_) { /* ignore */ }
    return null;
  }

  // Guarded call-time read of the shared schedule-context feed
  // (ai-context.js). Null when the module is absent — never throws,
  // never fetches.
  function aiContext() {
    try {
      var g = (typeof globalThis !== 'undefined') ? globalThis.ChronosAiContext : null;
      if (g && typeof g.pushScheduleEvent === 'function') return g;
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
  // Blue default (--accent), gold complementary (--warn, #f5c042), red
  // alerts (--danger). Never redefines the palette; text always
  // var(--text) — never raw white.
  function polish(node, kind) {
    if (!node || !node.style) return node;
    try {
      if (kind === 'primary') {
        node.style.boxShadow = 'var(--btn-glow, 0 0 10px rgba(79,156,249,.35))';
      } else if (kind === 'gold') {
        node.style.borderColor = 'var(--warn, #f5c042)';
        node.style.color = 'var(--warn, #f5c042)';
        node.style.boxShadow = 'var(--glow-sm, 0 0 6px rgba(245,192,66,.55))';
      } else if (kind === 'card') {
        node.style.background = 'var(--panel, #0a1626)';
        node.style.border = '1px solid var(--border, #13415e)';
        node.style.borderRadius = 'var(--radius, 8px)';
        node.style.color = 'var(--text, #e8eaed)';
      }
    } catch (_) { /* styling only — never break clicks */ }
    return node;
  }

  // CYBER-HUD display helpers (styling only — pure local reads, no fetch).
  // Progress % for Knowledge-Node cards: honors node.progress|pct|percent|
  // completion (0..100) or boolean done|completed, else 0.
  function nodePct(node) {
    try {
      var n = node || {};
      var v = n.progress;
      if (v == null) v = n.pct;
      if (v == null) v = n.percent;
      if (v == null) v = n.completion;
      if (v == null) {
        if (n.done === true || n.completed === true) return 100;
        return 0;
      }
      v = Math.round(Number(v));
      if (isNaN(v)) return 0;
      if (v < 0) return 0;
      if (v > 100) return 100;
      return v;
    } catch (_) { return 0; }
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function isoDate(y, m, d) { return y + '-' + pad(m + 1) + '-' + pad(d); }

  function parseISODate(iso) {
    var parts = String(iso || '').split('-');
    return new Date(+parts[0], (+parts[1]) - 1, +parts[2]);
  }

  function addDaysISO(iso, n) {
    var d = parseISODate(iso);
    d.setDate(d.getDate() + n);
    return isoDate(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function mondayOf(d) {
    var back = (d.getDay() + 6) % 7; // Mon..Sun week
    var m = new Date(d.getFullYear(), d.getMonth(), d.getDate() - back);
    return isoDate(m.getFullYear(), m.getMonth(), m.getDate());
  }

  function weekDates(mondayISO) {
    var out = [];
    var i;
    for (i = 0; i < 7; i++) out.push(addDaysISO(mondayISO, i));
    return out;
  }

  function slotLabel(hour) { return pad(hour) + ':00'; }

  function slotRef(dateISO, hour) { return dateISO + ' ' + slotLabel(hour); }

  function slotMs(dateISO, hour) {
    var d = parseISODate(dateISO);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), hour, 0, 0, 0).getTime();
  }

  function showBanner(doc, msg) {
    var sh = shell();
    if (sh) sh.showBanner(doc, msg);
  }

  function lazyGet(doc, path, ctx) {
    var sh = shell();
    if (!sh) return Promise.reject(new Error('shell unavailable'));
    return sh.apiFetch(path, { method: 'GET' }, ctx);
  }

  function lazyPost(doc, path, body, ctx) {
    var sh = shell();
    if (!sh) return Promise.reject(new Error('shell unavailable'));
    return sh.apiFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, ctx);
  }

  function newState() {
    var now = new Date();
    return {
      anchorMonday: mondayOf(now),
      view: 'week', // week | expanded | month | year
      expandedISO: null,
      monthY: now.getFullYear(),
      monthM: now.getMonth(),
      events: [], // {id,title,date,hour,durH}
      buckets: [], // {id,title}
      pendingDrag: null, // {id, kind:'event'|'bucket'} set on dragstart
    };
  }

  // --- server payload mapping (pure local) ---
  function toEvent(raw) {
    var r = raw || {};
    var id = r.id != null ? String(r.id) : '';
    var title = r.title || r.name || id || '(untitled)';
    var date = null;
    var hour = null;
    var ms = null;
    if (r.start_ms != null) ms = +r.start_ms;
    else if (r.start != null) { var t = Date.parse(r.start); if (!isNaN(t)) ms = t; }
    if (ms != null) {
      var d = new Date(ms);
      date = isoDate(d.getFullYear(), d.getMonth(), d.getDate());
      hour = d.getHours();
    } else if (r.date) {
      date = String(r.date).slice(0, 10);
      hour = (r.hour != null) ? +r.hour : null;
    }
    var durH = 1;
    if (r.end_ms != null && ms != null) {
      durH = Math.max(1, Math.round((+r.end_ms - ms) / 3600000));
    } else if (r.durH != null) {
      durH = Math.max(1, +r.durH || 1);
    }
    return { id: id, title: String(title), date: date, hour: hour, durH: durH };
  }

  function toBucket(raw) {
    var r = raw || {};
    var id = r.id != null ? String(r.id) : '';
    return { id: id, title: String(r.title || r.name || id || '(untitled)') };
  }

  // --- node tree / tags (unchanged renderers; data arrives lazily) ---
  function nodeTitle(n) {
    return n.title || n.name || n.id || '(untitled)';
  }

  function renderNodeTree(doc, listEl, nodes) {
    while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
    if (!nodes || !nodes.length) {
      listEl.appendChild(el(doc, 'li', 'empty', 'No nodes loaded yet.'));
      return;
    }
    var byParent = {};
    var ids = {};
    var i;
    for (i = 0; i < nodes.length; i++) {
      var n = nodes[i] || {};
      if (n.id != null) ids[n.id] = true;
    }
    for (i = 0; i < nodes.length; i++) {
      var n2 = nodes[i] || {};
      var p = (n2.parent != null && ids[n2.parent]) ? n2.parent : '__root__';
      if (!byParent[p]) byParent[p] = [];
      byParent[p].push(n2);
    }
    function appendLevel(parentEl, parentKey, depth) {
      var kids = byParent[parentKey] || [];
      var k;
      for (k = 0; k < kids.length; k++) {
        (function (node) {
          // CYBER-HUD Knowledge-Node card (styling only): title/kind/tags
          // rendering is unchanged; a % progress bar is appended.
          var li = el(doc, 'li', 'node-card', null);
          try {
            li.style.marginLeft = (depth * 14) + 'px';
            li.style.background = 'var(--panel, #0a1626)';
            li.style.border = '1px solid var(--border, #13415e)';
            li.style.borderLeft = '3px solid var(--accent, #4f9cf9)';
            li.style.borderRadius = 'var(--radius, 8px)';
            li.style.padding = '8px 10px';
            li.style.listStyle = 'none';
          } catch (_) { /* styling only */ }
          var titleSpan = el(doc, 'span', 'node-title', nodeTitle(node));
          try {
            titleSpan.style.color = 'var(--text, #e8eaed)';
            titleSpan.style.fontWeight = '600';
          } catch (_) { /* styling only */ }
          li.appendChild(titleSpan);
          li.appendChild(el(doc, 'span', 'node-kind', node.kind || 'node'));
          var tags = nodeTags(node);
          if (tags.length) li.appendChild(el(doc, 'span', 'node-tags', tags.join(', ')));
          // Progress bar (display only — pct derived locally, no fetch).
          var pct = nodePct(node);
          var track = el(doc, 'div', 'node-progress', null);
          try {
            track.style.height = '6px';
            track.style.marginTop = '6px';
            track.style.borderRadius = '4px';
            track.style.background = 'var(--panel-2, #23272f)';
            track.style.border = '1px solid var(--border, #333945)';
            track.style.overflow = 'hidden';
          } catch (_) { /* styling only */ }
          var fill = el(doc, 'div', 'node-progress-fill', null);
          try {
            fill.style.height = '100%';
            fill.style.width = pct + '%';
            fill.style.background = 'var(--warn, #f5c042)';
            fill.style.boxShadow = 'var(--glow-sm, 0 0 6px rgba(245,192,66,.55))';
          } catch (_) { /* styling only */ }
          track.appendChild(fill);
          li.appendChild(track);
          var pctLabel = el(doc, 'span', 'node-pct', pct + '%');
          try {
            pctLabel.style.fontSize = '11px';
            pctLabel.style.color = 'var(--muted, #7fa3b8)';
            pctLabel.style.fontFamily = 'var(--mono, monospace)';
          } catch (_) { /* styling only */ }
          li.appendChild(pctLabel);
          parentEl.appendChild(li);
          if (node.id != null) appendLevel(parentEl, node.id, depth + 1);
        })(kids[k]);
      }
    }
    appendLevel(listEl, '__root__', 0);
  }

  function nodeTags(node) {
    if (!node) return [];
    if (Array.isArray(node.tags)) return node.tags.map(String);
    if (typeof node.tags === 'string' && node.tags) return [node.tags];
    if (typeof node.tag === 'string' && node.tag) return [node.tag];
    return [];
  }

  function collectTags(nodes) {
    var seen = {};
    var out = [];
    (nodes || []).forEach(function (n) {
      nodeTags(n).forEach(function (t) {
        if (!seen[t]) { seen[t] = true; out.push(t); }
      });
    });
    return out.sort();
  }

  // CYBER-HUD tag chips with counts (styling only): accepts plain strings
  // (unchanged chips — textContent stays the bare tag so click-through
  // tests hold) or {tag|name, count} objects which render a gold count
  // badge. Counts ride on data-count so shell CSS hooks apply.
  function renderTagList(doc, tagsEl, tags) {
    while (tagsEl.firstChild) tagsEl.removeChild(tagsEl.firstChild);
    if (!tags || !tags.length) {
      tagsEl.appendChild(el(doc, 'span', 'empty', 'No tags loaded yet.'));
      return;
    }
    tags.forEach(function (t) {
      var name = t;
      var count = 0;
      if (t && typeof t === 'object') {
        name = t.tag != null ? t.tag : (t.name != null ? t.name : '');
        count = +(t.count != null ? t.count : 0) || 0;
      }
      name = String(name);
      var chip = el(doc, 'span', 'tag-chip', name);
      try {
        chip.style.borderColor = 'var(--accent, #4f9cf9)';
        chip.style.color = 'var(--accent, #4f9cf9)';
        if (count > 1) {
          chip.setAttribute('data-count', String(count));
          chip.title = name + ' × ' + count;
          var badge = el(doc, 'span', 'tag-count', ' ×' + count);
          badge.style.color = 'var(--warn, #f5c042)';
          badge.style.fontFamily = 'var(--mono, monospace)';
          badge.style.fontSize = '11px';
          badge.style.marginLeft = '4px';
          chip.appendChild(badge);
        }
      } catch (_) { /* styling only */ }
      tagsEl.appendChild(chip);
    });
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

  // --- drag + drop reschedule ---
  function findItem(st, id) {
    var i;
    for (i = 0; i < st.events.length; i++) {
      if (st.events[i].id === id) return { kind: 'event', item: st.events[i] };
    }
    for (i = 0; i < st.buckets.length; i++) {
      if (st.buckets[i].id === id) return { kind: 'bucket', item: st.buckets[i] };
    }
    return null;
  }

  function onDragStart(st, id, kind) {
    return function (ev) {
      st.pendingDrag = { id: id, kind: kind };
      try {
        if (ev && ev.dataTransfer && typeof ev.dataTransfer.setData === 'function') {
          ev.dataTransfer.setData('text/plain', id);
          ev.dataTransfer.effectAllowed = 'move';
        }
      } catch (_) { /* jsdom / guarded — pendingDrag is the fallback */ }
    };
  }

  function readDropId(st, ev) {
    if (st.pendingDrag && st.pendingDrag.id) return st.pendingDrag;
    try {
      if (ev && ev.dataTransfer && typeof ev.dataTransfer.getData === 'function') {
        var id = ev.dataTransfer.getData('text/plain');
        if (id) return { id: String(id), kind: 'event' };
      }
    } catch (_) { /* ignore */ }
    return null;
  }

  // Optimistic move + lazy POST /api/commands update_event + rollback.
  function moveItem(api, dragId, dragKind, targetDate, targetHour) {
    var st = api.st;
    var doc = api.doc;
    var found = findItem(st, dragId);
    if (!found) return;
    var item = found.item;
    var kind = found.kind || dragKind;
    var prev = (kind === 'event')
      ? { date: item.date, hour: item.hour, durH: item.durH }
      : null;
    var fromRef = (kind === 'event' && prev.date != null)
      ? slotRef(prev.date, prev.hour == null ? HOUR_START : prev.hour)
      : 'unscheduled';
    var toRef = slotRef(targetDate, targetHour);

    // Optimistic UI update.
    if (kind === 'event') {
      item.date = targetDate;
      item.hour = targetHour;
    } else {
      var idx = st.buckets.indexOf(item);
      if (idx !== -1) st.buckets.splice(idx, 1);
      st.events.push({ id: item.id, title: item.title, date: targetDate, hour: targetHour, durH: 1 });
    }
    st.pendingDrag = null;
    api.paint();

    var startMs = slotMs(targetDate, targetHour);
    var durH = (kind === 'event' && prev && prev.durH) ? prev.durH : 1;
    var payload = {
      tool: RESCHEDULE_TOOL,
      arguments: { id: dragId, start_ms: startMs, end_ms: startMs + durH * 3600000 },
    };
    var p;
    try {
      p = lazyPost(doc, RESCHEDULE_ROUTE, payload, api.ctx);
    } catch (err) {
      rollbackMove(api, kind, dragId, item, prev);
      showBanner(doc, 'Reschedule failed: ' + (err && err.message ? err.message : err));
      return;
    }
    Promise.resolve(p).then(
      function () {
        try {
          var feed = aiContext();
          if (feed) {
            feed.pushScheduleEvent({
              type: 'reschedule',
              id: dragId,
              title: item.title || dragId,
              from: fromRef,
              to: toRef,
            });
          }
        } catch (_) { /* context feed is best-effort */ }
        var detail = doc.getElementById('planner-day-detail');
        if (detail) detail.textContent = 'Moved ' + (item.title || dragId) + ': ' + fromRef + ' -> ' + toRef + '.';
      },
      function (err) {
        rollbackMove(api, kind, dragId, item, prev);
        showBanner(doc, 'Reschedule failed: ' + (err && err.message ? err.message : err));
      }
    );
  }

  function rollbackMove(api, kind, dragId, item, prev) {
    var st = api.st;
    if (kind === 'event' && prev) {
      item.date = prev.date;
      item.hour = prev.hour;
      item.durH = prev.durH;
    } else if (kind === 'bucket') {
      var i;
      for (i = 0; i < st.events.length; i++) {
        if (st.events[i].id === dragId) { st.events.splice(i, 1); break; }
      }
      var back = true;
      for (i = 0; i < st.buckets.length; i++) {
        if (st.buckets[i].id === dragId) { back = false; break; }
      }
      if (back) st.buckets.push(item);
    }
    api.paint();
  }

  function makeSlot(doc, api, dateISO, hour) {
    var s = el(doc, 'div', 'slot', null);
    s.setAttribute('data-date', dateISO);
    s.setAttribute('data-hour', String(hour));
    s.setAttribute('data-drop', 'slot');
    s.style.minHeight = '26px';
    s.addEventListener('dragover', function (ev) {
      try {
        if (ev) ev.preventDefault();
        if (ev && ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
      } catch (_) { /* ignore */ }
      try { s.style.outline = '1px dashed var(--accent)'; } catch (_) { /* styling only */ }
    });
    s.addEventListener('dragleave', function () {
      try { s.style.outline = ''; } catch (_) { /* styling only */ }
    });
    s.addEventListener('drop', function (ev) {
      try { if (ev) ev.preventDefault(); } catch (_) { /* ignore */ }
      try { s.style.outline = ''; } catch (_) { /* styling only */ }
      var drag = readDropId(api.st, ev);
      if (!drag) return;
      moveItem(api, drag.id, drag.kind, dateISO, hour);
    });
    return s;
  }

  function makeDraggable(doc, api, node, id, kind) {
    try { node.setAttribute('draggable', 'true'); } catch (_) { /* ignore */ }
    node.setAttribute('data-id', id);
    node.addEventListener('dragstart', onDragStart(api.st, id, kind));
    return node;
  }

  function eventsAt(st, dateISO, hour) {
    return st.events.filter(function (e) {
      return e.date === dateISO && +e.hour === +hour;
    });
  }

  function renderEventBlock(doc, api, e) {
    var b = el(doc, 'div', 'tag-chip event-block', e.title + ' ' + slotLabel(e.hour == null ? HOUR_START : e.hour));
    b.setAttribute('data-kind', 'event');
    b.style.display = 'block';
    b.style.margin = '2px 0';
    b.style.cursor = 'move';
    b.title = 'Drag to reschedule';
    return makeDraggable(doc, api, b, e.id, 'event');
  }

  // --- views ---
  function paintWeek(doc, mount, api) {
    var st = api.st;
    mount.innerHTML = '';
    mount.setAttribute('data-view', 'week');
    var dates = weekDates(st.anchorMonday);

    var label = el(doc, 'div', 'cal-label',
      'Week of ' + st.anchorMonday + ' — ' + dates[0] + ' .. ' + dates[6]);
    label.id = 'planner-week-label';
    mount.appendChild(label);

    var scroll = el(doc, 'div', 'week-grid-scroll', null);
    scroll.id = 'planner-week-scroll';
    scroll.style.overflow = 'auto';
    scroll.style.maxHeight = '420px';

    var head = el(doc, 'div', 'week-head', null);
    head.style.display = 'flex';
    var corner = el(doc, 'span', 'week-corner', '');
    corner.style.minWidth = '52px';
    head.appendChild(corner);
    dates.forEach(function (d, i) {
      var h = el(doc, 'button', 'btn ghost day-head', DOWS_MON[i] + ' ' + d.slice(5));
      h.type = 'button';
      h.setAttribute('data-date', d);
      h.style.flex = '1';
      if (st.expandedISO === d) h.setAttribute('aria-pressed', 'true');
      h.addEventListener('click', function () {
        if (st.expandedISO === d && st.view === 'expanded') {
          st.expandedISO = null;
          st.view = 'week';
        } else {
          st.expandedISO = d;
          st.view = 'expanded';
        }
        api.paint();
      });
      head.appendChild(h);
    });
    scroll.appendChild(head);

    var h;
    for (h = HOUR_START; h < HOUR_END; h++) {
      (function (hour) {
        var row = el(doc, 'div', 'week-row', null);
        row.style.display = 'flex';
        var gut = el(doc, 'span', 'week-gutter', slotLabel(hour));
        gut.style.minWidth = '52px';
        row.appendChild(gut);
        dates.forEach(function (d) {
          var slot = makeSlot(doc, api, d, hour);
          slot.style.flex = '1';
          eventsAt(st, d, hour).forEach(function (e) {
            slot.appendChild(renderEventBlock(doc, api, e));
          });
          row.appendChild(slot);
        });
        scroll.appendChild(row);
      })(h);
    }
    mount.appendChild(scroll);

    if (!st.events.length) {
      mount.appendChild(el(doc, 'div', 'empty',
        'No events this week — click Load week, or drag a bucket onto a slot.'));
    }
  }

  function paintExpanded(doc, mount, api) {
    var st = api.st;
    mount.innerHTML = '';
    mount.setAttribute('data-view', 'expanded');
    var focus = st.expandedISO || st.anchorMonday;
    var pair = [focus, addDaysISO(focus, 1)];

    var bar = el(doc, 'div', 'row', null);
    var close = el(doc, 'button', 'btn', 'X Back to week');
    close.type = 'button';
    close.id = 'planner-collapse-day';
    close.setAttribute('aria-label', 'Back to week view');
    close.addEventListener('click', function () {
      st.expandedISO = null;
      st.view = 'week';
      api.paint();
    });
    bar.appendChild(close);
    bar.appendChild(el(doc, 'span', 'cal-label', 'Focused: ' + pair.join(' + ')));
    mount.appendChild(bar);

    var wrap = el(doc, 'div', 'expanded-days', null);
    wrap.id = 'planner-expanded';
    wrap.style.display = 'flex';
    wrap.style.gap = '8px';
    pair.forEach(function (d) {
      var col = el(doc, 'div', 'card expanded-day', null);
      col.setAttribute('data-date', d);
      col.style.flex = '1';
      col.appendChild(el(doc, 'h3', null, d));
      var scroll = el(doc, 'div', 'expanded-scroll', null);
      scroll.style.overflow = 'auto';
      scroll.style.maxHeight = '380px';
      var h;
      for (h = HOUR_START; h < HOUR_END; h++) {
        (function (hour) {
          var line = el(doc, 'div', 'expanded-line', null);
          line.style.display = 'flex';
          line.style.gap = '6px';
          line.appendChild(el(doc, 'span', 'week-gutter', slotLabel(hour)));
          var slot = makeSlot(doc, api, d, hour);
          slot.style.flex = '1';
          eventsAt(st, d, hour).forEach(function (e) {
            slot.appendChild(renderEventBlock(doc, api, e));
          });
          line.appendChild(slot);
          scroll.appendChild(line);
        })(h);
      }
      col.appendChild(scroll);
      var agenda = el(doc, 'ul', 'node-list planner-agenda', null);
      agenda.id = 'planner-agenda-' + d;
      var dayEvents = st.events.filter(function (e) { return e.date === d; });
      if (!dayEvents.length) {
        agenda.appendChild(el(doc, 'li', 'empty', 'No events on ' + d + ' — drag a bucket here.'));
      } else {
        dayEvents.forEach(function (e) {
          agenda.appendChild(el(doc, 'li', null,
            slotLabel(e.hour == null ? HOUR_START : e.hour) + ' ' + e.title));
        });
      }
      col.appendChild(el(doc, 'h3', null, 'Agenda'));
      col.appendChild(agenda);
      wrap.appendChild(col);
    });
    mount.appendChild(wrap);
  }

  function paintMonthGrid(doc, mount, y, m, cbs) {
    mount.innerHTML = '';
    mount.setAttribute('data-view', 'month');
    mount.setAttribute('data-year', String(y));
    mount.setAttribute('data-month', String(m));

    var head = el(doc, 'div', 'cal-head');
    var prev = el(doc, 'button', 'btn', '<');
    prev.type = 'button';
    prev.id = 'cal-prev';
    prev.setAttribute('aria-label', 'Previous month');
    var label = el(doc, 'span', 'cal-label', MONTHS[m] + ' ' + y);
    label.id = 'cal-label';
    var today = el(doc, 'button', 'btn', 'Today');
    today.type = 'button';
    today.id = 'cal-today';
    var next = el(doc, 'button', 'btn', '>');
    next.type = 'button';
    next.id = 'cal-next';
    next.setAttribute('aria-label', 'Next month');
    head.appendChild(prev);
    head.appendChild(label);
    head.appendChild(today);
    head.appendChild(next);
    mount.appendChild(head);

    var grid = el(doc, 'div', 'cal-grid');
    var i;
    for (i = 0; i < 7; i++) grid.appendChild(el(doc, 'span', 'cal-dow', DOWS[i]));
    var first = new Date(y, m, 1).getDay();
    var days = new Date(y, m + 1, 0).getDate();
    for (i = 0; i < first; i++) grid.appendChild(el(doc, 'span', 'cal-day blank', ''));
    for (i = 1; i <= days; i++) {
      (function (day) {
        var b = el(doc, 'button', 'cal-day', String(day));
        b.type = 'button';
        b.setAttribute('data-date', isoDate(y, m, day));
        // CYBER-HUD event-dots hook (class-only): empty flex row inside the
        // day cell; paintMonth() fills dots from local events (no fetch).
        // Button label/count/ids/handlers unchanged.
        var dots = el(doc, 'span', 'event-dots', null);
        try {
          dots.setAttribute('aria-hidden', 'true');
          dots.style.display = 'flex';
          dots.style.gap = '2px';
          dots.style.justifyContent = 'center';
          dots.style.marginTop = '2px';
          dots.style.minHeight = '6px';
        } catch (_) { /* styling only */ }
        b.appendChild(dots);
        b.addEventListener('click', function () { cbs.onDay(isoDate(y, m, day), b); });
        grid.appendChild(b);
      })(i);
    }
    mount.appendChild(grid);

    prev.addEventListener('click', function () { cbs.onPrev(); });
    next.addEventListener('click', function () { cbs.onNext(); });
    today.addEventListener('click', function () { cbs.onToday(); });
  }

  function stepMonth(st, delta) {
    var m = st.monthM + delta;
    var y = st.monthY;
    while (m < 0) { m += 12; y -= 1; }
    while (m > 11) { m -= 12; y += 1; }
    st.monthM = m;
    st.monthY = y;
  }

  function paintMonth(doc, mount, api) {
    var st = api.st;
    paintMonthGrid(doc, mount, st.monthY, st.monthM, {
      onPrev: function () { stepMonth(st, -1); api.paint(); },
      onNext: function () { stepMonth(st, 1); api.paint(); },
      onToday: function () {
        var now = new Date();
        st.monthY = now.getFullYear();
        st.monthM = now.getMonth();
        api.paint();
      },
      // Clicking a day jumps to the week with that day focused/expanded.
      onDay: function (dateISO) {
        st.anchorMonday = mondayOf(parseISODate(dateISO));
        st.expandedISO = dateISO;
        st.view = 'expanded';
        var detail = doc.getElementById('planner-day-detail');
        if (detail) detail.textContent = 'Focused ' + dateISO + '.';
        api.paint();
      },
    });
    // CYBER-HUD event dots (display only — reads local st.events, no fetch):
    // one gold/blue dot per event, capped at 3 per day cell.
    try {
      var counts = {};
      (st.events || []).forEach(function (e) {
        if (e && e.date) counts[e.date] = (counts[e.date] || 0) + 1;
      });
      var cells = mount.querySelectorAll('.cal-day[data-date]');
      var ci;
      for (ci = 0; ci < cells.length; ci++) {
        (function (cell) {
          var n = counts[cell.getAttribute('data-date')] || 0;
          var box = cell.querySelector('.event-dots');
          if (!box || !n) return;
          var shown = Math.min(3, n);
          var di;
          for (di = 0; di < shown; di++) {
            var dot = el(doc, 'span', 'event-dot', null);
            dot.style.display = 'inline-block';
            dot.style.width = '6px';
            dot.style.height = '6px';
            dot.style.borderRadius = '50%';
            dot.style.background = (di === 0)
              ? 'var(--warn, #f5c042)'
              : 'var(--accent, #4f9cf9)';
            dot.style.boxShadow = 'var(--glow-sm, 0 0 6px rgba(245,192,66,.55))';
            box.appendChild(dot);
          }
          cell.title = n + (n === 1 ? ' event' : ' events');
        })(cells[ci]);
      }
    } catch (_) { /* dots are decorative — never break paint */ }
  }

  function paintYear(doc, mount, api) {
    var st = api.st;
    mount.innerHTML = '';
    mount.setAttribute('data-view', 'year');
    var y = st.monthY;
    var head = el(doc, 'div', 'cal-head');
    var prev = el(doc, 'button', 'btn', '<');
    prev.type = 'button';
    prev.id = 'year-prev';
    prev.setAttribute('aria-label', 'Previous year');
    var label = el(doc, 'span', 'cal-label', 'Year ' + y);
    label.id = 'year-label';
    var next = el(doc, 'button', 'btn', '>');
    next.type = 'button';
    next.id = 'year-next';
    next.setAttribute('aria-label', 'Next year');
    head.appendChild(prev);
    head.appendChild(label);
    head.appendChild(next);
    mount.appendChild(head);

    var grid = el(doc, 'div', 'year-grid', null);
    grid.id = 'planner-year-grid';
    for (var m = 0; m < 12; m++) {
      (function (mm) {
        var cell = el(doc, 'div', 'card year-month', null);
        var b = el(doc, 'button', 'btn year-month-btn', MONTHS[mm]);
        b.type = 'button';
        b.setAttribute('data-month', String(mm));
        b.setAttribute('data-year', String(y));
        b.addEventListener('click', function () {
          st.monthM = mm;
          st.view = 'month';
          api.paint();
        });
        cell.appendChild(b);
        cell.appendChild(el(doc, 'div', 'empty',
          String(new Date(y, mm + 1, 0).getDate()) + ' days'));
        grid.appendChild(cell);
      })(m);
    }
    mount.appendChild(grid);

    prev.addEventListener('click', function () { st.monthY = y - 1; api.paint(); });
    next.addEventListener('click', function () { st.monthY = y + 1; api.paint(); });
  }

  // Day drill — lazy GET /api/buckets, guarded (back-compat standalone).
  function onDayClick(doc, mount, btn) {
    var selected = mount.querySelectorAll('.cal-day.selected');
    var i;
    for (i = 0; i < selected.length; i++) selected[i].classList.remove('selected');
    btn.classList.add('selected');
    var date = btn.getAttribute('data-date');
    var detail = doc.getElementById('planner-day-detail');
    if (detail) detail.textContent = 'Loading ' + date + '…';
    lazyGet(doc, '/api/buckets?level=D&date=' + encodeURIComponent(date)).then(
      function (data) {
        var n = Array.isArray(data) ? data.length : 0;
        if (detail) detail.textContent = date + ': ' + n + ' bucket(s).' +
          (Array.isArray(data) && n ? ' ' + data.map(function (b) {
            return b.title || b.name || b.id;
          }).join(', ') : '');
      },
      function (err) {
        if (detail) detail.textContent = 'Could not load ' + date + ' (offline?).';
        showBanner(doc, 'Day load failed: ' + (err && err.message ? err.message : err));
      }
    );
  }

  // Back-compat standalone month calendar (prev/next/today, day drill).
  function renderCalendar(doc, mount, year, month) {
    var ym = { y: year, m: month };
    function draw() {
      paintMonthGrid(doc, mount, ym.y, ym.m, {
        onPrev: function () {
          ym.m -= 1;
          if (ym.m < 0) { ym.m = 11; ym.y -= 1; }
          draw();
        },
        onNext: function () {
          ym.m += 1;
          if (ym.m > 11) { ym.m = 0; ym.y += 1; }
          draw();
        },
        onToday: function () {
          var now = new Date();
          ym.y = now.getFullYear();
          ym.m = now.getMonth();
          draw();
        },
        onDay: function (dateISO, btn) { onDayClick(doc, mount, btn); },
      });
    }
    draw();
  }

  function renderBuckets(doc, api, stripEl, sideEl) {
    var st = api.st;
    [stripEl, sideEl].forEach(function (box) {
      if (!box) return;
      while (box.firstChild) box.removeChild(box.firstChild);
    });
    if (!st.buckets.length) {
      var msg = 'No buckets — click Load buckets.';
      if (stripEl) stripEl.appendChild(el(doc, 'span', 'empty', msg));
      if (sideEl) sideEl.appendChild(el(doc, 'span', 'empty', msg));
      return;
    }
    st.buckets.forEach(function (bk) {
      [[stripEl, 'strip'], [sideEl, 'side']].forEach(function (pair) {
        var box = pair[0];
        if (!box) return;
        // CYBER-HUD Buckets-for-day card (styling only): keeps tag-chip +
        // bucket hooks for drag-drop, adds card surface + gold accent edge.
        var n = el(doc, 'div', 'tag-chip bucket bucket-card', bk.title);
        n.setAttribute('data-kind', 'bucket');
        n.setAttribute('data-loc', pair[1]);
        n.style.cursor = 'move';
        n.title = 'Drag onto a day + hour to schedule';
        try {
          n.style.background = 'var(--panel, #0a1626)';
          n.style.border = '1px solid var(--border, #13415e)';
          n.style.borderLeft = '3px solid var(--warn, #f5c042)';
          n.style.borderRadius = 'var(--radius, 8px)';
          n.style.padding = '6px 10px';
          n.style.color = 'var(--text, #e8eaed)';
          n.style.boxShadow = 'var(--glow-sm, 0 0 6px rgba(245,192,66,.25))';
        } catch (_) { /* styling only */ }
        makeDraggable(doc, api, n, bk.id, 'bucket');
        box.appendChild(n);
      });
    });
  }

  // mountPlanner(container, ctx?) -> handles
  function mountPlanner(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;
    var st = newState();
    var api = {
      st: st,
      doc: doc,
      ctx: ctx,
      paint: null,
      calMount: null,
      stripEl: null,
      sideEl: null,
    };

    var screen = el(doc, 'div', 'screen planner-screen');
    screen.appendChild(el(doc, 'h2', null, 'Planner'));
    screen.appendChild(el(doc, 'p', 'sub', 'Offline — week grid renders locally; events and buckets load on demand.'));

    // CYBER-HUD screen hooks (styling only — no palette redefinition, no
    // fetch, no ids): selected-day glow, event dots, tag-count badges and
    // node progress tracks consume shell vars with local fallbacks.
    try {
      var hudStyle = doc.createElement('style');
      hudStyle.setAttribute('data-planner-hud', 'true');
      hudStyle.textContent =
        '.planner-screen .cal-day.selected{' +
        'border-color:var(--warn, #f5c042) !important;' +
        'box-shadow:var(--glow-md, 0 0 14px rgba(245,192,66,.55)), inset 0 0 12px rgba(245,192,66,.25) !important;' +
        'color:var(--text, #e8eaed);}' +
        '.planner-screen .day-head[aria-pressed="true"]{' +
        'border-color:var(--warn, #f5c042) !important;' +
        'box-shadow:var(--glow-sm, 0 0 6px rgba(245,192,66,.55)) !important;}' +
        '.planner-screen .tag-chip[data-count]::after{' +
        'content:" ×" attr(data-count);' +
        'color:var(--warn, #f5c042);' +
        'font-family:var(--mono, monospace);font-size:11px;margin-left:4px;}' +
        '.planner-screen .event-dot{flex-shrink:0;}';
      screen.appendChild(hudStyle);
    } catch (_) { /* decorative — never break mount */ }

    // Toolbar: week nav + view switches + lazy loaders.
    var toolbar = el(doc, 'div', 'row planner-toolbar', null);
    toolbar.id = 'planner-toolbar';
    function tbButton(id, text, primary) {
      var b = polish(el(doc, 'button', primary ? 'btn primary' : 'btn', text), primary ? 'primary' : null);
      b.type = 'button';
      b.id = id;
      toolbar.appendChild(b);
      return b;
    }
    var todayBtn = tbButton('planner-today', 'Today');
    var prevBtn = tbButton('planner-prev-week', '< Prev week');
    prevBtn.setAttribute('aria-label', 'Previous week');
    var nextBtn = tbButton('planner-next-week', 'Next week >');
    nextBtn.setAttribute('aria-label', 'Next week');
    var monthBtn = tbButton('planner-month-view', 'Month');
    var yearBtn = tbButton('planner-year-view', 'Year');
    var loadWeek = tbButton('planner-load-week', 'Load week', true);
    var loadBuckets = tbButton('planner-load-buckets', 'Load buckets', true);
    screen.appendChild(toolbar);

    // Buckets strip: all-day/unscheduled buckets, own scroll region.
    screen.appendChild(el(doc, 'h3', 'jarvis-title', 'Buckets (drag onto a day + hour)'));
    var strip = el(doc, 'div', 'buckets-strip', null);
    strip.id = 'planner-buckets';
    strip.style.display = 'flex';
    strip.style.gap = '6px';
    strip.style.overflowX = 'auto';
    strip.style.overflowY = 'hidden';
    strip.style.maxWidth = '100%';
    screen.appendChild(strip);

    // Body: calendar surface + weekly-buckets sidebar docked RIGHT.
    var body = el(doc, 'div', 'planner-body', null);
    body.style.display = 'flex';
    body.style.gap = '8px';
    var calMount = el(doc, 'div', 'planner-calendar');
    calMount.id = 'planner-calendar';
    calMount.style.flex = '1';
    calMount.style.minWidth = '0';
    var side = el(doc, 'div', 'card planner-side', null);
    side.id = 'planner-side';
    side.style.width = '220px';
    side.style.flexShrink = '0';
    side.appendChild(el(doc, 'h3', null, "This week's buckets"));
    var sideList = el(doc, 'div', 'planner-side-buckets', null);
    sideList.id = 'planner-side-buckets';
    sideList.style.overflowY = 'auto';
    sideList.style.maxHeight = '420px';
    side.appendChild(sideList);
    side.appendChild(el(doc, 'div', 'empty', 'Drag a bucket onto the grid to schedule it.'));
    body.appendChild(calMount);
    body.appendChild(side);
    screen.appendChild(body);

    var dayDetail = el(doc, 'div', 'status');
    dayDetail.id = 'planner-day-detail';
    dayDetail.textContent = 'Pick a day to load its buckets.';
    screen.appendChild(dayDetail);

    // Nodes + tags cards (legacy contract: shell + integrator tests).
    var lists = el(doc, 'div', 'split', null);
    var nodeCard = el(doc, 'div', 'card');
    nodeCard.appendChild(el(doc, 'h3', null, 'Nodes'));
    var nodeRow = el(doc, 'div', 'row');
    var loadNodes = polish(el(doc, 'button', 'btn primary', 'Load nodes'), 'primary');
    loadNodes.type = 'button';
    loadNodes.id = 'planner-load-nodes';
    nodeRow.appendChild(loadNodes);
    nodeCard.appendChild(nodeRow);
    var nodeList = el(doc, 'ul', 'node-list');
    nodeList.id = 'planner-node-list';
    nodeCard.appendChild(nodeList);
    lists.appendChild(nodeCard);

    var tagCard = el(doc, 'div', 'card');
    tagCard.appendChild(el(doc, 'h3', null, 'Tags'));
    var tagRow = el(doc, 'div', 'row');
    var loadTags = polish(el(doc, 'button', 'btn primary', 'Load tags'), 'primary');
    loadTags.type = 'button';
    loadTags.id = 'planner-load-tags';
    tagRow.appendChild(loadTags);
    tagCard.appendChild(tagRow);
    var tagList = el(doc, 'div', 'tag-list');
    tagList.id = 'planner-tag-list';
    tagCard.appendChild(tagList);
    lists.appendChild(tagCard);
    screen.appendChild(lists);

    container.appendChild(screen);

    api.calMount = calMount;
    api.stripEl = strip;
    api.sideEl = sideList;
    api.paint = function () {
      if (st.view === 'expanded') paintExpanded(doc, calMount, api);
      else if (st.view === 'month') paintMonth(doc, calMount, api);
      else if (st.view === 'year') paintYear(doc, calMount, api);
      else paintWeek(doc, calMount, api);
      renderBuckets(doc, api, strip, sideList);
    };

    // Offline first paint: week grid + empty states, zero network.
    api.paint();
    renderNodeTree(doc, nodeList, []);
    renderTagList(doc, tagList, []);

    todayBtn.addEventListener('click', function () {
      var now = new Date();
      st.anchorMonday = mondayOf(now);
      st.monthY = now.getFullYear();
      st.monthM = now.getMonth();
      st.expandedISO = null;
      st.view = 'week';
      api.paint();
    });
    prevBtn.addEventListener('click', function () {
      st.anchorMonday = addDaysISO(st.anchorMonday, -7);
      st.expandedISO = null;
      if (st.view === 'expanded') st.view = 'week';
      api.paint();
    });
    nextBtn.addEventListener('click', function () {
      st.anchorMonday = addDaysISO(st.anchorMonday, 7);
      st.expandedISO = null;
      if (st.view === 'expanded') st.view = 'week';
      api.paint();
    });
    monthBtn.addEventListener('click', function () {
      if (st.view === 'month') {
        st.view = st.expandedISO ? 'expanded' : 'week';
      } else {
        var d = parseISODate(st.expandedISO || st.anchorMonday);
        st.monthY = d.getFullYear();
        st.monthM = d.getMonth();
        st.view = 'month';
      }
      api.paint();
    });
    yearBtn.addEventListener('click', function () {
      if (st.view === 'year') {
        st.view = st.expandedISO ? 'expanded' : 'week';
      } else {
        st.view = 'year';
      }
      api.paint();
    });

    loadWeek.addEventListener('click', function () {
      loadWeek.disabled = true;
      var dates = weekDates(st.anchorMonday);
      var path = '/api/events?from=' + encodeURIComponent(dates[0] + 'T00:00:00') +
        '&to=' + encodeURIComponent(addDaysISO(dates[6], 1) + 'T00:00:00');
      lazyGet(doc, path, ctx).then(
        function (data) {
          loadWeek.disabled = false;
          var list = Array.isArray(data) ? data : [];
          st.events = list.map(toEvent).filter(function (e) { return e.date && e.hour != null; });
          dayDetail.textContent = 'Week ' + st.anchorMonday + ': ' + st.events.length + ' event(s).';
          api.paint();
        },
        function (err) {
          loadWeek.disabled = false;
          showBanner(doc, 'Week load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    loadBuckets.addEventListener('click', function () {
      loadBuckets.disabled = true;
      lazyGet(doc, '/api/buckets?level=W&date=' + encodeURIComponent(st.anchorMonday), ctx).then(
        function (data) {
          loadBuckets.disabled = false;
          var list = Array.isArray(data) ? data : [];
          st.buckets = list.map(toBucket);
          dayDetail.textContent = 'Week ' + st.anchorMonday + ': ' + st.buckets.length + ' bucket(s). Drag one onto the grid.';
          api.paint();
        },
        function (err) {
          loadBuckets.disabled = false;
          showBanner(doc, 'Buckets load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    loadNodes.addEventListener('click', function () {
      loadNodes.disabled = true;
      lazyGet(doc, '/api/nodes', ctx).then(
        function (data) {
          loadNodes.disabled = false;
          renderNodeTree(doc, nodeList, Array.isArray(data) ? data : []);
        },
        function (err) {
          loadNodes.disabled = false;
          showBanner(doc, 'Nodes load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    loadTags.addEventListener('click', function () {
      loadTags.disabled = true;
      // No dedicated tags route — tags derive from nodes.
      lazyGet(doc, '/api/nodes', ctx).then(
        function (data) {
          loadTags.disabled = false;
          renderTagList(doc, tagList, collectTags(Array.isArray(data) ? data : []));
        },
        function (err) {
          loadTags.disabled = false;
          showBanner(doc, 'Tags load failed: ' + (err && err.message ? err.message : err));
        }
      );
    });

    return {
      screen: screen,
      calendar: calMount,
      state: st,
      toolbar: toolbar,
      bucketsStrip: strip,
      side: side,
      loadWeek: loadWeek,
      loadBuckets: loadBuckets,
      loadNodes: loadNodes,
      nodeList: nodeList,
      loadTags: loadTags,
      tagList: tagList,
      dayDetail: dayDetail,
      aiRow: mountAiRowIfAvailable(screen, ctx),
    };
  }

  // Back-compat alias used by the bundle boot + tests.
  function renderPlanner(container, ctx) { return mountPlanner(container, ctx); }

  return {
    HOUR_START: HOUR_START,
    HOUR_END: HOUR_END,
    RESCHEDULE_ROUTE: RESCHEDULE_ROUTE,
    RESCHEDULE_TOOL: RESCHEDULE_TOOL,
    mountPlanner: mountPlanner,
    renderPlanner: renderPlanner,
    renderCalendar: renderCalendar,
    renderNodeTree: renderNodeTree,
    renderTagList: renderTagList,
    collectTags: collectTags,
  };
});
