// Pure renderer logic: DOM-free so node --test can cover it.

export function formatDuration(ms) {
  const total = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export function formatMsLong(ms) {
  const totalMin = Math.floor((Number(ms) || 0) / 60000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h <= 0) return `${m}m`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

/** Build a parent_id tree from a flat node list. Roots sorted by title. */
export function buildNodeTree(nodes) {
  const byId = new Map();
  for (const n of nodes || []) byId.set(n.id, { ...n, children: [] });
  const roots = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const sortRec = (list) => {
    list.sort((a, b) => String(a.title || "").localeCompare(String(b.title || "")));
    for (const n of list) sortRec(n.children);
  };
  sortRec(roots);
  return roots;
}

/** Collect distinct tag names from node payloads ({tags:[..]} or "a,b"). */
export function collectTags(nodes) {
  const out = new Set();
  for (const n of nodes || []) {
    const tags = Array.isArray(n.tags)
      ? n.tags
      : typeof n.tags === "string"
        ? n.tags.split(",")
        : n.tag
          ? [n.tag]
          : [];
    for (const t of tags) {
      const s = String(t || "").trim();
      if (s) out.add(s);
    }
  }
  return [...out].sort((a, b) => a.localeCompare(b));
}

/**
 * Month grid cells for a calendar: leading nulls + day numbers.
 * weekStart: 0=Sunday,1=Monday.
 */
export function monthCells(year, month /* 1-12 */, weekStart = 1) {
  const first = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const lead = (first.getDay() - weekStart + 7) % 7;
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  return cells;
}

export function dayRangeMs(year, month, day) {
  const start = new Date(year, month - 1, day, 0, 0, 0, 0).getTime();
  return [start, start + 86400000];
}

export function monthRangeMs(year, month) {
  const start = new Date(year, month - 1, 1, 0, 0, 0, 0).getTime();
  const end = new Date(year, month, 1, 0, 0, 0, 0).getTime();
  return [start, end];
}

/** Scale values to 0..100 bar widths; empty -> []. */
export function scaleBars(rows) {
  const max = Math.max(0, ...rows.map((r) => Number(r.value) || 0));
  if (max <= 0) return rows.map((r) => ({ ...r, pct: 0 }));
  return rows.map((r) => ({ ...r, pct: Math.round(((Number(r.value) || 0) / max) * 100) }));
}

/** Group events by yyyy-mm-dd for calendar dots. */
export function eventsByDay(events) {
  const map = new Map();
  for (const e of events || []) {
    const ms = Number(e.start_ms ?? e.startMs ?? 0);
    if (!ms) continue;
    const d = new Date(ms);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    map.set(key, (map.get(key) || 0) + 1);
  }
  return map;
}

/** Clamp a splitter fraction to the usable band. */
export function clampFraction(f) {
  const n = Number(f);
  if (!Number.isFinite(n)) return 0.5;
  return Math.min(0.9, Math.max(0.1, n));
}

/** Parse "host[:port]" discovery input; returns {host, port}. */
export function parseHostPort(raw, defaultPort) {
  const s = String(raw || "").trim();
  const m = s.match(/^(.*?)(?::(\d{1,5}))?$/);
  const host = (m && m[1]) || s;
  const port = m && m[2] ? Number(m[2]) : defaultPort;
  return { host, port };
}
