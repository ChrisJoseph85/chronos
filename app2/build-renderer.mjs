// Chronos app2 — renderer bundler (UI-A owned).
//
// Vanilla bundler: concatenates/inlines UI-A files plus a placeholder hook
// for UI-B files when present, and emits a SINGLE self-contained
// app2/renderer-dist/index.html.
//
// Rules enforced here:
//  - build FAILS (exit 1) on any leading-`/` asset ref in sources or output
//    (same guard as v2): src="/..., href="/..., url(/..., @import "/...,
//    or ES import ... from "/...  (API paths like '/api/nodes' are fine —
//    the patterns only match asset-attribute/import positions).
//  - build FAILS if a required UI-A file is missing.
//  - UI-B hook: optional files are inlined only when present, in fixed
//    order; the boot script mounts them behind typeof-guards.
//
// Usage: node app2/build-renderer.mjs
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = join(here, 'renderer-src');
const outDir = join(here, 'renderer-dist');

// UI-A required files (fail build when missing).
const REQUIRED_JS = [
  'shell/shell.js',
  'screens/planner.js',
  'screens/timer.js',
];
const REQUIRED_CSS = ['shell/shell.css'];

// UI-B placeholder hook: inlined only when present. Order is fixed so the
// bundle is deterministic regardless of which subset has landed.
const OPTIONAL_JS = [
  'ai-row.js',
  'discovery.js',
  'screens/briefing.js',
  'screens/stats.js',
  'screens/settings.js',
];
const OPTIONAL_CSS = ['shell/extra.css'];

function read(rel) {
  return readFileSync(join(srcDir, rel), 'utf8');
}

