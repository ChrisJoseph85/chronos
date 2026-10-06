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

// Testable IPC handler core: validates, then delegates display to showFn.
// Returns true when a notification was shown, false otherwise (never throws).
function handleNotifyIpc(payload, showFn) {
  const result = validateNotify(payload);
  if (!result.ok) return false;
  try {
    showFn({ title: result.title, body: result.body });
    return true;
  } catch {
    return false;
  }
}

module.exports = {
  MAX_TITLE_LEN,
  MAX_BODY_LEN,
  validateNotify,
  handleNotifyIpc,
};
