# Chronos Web (browser client)

One codebase, runs anywhere a browser runs. Vite + TypeScript, no framework (vanilla DOM), against REST+WS per `docs/server/API.md` (v1.1+v1.2; shapes are truth).

## Install / dev / build

```bash
cd web
npm install
npm run dev      # http://localhost:5173
npm run build    # tsc --noEmit + vite build -> dist/
npm test         # vitest run (fakes only, no network)
```

Pinned: `vite 5.4.8`, `typescript 5.6.2`, `vitest 2.1.3`.

## Key storage — XSS caveat (read this)

The instance key is stored in `localStorage` (`chronos.key`) so the SPA survives reloads. **Honest caveat:** any script running on this origin (XSS, malicious extension, devtools) can read `localStorage` and steal the key. Mitigations applied: key sent only via `X-Chronos-Key` header, never in URLs (except MCP `?key=` which this client never uses), never logged, never rendered, key fields are `type=password`. For higher assurance, serve the built `dist/` from a trusted origin over HTTPS and keep the browser profile clean.

## Server discovery

Browsers cannot enumerate the LAN. Order: `http://127.0.0.1:693` first, then the manual host, then remembered hosts (localStorage `chronos.hosts`, cap 8). Probe = `GET /api/health` (the only open route) with 3s timeout; data calls always send the saved key. Port default **693**.

## Notes

- Health gate banner on top; when down, views fall back to cached read-only snapshots (`chronos.cache.*`).
- Timer: stopwatch/countdown/pomodoro, target picker, strict toggle (client-side label), presets (always includes 25/5x4 from server), live tick including remote sessions, 409 message when one is already running, stop keeps time / void only after a second confirmed attempt.
- Voice bar: text via `POST /api/say` (proposal accept/reject over `/ws`); mic button uses `MediaRecorder` → `POST /api/voice` only when `MediaRecorder` + mic are available, otherwise the button is disabled and labelled text-only.
- Provider management in Settings: list/add/reorder providers, add/delete keys. Keys are write-only — the list shows `key_ids`/`key_count` only and values are cleared from the input immediately after POST.
