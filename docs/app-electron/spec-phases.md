# Chronos Desktop App (app2) — Phase-based dispatch spec

Subagents run on **Muse Spark** (`opencode/muse-spark-1.3-contributor-free`).
Target dir: `app2/` (dead attempts `app-electron/`, `web/electron/` stay untouched).
Full product spec: `docs/app-electron/spec.md` (layout, rules 1–6, frozen contracts).

## Phase 0 — Contracts (manager, no agent)
Frozen: REST `docs/server/API.md`; IPC `chronos-notify{title,body}` only;
preload exposes exactly `window.chronos{notify}`; `contextIsolation` on,
`nodeIntegration` off; secrets in renderer localStorage only.
Screen contract: each screen module exports `init(el, ctx)`,
`ctx={api,notify,aiRow,prefs,savePrefs,banner,autostart,setAutostart,setNotify,go}`.

## Phase 1 — SHELL (agent, parallel with 2+3)
Owns: `app2/main/*`, `app2/package.json`, `.github/workflows/app2.yml`.
Delivers: main (single-instance, `--autostart` hidden, bounds persist),
preload.cjs, autostart (linux user-.desktop / win+mac login item),
store (UI keys only, corrupt-tolerant), discovery (port 693 list, pure),
`--smoke` that prints SMOKE-RESULT and exits ≤10s headless.
Accept: `node --test app2/tests/shell-*.test.js` green. No commits.

## Phase 2 — UI-A (agent, parallel)
Owns: `app2/renderer/shell.html`, `app.css`, `screens/planner.js`, `screens/timer.js`.
Delivers: sidebar nav (5 screens, collapsible, persisted), planner
(calendar+tree+tags), timer (3 modes, strict, breakdown drill), splitter drag,
640px stacking CSS. All data via injected `ctx.api`; zero fetch at boot.
Accept: jsdom/hand-rolled-DOM click tests green (nav shows screen, every
button calls its double). No commits.

## Phase 3 — UI-B (agent, parallel)
Owns: `screens/briefing.js`, `stats.js`, `settings.js`, `ai-row.js`,
`api.js`, `discovery-client.js`.
Delivers: briefing+ask, canvas stats, settings (URL/key, providers add/reorder,
keys add/delete never shown, autostart toggle, per-category notify toggles,
health banner), AI mic+text row mountable on every screen, lazy guarded api.
Accept: click tests green incl. server-down graceful disable. No commits.

## Phase 4 — INTEGRATE (agent, after 1+2+3 land)
Owns: `app2/tests/click.test.js`, `scripts/build-renderer.js`, `scripts/smoke.js`.
Delivers: single-file inlined `dist/index.html` (build FAILS on absolute refs),
cross-screen suite (all 5 nav, AI row each, server-down boot never throws),
`electron-builder --linux AppImage` artifact on disk.
Accept: full `node --test app2/tests/` green + AppImage exists. No commits.
Win/mac via CI only, marked unverified.

## Manager verify (no agent): re-run tests + build, launch AppImage, commit+push.
