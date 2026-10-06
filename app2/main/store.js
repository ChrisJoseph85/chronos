'use strict';

// Hand-rolled JSON store for window bounds + panel state.
// No electron dependency: persists to an explicit file path so it is
// unit-testable with plain node. Secrets never go here (renderer
// localStorage owns secrets per spec).

const fs = require('fs');
const path = require('path');

const STORE_FILE_NAME = 'window-state.json';

const DEFAULT_BOUNDS = Object.freeze({
  x: undefined,
  y: undefined,
  width: 1200,
  height: 800,
});

const DEFAULTS = Object.freeze({
  bounds: { ...DEFAULT_BOUNDS },
  sidebarCollapsed: false,
  panels: {},
});

function cloneDefaults() {
  return {
    bounds: { ...DEFAULT_BOUNDS },
    sidebarCollapsed: false,
    panels: {},
  };
}

function sanitizeBounds(raw) {
  const out = { ...DEFAULT_BOUNDS };
  if (raw && typeof raw === 'object') {
    for (const key of ['x', 'y', 'width', 'height']) {
      const v = raw[key];
      if (typeof v === 'number' && Number.isFinite(v)) {
        out[key] = v;
      }
    }
  }
  // Guard against zero/negative/huge window sizes; fall back to defaults.
  if (!(out.width >= 200 && out.width <= 7680)) out.width = DEFAULT_BOUNDS.width;
  if (!(out.height >= 200 && out.height <= 4320)) out.height = DEFAULT_BOUNDS.height;
  return out;
}

function sanitizeState(raw) {
  const base = cloneDefaults();
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return base;
  base.bounds = sanitizeBounds(raw.bounds);
  base.sidebarCollapsed = raw.sidebarCollapsed === true;
  if (raw.panels && typeof raw.panels === 'object' && !Array.isArray(raw.panels)) {
    base.panels = { ...raw.panels };
  }
  return base;
}

function defaultStorePath(userDataPath) {
  return path.join(userDataPath, STORE_FILE_NAME);
}

function createStore(filePath) {
  let cache = null;

  function load() {
    if (cache) return cache;
    let raw = null;
    try {
      const text = fs.readFileSync(filePath, 'utf8');
      raw = JSON.parse(text);
    } catch {
      raw = null; // Missing/corrupt file -> clean defaults, never throw.
    }
    cache = sanitizeState(raw);
    return cache;
  }

  function save(state) {
    cache = sanitizeState(state);
    try {
      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(filePath, JSON.stringify(cache, null, 2) + '\n', 'utf8');
    } catch {
      // Best effort: a failed persist must never crash the shell.
    }
    return cache;
  }

  function get(key) {
    return load()[key];
  }

  function set(key, value) {
    const next = { ...load(), [key]: value };
    return save(next);
  }

  function setBounds(bounds) {
    const next = { ...load(), bounds: sanitizeBounds({ ...load().bounds, ...bounds }) };
    return save(next).bounds;
  }

  return { filePath, load, save, get, set, setBounds };
}

module.exports = {
  STORE_FILE_NAME,
  DEFAULTS,
  DEFAULT_BOUNDS,
  defaultStorePath,
  createStore,
  sanitizeBounds,
  sanitizeState,
};
