# Phase 3 — Server (api, realtime, auth)

**Runs in parallel with phases 1, 2, 4–6.** Binds the frozen interfaces together
into a running server. It may start as soon as the Phase 0 contracts are frozen;
it does not wait for phases 1 and 2 to be *finished*, only for their interfaces.

Spec: `docs/Chronos.md` §3 (auth), §8 (server), §6 (conflict rules at commit).

---

## Parts

| Part | Files | Owner |
|---|---|---|
| 3.1 app factory | `chronos/api/app.py` | one code agent |
| 3.2 auth | `chronos/api/auth.py` | one code agent |
| 3.3 REST routes | `chronos/api/routes.py` | one code agent |
| 3.4 voice route | `chronos/api/voice.py` | one code agent |
| 3.5 realtime hub | `chronos/realtime/` | one code agent |
| 3.6 smoke script | `scripts/smoke.sh` | one code agent |

3.1 and 3.2 gate the rest of the phase. 3.3–3.6 then run in parallel.

---

## Behaviour the tests must pin

**Auth (§3)**
- One **instance key**, generated on first run, printed once, stored
  **Argon2-hashed**.
- Every REST request, WebSocket upgrade, MCP call and CLI command requires it —
  header `X-Chronos-Key`, with a query-string fallback for MCP clients.
- **`/api/health` is the only unauthenticated route.** Everything else is 401
  without a valid key.
- **A key in a query string is never written to a log.** This is easy to get
  wrong: an HTTP client logging the full URL will leak it. Redact at
  record-creation time, not with a logger-attached filter (filters do not run for
  descendant loggers like `httpx._client`).
- `key-renew` rotates the key and disconnects every client.
- Single user. No roles, no registration, no multi-tenancy.

**App factory (§8.2)**
- `create_app(db_path=None) -> FastAPI`. **This signature is load-bearing** — the
  CLI, the smoke script and the tests all call it. Do not change it.
- It must open the file `db_path` names. Getting this wrong 401s every request,
  because the app validates against a different database's key.

**REST (§8.2)**
All routes present, all authenticated except `/api/health`:

```
POST   /api/voice                audio → transcript
POST   /api/say                  text → intent → proposal → commit
POST   /api/commands             raw tool call, for CLI and MCP
GET    /api/events?from&to       range query
GET    /api/nodes?parent&tag     tree query
GET    /api/buckets?level&date   bucket contents
GET    /api/briefing?date        daily briefing
GET    /api/search?q&limit       keyword + semantic
GET    /api/reminders            pending reminders
POST   /api/timer/start · /stop
GET    /api/timer?node_id        running timer
GET    /api/timer/summary?node_id  logged time + project rollup
GET/POST /api/timer/presets      custom pomodoro focus/break pairs
GET    /api/stats                counts, streaks, token spend by day
GET    /api/settings · PUT /api/settings
POST   /api/keys/renew
GET    /api/health
```

- `POST /api/say` runs propose → verify → commit and returns the result.
- Starting a timer while one runs is **refused** with a clear client error (409),
  not a crash and not a silent replace.
- Every route is a real implementation. **A stub left in `routes.py` that shadows
  a later module's route is a bug** — v1 shipped two of them, which made the
  features invisible while tests passed.

**WebSocket (§8.3)**
- One connection per client, authenticated on upgrade.
- Server → client: `state` (full snapshot on connect), `patch`, `proposal`,
  `question`, `timer`, `queued`, `retrying`.
- Client → server: `hello`, `say`, `accept` / `reject` / `skip`.
- One hub, many clients: **every mutation broadcasts to all of them.**

---

## Done means

- [ ] `scripts/smoke.sh` boots the real server and passes every check
- [ ] 401 without a key on every authenticated route; `/api/health` open
- [ ] the query-string key never reaches a log line
- [ ] one English sentence commits a real event, read back out of SQLite
- [ ] `create_app(db_path=...)` opens that exact file
- [ ] starting a second timer returns 409, not a crash
- [ ] the hub fans out to all connected clients
- [ ] full suite green
- [ ] per-part scratch tests and probe scripts deleted; the phase's spec tests kept
      (`manager.md` §10)

---

## Verification

```bash
.venv/bin/python -m pytest tests/phase_3 -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check chronos tests
./scripts/smoke.sh 8099          # the real proof: boots the server over HTTP
```

A green unit suite is not a running app. `smoke.sh` is the gate.
