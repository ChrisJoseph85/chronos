// Chronos app2 — Planner screen (UI-A owned).
//
// Calendar + node tree + tags. Renders fully offline with empty states;
// every fetch is lazy (inside click handlers) and guarded
// (try/catch -> global banner). No network at import or mount time.
//
// Wired lazily to: GET /api/nodes?parent=&tag= (tree + tags),
// GET /api/buckets?level=D&date= (day drill).
//
// UMD-lite: concatenated into the renderer bundle
// (globalThis.ChronosPlanner) or required under node --test.
// Exports: { mountPlanner(container, ctx?), renderCalendar,
//            renderNodeTree, renderTagList, collectTags }
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosPlanner = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
  var DOWS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

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

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function isoDate(y, m, d) { return y + '-' + pad(m + 1) + '-' + pad(d); }

  function showBanner(doc, msg) {
    var sh = shell();
    if (sh) sh.showBanner(doc, msg);
  }

  function lazyGet(doc, path, ctx) {
    var sh = shell();
    if (!sh) return Promise.reject(new Error('shell unavailable'));
    return sh.apiFetch(path, { method: 'GET' }, ctx);
  }

  // --- calendar (pure local, no network) ---
  function renderCalendar(doc, mount, year, month) {
    mount.innerHTML = '';
    mount.setAttribute('data-year', String(year));
    mount.setAttribute('data-month', String(month));

    var head = el(doc, 'div', 'cal-head');
    var prev = el(doc, 'button', 'btn', '<');
    prev.type = 'button';
    prev.id = 'cal-prev';
    prev.setAttribute('aria-label', 'Previous month');
    var label = el(doc, 'span', 'cal-label', MONTHS[month] + ' ' + year);
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
    var first = new Date(year, month, 1).getDay();
    var days = new Date(year, month + 1, 0).getDate();
    for (i = 0; i < first; i++) grid.appendChild(el(doc, 'span', 'cal-day blank', ''));
    for (i = 1; i <= days; i++) {
      (function (day) {
        var b = el(doc, 'button', 'cal-day', String(day));
        b.type = 'button';
        b.setAttribute('data-date', isoDate(year, month, day));
        b.addEventListener('click', function () { onDayClick(doc, mount, b); });
        grid.appendChild(b);
      })(i);
    }
    mount.appendChild(grid);

    prev.addEventListener('click', function () {
      var y = month === 0 ? year - 1 : year;
      var m = (month + 11) % 12;
      renderCalendar(doc, mount, y, m);
    });
    next.addEventListener('click', function () {
      var y = month === 11 ? year + 1 : year;
      var m = (month + 1) % 12;
      renderCalendar(doc, mount, y, m);
    });
    today.addEventListener('click', function () {
      var now = new Date();
      renderCalendar(doc, mount, now.getFullYear(), now.getMonth());
    });
  }

  // Day drill — lazy GET /api/buckets, guarded.
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

  // --- node tree (stub-data renderer; data arrives lazily) ---
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
          var li = el(doc, 'li', null, null);
          li.style.marginLeft = (depth * 14) + 'px';
          li.appendChild(doc.createTextNode(nodeTitle(node)));
          li.appendChild(el(doc, 'span', 'node-kind', node.kind || 'node'));
          var tags = nodeTags(node);
          if (tags.length) li.appendChild(el(doc, 'span', 'node-tags', tags.join(', ')));
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

  function renderTagList(doc, tagsEl, tags) {
    while (tagsEl.firstChild) tagsEl.removeChild(tagsEl.firstChild);
    if (!tags || !tags.length) {
      tagsEl.appendChild(el(doc, 'span', 'empty', 'No tags loaded yet.'));
      return;
    }
    tags.forEach(function (t) {
      tagsEl.appendChild(el(doc, 'span', 'tag-chip', t));
    });
  }

  // mountPlanner(container, ctx?) -> handles
  function mountPlanner(container, ctx) {
    ctx = ctx || {};
    var doc = (container && container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) return null;

    var screen = el(doc, 'div', 'screen planner-screen');
    screen.appendChild(el(doc, 'h2', null, 'Planner'));
    screen.appendChild(el(doc, 'p', 'sub', 'Offline — calendar renders locally; lists load on demand.'));

    var split = el(doc, 'div', 'split');
    var paneCal = el(doc, 'div', 'pane');
    paneCal.appendChild(el(doc, 'h3', null, 'Calendar'));
    var calMount = el(doc, 'div', 'planner-calendar');
    calMount.id = 'planner-calendar';
    paneCal.appendChild(calMount);
    var dayDetail = el(doc, 'div', 'status');
    dayDetail.id = 'planner-day-detail';
    dayDetail.textContent = 'Pick a day to load its buckets.';
    paneCal.appendChild(dayDetail);

    var splitter = el(doc, 'div', 'splitter');
    splitter.id = 'planner-splitter';
    splitter.setAttribute('data-split-key', 'chronos.planner.split');
    splitter.setAttribute('title', 'Drag to resize');

    var paneLists = el(doc, 'div', 'pane');
    var nodeCard = el(doc, 'div', 'card');
    nodeCard.appendChild(el(doc, 'h3', null, 'Nodes'));
    var nodeRow = el(doc, 'div', 'row');
    var loadNodes = el(doc, 'button', 'btn', 'Load nodes');
    loadNodes.type = 'button';
    loadNodes.id = 'planner-load-nodes';
    nodeRow.appendChild(loadNodes);
    nodeCard.appendChild(nodeRow);
    var nodeList = el(doc, 'ul', 'node-list');
    nodeList.id = 'planner-node-list';
    nodeCard.appendChild(nodeList);
    paneLists.appendChild(nodeCard);

    var tagCard = el(doc, 'div', 'card');
    tagCard.appendChild(el(doc, 'h3', null, 'Tags'));
    var tagRow = el(doc, 'div', 'row');
    var loadTags = el(doc, 'button', 'btn', 'Load tags');
    loadTags.type = 'button';
    loadTags.id = 'planner-load-tags';
    tagRow.appendChild(loadTags);
    tagCard.appendChild(tagRow);
    var tagList = el(doc, 'div', 'tag-list');
    tagList.id = 'planner-tag-list';
    tagCard.appendChild(tagList);
    paneLists.appendChild(tagCard);

    split.appendChild(paneCal);
    split.appendChild(splitter);
    split.appendChild(paneLists);
    screen.appendChild(split);
    container.appendChild(screen);

    // Offline first paint: calendar + empty states, zero network.
    var now = new Date();
    renderCalendar(doc, calMount, now.getFullYear(), now.getMonth());
    renderNodeTree(doc, nodeList, []);
    renderTagList(doc, tagList, []);

    // Wire the shell splitter (present in bundle; no-op under require()).
    try {
      var sh0 = shell();
      if (sh0) {
        var all = screen.querySelectorAll('.splitter');
        // splitters are wired by initShell in the bundle; wire here for
        // late mounts (tests / UI-B-style mounting).
        void all;
      }
    } catch (_) { /* ignore */ }

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
    mountPlanner: mountPlanner,
    renderPlanner: renderPlanner,
    renderCalendar: renderCalendar,
    renderNodeTree: renderNodeTree,
    renderTagList: renderTagList,
    collectTags: collectTags,
  };
});
