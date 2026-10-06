# Chronos Desktop App — Build Spec (v3 attempt)

## Why v1 (wrapper) and v2 (direct) both died
Both renderers bound UI events only after code paths that can throw at
startup (server/health/discovery calls firing before first paint, unguarded
`localStorage`/fetch, asset load failure). Dead clicks = JS died before
binding. This spec makes that structurally impossible.

## Non-negotiable rules (all agents)
1. **Boot with zero server.** First paint needs no network, no key, no
   discovery. Every server call is lazy (on user action), guarded
   (try/catch → banner + disabled state), never at import/startup time.
2. **Click-through proof per screen.** Each screen ships jsdom interaction
   tests: click nav → screen visible; click each button → stubbed handler
   called. No screen merges without its click tests green.
3. **No absolute asset refs.** Renderer is one self-contained bundle;
   build fails on any leading-`/` asset ref (same guard as v2).
4. **Frozen contracts** (disputes resolved by these, not by agents):
   - REST: `docs/server/API.md` (base `http://host:8080`, discovery port
     `693`, `GET /api/health` only open route).
   - IPC: `chronos-notify{title,body}` renderer→main only; preload exposes
     exactly `window.chronos{notify,onNavigate?}`; `contextIsolation` on,
     `nodeIntegration` off; secrets stay in renderer localStorage.
   - Layout: left sidebar (Planner/Timer+Log/Briefing/Stats/Settings),
     collapsible to icons (persisted); resizable drag splitters; usable at
     640px (stack); bounds+panels persisted in userData JSON, hand-rolled.
5. **Ownership (one writer per path):** `app2/main/*` (shell), 
   `app2/renderer/screens/planner.js + timer.js` (A), `app2/renderer/*`
   (rest: briefing/stats/settings/ai-row/shell-css) (B), `app2/tests/*`
   (integrator). New dir `app2/` — `app-electron/` stays dead.
6. Lean: no frameworks in renderer (vanilla + one bundle step), no new
   runtime deps without manager approval.

## Screens (unchanged features)
- Planner: calendar + node tree + tags. Timer+Log: 3 modes, strict
  toggle, breakdown drill. Briefing: briefing + question box. Stats:
  charts (canvas, hand-rolled). Settings: server URL/key, providers
  add/reorder, keys add/delete (never displayed), autostart toggle,
  per-category notification toggles, health banner.
- Every screen: AI row (mic button → `POST /api/voice`, graceful
  disabled when server down; text input → contextual POST).

## Division (4 parallel, then integrate)
- **SHELL:** `app2/main/*` (main, preload, autostart, notify, store) +
  `app2/package.json` builder config (AppImage+deb/NSIS/dmg-unsigned) +
  `.github/workflows/app2.yml`. Tests: main-process logic only.
- **UI-A:** planner + timer screens + sidebar/nav shell + CSS responsive
  rules. Tests: jsdom click-through for its 2 screens.
- **UI-B:** briefing + stats + settings/providers + AI row component +
  discovery client. Tests: jsdom click-through for its 3 screens + AI row.
- **INTEGRATOR (runs after A+B land):** cross-screen jsdom suite (nav to
  all 5, AI row on each, server-down boot with fetch stubbed to throw),
  `electron-builder --linux AppImage`, report artifact + gaps. Win/mac
  CI-only, marked unverified.
