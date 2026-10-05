# API contract — frozen interface

**Build to this.** These are settled; do not relitigate them. Derived from the
frozen proposals in [`proposals/`](proposals/) and
[Chronos.md](../Chronos.md).

---

## 1. The server

```
chronos serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]
chronos setup              # interactive: STT, text providers, embeddings, timezone
chronos key-renew
chronos db-upgrade
chronos token-cost [--days 7]
chronos export
chronos say -              # read a sentence from stdin
chronos get day | timer | briefing
```

Terse output, no prompts, safe to pipe.

**Non-negotiable:** the console script must actually run. The last build's entry
point pointed at a module that never existed, so the server could not boot while
690 tests passed. Write a contract test that executes the installed script.

---

## 2. Auth — §3

- **One instance key**, generated on first run, printed **once**, stored
  Argon2-hashed.
- **Every** REST request, WebSocket upgrade, MCP call and CLI command requires it.
- Header `X-Chronos-Key`; query-string `?key=` fallback for MCP clients that
  cannot set headers.
- `/api/health` is the **only** unauthenticated route — §11, so a client can say
  "server is down" instead of spinning.
- **The key must never reach a log line** — via query string *or* header.
  uvicorn logs full request headers, so redact there too.
- Admin = anyone holding the key (ruling 23).

---

## 3. REST routes

```
POST   /api/say              {text}                  -> proposal
POST   /api/commands         tool dispatch
POST   /api/voice            multipart audio -> STT
GET    /api/events           ?from=<ms>&to=<ms>
GET    /api/nodes            ?parent=<id>
GET    /api/buckets          level / date
GET    /api/briefing         ?date=<YYYY-MM-DD>
GET    /api/search           ?q=
GET    /api/reminders
GET    /api/timer
POST   /api/timer/start
POST   /api/timer/stop
GET    /api/timer/summary
GET    /api/timer/presets
POST   /api/timer/presets
GET    /api/stats
GET    /api/settings
PUT    /api/settings
POST   /api/keys/renew
GET    /api/health           (open)
```

### `/api/say` — the core

Returns a **proposal**, never a silent commit:

```json
{
  "intent": "create_event",
  "tool_calls": [{"tool": "create_event", "arguments": {...}}],
  "proposal_id": "uuid",
  "committed": false,
  "events": [],
  "message": "Proposes DB review at 2026-10-04T16:00:00+00:00."
}
```

**Must work with no provider keys** — the README promises a built-in offline
parser. Keys unlock better models; they are never required.

An **ambiguous** sentence must propose *and* ask (§5.5/§5.7) — at most one
`question`. See [scheduling-behaviour.md](scheduling-behaviour.md).

An endpoint that is not implemented must **not** return `success: true`.

---

## 4. WebSocket

- `/ws`, authenticated **before** `accept()`; unauthenticated upgrades close with
  **4001**.
- Must call `await websocket.accept()` or the upgrade 404s.
- **`websockets` must be a declared dependency.** uvicorn ships no WebSocket
  implementation; Starlette's `TestClient` has its own, which masks this — that
  is why 112 tests passed while the real server 404'd every upgrade.
- Pushes: state, timer, proposal, question.

---

## 5. Data model essentials

- **Buckets** Y→M→W→D, 10 years, ~4,300 rows, idempotent seeding. Week 1 of the
  first year starts in December of the prior year — its parent month must exist,
  or clamp the week rather than dropping it.
- **Review series** must be **bounded** — `max_count` and/or `ends_on_ms`. Enforce
  at both the repo and the schema. State values are lowercase
  `active|retired|cancelled` and the spec declares **no CHECK** on it.
- **One timer at a time** — enforce with a unique partial index, not only in the
  route layer.
- **A stopwatch ignores a target** and its time **counts toward** totals. Pomodoro
  **breaks** are excluded. Inverting this is easy and wrong.
- **Events snap to the minute grid** (§7.2).
- **Day boundaries use `instance.timezone`**, never a hardcoded UTC.
- **Tags never attach to projects** (§4.1).

---

## 6. Search

`node_fts` is **external-content** FTS5 (`content=''`). `rowid` must be an
INTEGER — map the TEXT uuid deterministically (SHA-256 → 62-bit). Passing a TEXT
uuid as `rowid` raises `datatype mismatch` and **nothing is ever indexed**, so
search silently returns empty forever.

Degrade gracefully when `sqlite-vec` is absent: keywords still work.

---

## 7. Threading

`DatabaseEngine.conn` is **thread-local**. Do not capture the boot-thread
connection into `app.state` or a repo — every worker-thread request then raises
`sqlite3.ProgrammingError`. Resolve the connection per call.

---

## 8. Migration idempotency

Normalise every DDL statement to `CREATE ... IF NOT EXISTS` and track a
`schema_version`. A second boot against an existing database must succeed.

---

## 9. Timeouts and values

Enum values crossing into SQLite and back must round-trip through the enum
constructor: `EventKind(row["kind"])` must not raise. Raw TEXT from the database
is not an enum member, and `.value` on it explodes. Five uppercase defaults
shipped exactly this bug.

Minute snapping, timezone-aware day boundaries, and half-open event overlap
(`from` inclusive, `to` exclusive) are all spec'd — read §7.

---

## Clients — backend-only, no bundled web

**2026-10-05 decision: backend is API-only.** No `chronos/web/`, no `mount_hud`, no `index.html/app.js`, no `/`, `/styles.css`, `/app.js` routes. `CHRONOS_WEB` / `--no-web` removed — the server never serves HTML.

The clients — browser UIs, Android apps, MCP agents, CLIs — are **separate projects**
outside this repository. They are not documented here, and this server agent
should not build them or read their material.

What matters for the server is only this: **the API you expose is a contract.**
Endpoints, auth, and response shapes must not drift. A client that works against
today's API must keep working tomorrow. That contract is REST (`/api/*`) + WebSocket (`/ws`) + MCP (`/mcp`), all against the same `ToolDispatcher`.