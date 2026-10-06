'use strict';

// Validation for the frozen IPC contract: renderer -> main only,
// `chronos-notify{title,body}`. Pure logic (no electron import) so it can
// be unit-tested with plain `node --test` (no display).

const MAX_TITLE_LEN = 200;
const MAX_BODY_LEN = 2000;

function validateNotify(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { ok: false, error: 'payload must be an object {title, body}' };
  }
  const { title, body } = payload;
  if (typeof title !== 'string' || title.trim().length === 0) {
    return { ok: false, error: 'title must be a non-empty string' };
  }
  if (typeof body !== 'string' || body.trim().length === 0) {
    return { ok: false, error: 'body must be a non-empty string' };
  }
  if (title.trim().length > MAX_TITLE_LEN) {
    return { ok: false, error: `title must be <= ${MAX_TITLE_LEN} chars` };
  }
  if (body.trim().length > MAX_BODY_LEN) {
    return { ok: false, error: `body must be <= ${MAX_BODY_LEN} chars` };
  }
  return { ok: true, title: title.trim(), body: body.trim() };
}

// Testable IPC handler core: validates, polishes display text, then
// delegates display to showFn. Returns true when a notification was shown,
// false otherwise (never throws).
function handleNotifyIpc(payload, showFn) {
  const result = validateNotify(payload);
  if (!result.ok) return false;
  try {
    showFn(formatNotify({ title: result.title, body: result.body }));
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Engagement polish: display-text normalization for EVERY notify path
// (briefing / timer / reminder / proposal all arrive here from the renderer).
// Validation + limits above are the frozen contract and are unchanged; this
// only shapes already-valid text for display: crisp Title Case headlines,
// one-line bodies, no raw JSON dumps, capped at NOTIFY_BODY_MAX chars.
// Pure + total (never throws) so it stays unit-testable with plain node.
// ---------------------------------------------------------------------------

// Display cap for notification bodies (validation limit MAX_BODY_LEN stays).
const NOTIFY_BODY_MAX = 120;

function toTitleCase(s) {
  return String(s == null ? '' : s)
    .split(/\s+/)
    .filter((w) => w.length > 0)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}

function oneLine(s) {
  return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
}

function looksLikeJsonDump(s) {
  const t = oneLine(s);
  if (!/^[{[]/.test(t)) return false;
  try {
    JSON.parse(t);
    return true;
  } catch {
    return false;
  }
}

function truncateBody(s) {
  const t = oneLine(s);
  if (t.length > NOTIFY_BODY_MAX) return t.slice(0, NOTIFY_BODY_MAX - 1) + '…';
  return t;
}

function formatNotifyBody(body) {
  const t = oneLine(body);
  if (!t) return t;
  // Never surface a raw JSON/object dump (or bare ids payload) as body text.
  if (looksLikeJsonDump(t)) return 'The details are ready in the app, sir.';
  return truncateBody(t);
}

// formatNotify({title, body}) -> {title, body} polished for display.
// Total function: coerces, never throws.
function formatNotify(payload) {
  const rawTitle = payload && typeof payload.title === 'string' ? payload.title : '';
  const rawBody = payload && typeof payload.body === 'string' ? payload.body : '';
  return { title: toTitleCase(rawTitle), body: formatNotifyBody(rawBody) };
}

module.exports = {
  MAX_TITLE_LEN,
  MAX_BODY_LEN,
  validateNotify,
  handleNotifyIpc,
  NOTIFY_BODY_MAX,
  toTitleCase,
  oneLine,
  truncateBody,
  formatNotifyBody,
  formatNotify,
};