// Leading-`/` asset refs. Deliberately anchored to asset positions so that
// API strings like '/api/nodes' inside JS never match.
const ASSET_PATTERNS = [
  /(src|href)\s*=\s*["']\//, // src="/x  href='/x
  /url\(\s*["']?\//, // CSS url(/x)  url("/x")
  /@import\s+["']\//, // CSS @import "/x"
  /\bimport\s[^;]*?["']\//, // import ... from "/x"
  /\bfrom\s+["']\//, // from "/x"
];

function assertNoAssetRefs(label, text, isOutput) {
  for (const re of ASSET_PATTERNS) {
    if (re.test(text)) {
      console.error(`build-renderer: FAIL — leading-/ asset ref in ${label} (pattern ${re})`);
      process.exit(1);
    }
  }
  // Sources are inlined into <script>/<style> blocks, so a literal
  // </script inside a source would break the bundle. (The assembled HTML
  // itself legitimately contains </script> closers — do not check it.)
  if (!isOutput && text.includes('</script')) {
    console.error(`build-renderer: FAIL — literal </script in ${label} would break inlining`);
    process.exit(1);
  }
}

function main() {
  const missing = REQUIRED_JS.concat(REQUIRED_CSS).filter((rel) => !existsSync(join(srcDir, rel)));
  if (missing.length) {
    console.error(`build-renderer: FAIL — missing required files: ${missing.join(', ')}`);
    process.exit(1);
  }

  const cssParts = [];
  const jsParts = [];
  for (const rel of REQUIRED_CSS) {
    const text = read(rel);
    assertNoAssetRefs(rel, text);
    cssParts.push(`/* --- ${rel} --- */\n` + text);
  }
  for (const rel of OPTIONAL_CSS) {
    if (!existsSync(join(srcDir, rel))) {
      console.log(`build-renderer: hook — optional ${rel} absent, skipping`);
      continue;
    }
    const text = read(rel);
    assertNoAssetRefs(rel, text);
    cssParts.push(`/* --- ${rel} (UI-B hook) --- */\n` + text);
  }
  for (const rel of REQUIRED_JS) {
    const text = read(rel);
    assertNoAssetRefs(rel, text);
    jsParts.push(`/* --- ${rel} --- */\n` + text);
  }
  const hooked = [];
  for (const rel of OPTIONAL_JS) {
    if (!existsSync(join(srcDir, rel))) {
      console.log(`build-renderer: hook — optional ${rel} absent, skipping`);
      continue;
    }
    const text = read(rel);
    assertNoAssetRefs(rel, text);
    jsParts.push(`/* --- ${rel} (UI-B hook) --- */\n` + text);
    hooked.push(rel);
  }

  const bootLines = [
    '(function () {',
    '  function byId(id) { return document.getElementById(id); }',
    '  function fatal(msg) {',
    '    try { var b = byId("global-banner"); if (b) { b.textContent = String(msg); b.hidden = false; } } catch (e) {}',
    '  }',
    '  var ctx = null;',
    '  try { if (window.ChronosShell && window.ChronosShell.defaultCtx) ctx = window.ChronosShell.defaultCtx(); }',
    '  catch (e) { ctx = null; }',
    '  if (!ctx) ctx = {};',
    '  try { if (window.ChronosShell) window.ChronosShell.initShell(document); }',
    '  catch (e) { fatal("Shell failed to start: " + (e && e.message)); }',
    '  function mount(globalName, fnName, sectionId) {',
    '    try {',
    '      var g = window[globalName];',
    '      var sec = byId(sectionId);',
    '      if (g && typeof g[fnName] === "function" && sec) g[fnName](sec, ctx);',
    '    } catch (e) { fatal(globalName + " failed to render: " + (e && e.message)); }',
    '  }',
    '  mount("ChronosPlanner", "mountPlanner", "screen-planner");',
    '  mount("ChronosTimer", "mountTimer", "screen-timer");',
    '  mount("ChronosBriefing", "mountBriefing", "screen-briefing");',
    '  mount("ChronosStats", "mountStats", "screen-stats");',
    '  mount("ChronosSettings", "mountSettings", "screen-settings");',
    '})();',
  ];
  const boot = bootLines.join('\n');
  assertNoAssetRefs('boot script', boot);

  const html =
    '<!DOCTYPE html>\n' +
    '<html lang="en">\n' +
    '<head>\n' +
    '<meta charset="utf-8">\n' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
    '<title>Chronos</title>\n' +
    '<style>\n' + cssParts.join('\n\n') + '\n</style>\n' +
    '</head>\n' +
    '<body>\n' +
    '<div id="app">\n' +
    '  <nav id="sidebar" aria-label="Primary">\n' +
    '    <div class="brand"><span class="brand-mark">◷</span><span class="brand-name">Chronos</span></div>\n' +
    '    <button type="button" class="nav-btn" data-screen-nav="planner"><span class="nav-icon">▦</span><span class="nav-label">Planner</span></button>\n' +
    '    <button type="button" class="nav-btn" data-screen-nav="timer"><span class="nav-icon">◷</span><span class="nav-label">Timer+Log</span></button>\n' +
    '    <button type="button" class="nav-btn" data-screen-nav="briefing"><span class="nav-icon">☰</span><span class="nav-label">Briefing</span></button>\n' +
    '    <button type="button" class="nav-btn" data-screen-nav="stats"><span class="nav-icon">▅</span><span class="nav-label">Stats</span></button>\n' +
    '    <button type="button" class="nav-btn" data-screen-nav="settings"><span class="nav-icon">⚙</span><span class="nav-label">Settings</span></button>\n' +
    '    <button type="button" id="sidebar-collapse" aria-label="Collapse sidebar">«</button>\n' +
    '  </nav>\n' +
    '  <div class="splitter" id="sidebar-splitter" data-split-key="chronos.sidebar.width" data-split-target="sidebar" title="Drag to resize"></div>\n' +
    '  <main id="main">\n' +
    '    <div id="global-banner" hidden role="alert"></div>\n' +
    '    <div id="screen-container">\n' +
    '      <section id="screen-planner" data-screen-panel="planner" aria-label="Planner"></section>\n' +
    '      <section id="screen-timer" data-screen-panel="timer" aria-label="Timer and Log" hidden></section>\n' +
    '      <section id="screen-briefing" data-screen-panel="briefing" aria-label="Briefing" hidden><div class="empty">Briefing screen — provided by UI-B.</div></section>\n' +
    '      <section id="screen-stats" data-screen-panel="stats" aria-label="Stats" hidden><div class="empty">Stats screen — provided by UI-B.</div></section>\n' +
    '      <section id="screen-settings" data-screen-panel="settings" aria-label="Settings" hidden><div class="empty">Settings screen — provided by UI-B.</div></section>\n' +
    '    </div>\n' +
    '  </main>\n' +
    '</div>\n' +
    jsParts.map((p) => '<script>\n' + p + '\n</script>').join('\n') +
    '\n<script>\n' + boot + '\n</script>\n' +
    '</body>\n' +
    '</html>\n';

  assertNoAssetRefs('output index.html', html, true);

  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, 'index.html'), html, 'utf8');
  console.log(`build-renderer: OK — renderer-dist/index.html (${html.length} bytes, UI-B hooked: ${hooked.length ? hooked.join(', ') : 'none'})`);
}

main();
