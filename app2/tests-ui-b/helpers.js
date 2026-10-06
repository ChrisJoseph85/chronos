// Shared jsdom harness for UI-B click-through tests.
'use strict';

const { JSDOM } = require('jsdom');

function makeDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/',
  });
  global.window = dom.window;
  global.document = dom.window.document;
  global.localStorage = dom.window.localStorage;
  // NOTE: do not assign global.navigator — Node >= 21 exposes it as a
  // getter-only global. Use window.navigator where needed.
  // Keep node-native Blob/FormData (node >= 18); fall back to jsdom's.
  if (typeof global.Blob === 'undefined') global.Blob = dom.window.Blob;
  if (typeof global.FormData === 'undefined') global.FormData = dom.window.FormData;
  return dom;
}

function teardownDom() {
  try {
    if (global.window && typeof global.window.close === 'function') global.window.close();
  } catch (_) { /* ignore */ }
  delete global.window;
  delete global.document;
  delete global.localStorage;
}

// Let queued promise continuations (the screens use Promise.resolve(p).then)
// run to completion.
async function flush(turns = 10) {
  for (let i = 0; i < turns; i++) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function jsonResponse(data, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
  };
}

function click(node) {
  if (typeof node.click === 'function') {
    node.click();
  } else {
    node.dispatchEvent(new global.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  }
}

function submitForm(form) {
  form.dispatchEvent(new global.window.Event('submit', { bubbles: true, cancelable: true }));
}

module.exports = { makeDom, teardownDom, flush, jsonResponse, click, submitForm };
