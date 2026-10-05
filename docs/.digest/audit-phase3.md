# Phase 3 audit — tests/phase_3/test_server_spec.py

**Auditor:** read-only audit agent. **Date:** 2026-10-04.
**Files touched by me:** none. Two temporary mutations were applied to a *copy-safe*
path and restored byte-identically (`chronos/api/auth.py`, `chronos/api/app.py` —
both verified with `diff -q` after restore). No git stash/add/commit.
**Caveat:** another agent was concurrently restructuring `chronos/ai/` during this
audit (`git status` showed `chronos/ai/adapter.py`, `chain.py`, `dispatcher.py`,
`intent.py`, `stt.py` deleted mid-run). Findings that depend on `chronos.ai` imports
are marked **INDETERMINATE**.

---

## 0. Baseline

```
.venv/bin/python -m pytest tests/phase_3 -q
20 failed, 81 passed, 249 warnings, 7 errors in 108.76s
```

Failing (20 F) + erroring (7 E) list is reproduced verbatim in §6.

The suite is not slow because it is thorough. It is slow because
`test_smoke_script_boots_server` shells out to a real server with a 30 s timeout and
`TestWebSocket` spins 9 in-process ASGI portals. Neither buys real-server coverage.

---

## 1. THE HEADLINE: the v1 failure is still live, and the suite does not catch it

**This is the single most important finding.**

I booted the real product exactly as `errors-and-test-proposal.md` Layer 3
prescribes and probed it.

```
$ chronos serve --port 8199 --db /tmp/audit3.db &
$ curl -s http://127.0.0.1:8199/api/health
{"status":"ok","version":"0.1.0","db_path":"/tmp/audit3.db","uptime_seconds":2.75}

$ curl -s -X POST -H "X-Chronos-Key: $K" -d '{"text":"schedule DB review tomorrow 4pm for 45 mins"}' \
       http://127.0.0.1:8199/api/say
{"intent":"unknown","tool_calls":[],"proposal_id":null,"committed":false,
 "events":[],"message":"Intent pipeline not yet implemented"}
```

`chronos/api/routes.py:279` and `:307` still contain the literal strings
`"Intent pipeline not yet implemented"` and `"Tool dispatch not yet implemented"`.

```
$ curl -s -X POST -H "X-Chronos-Key: $K" -d '{"tool":"get_day","arguments":{}}' \
       http://127.0.0.1:8199/api/commands
{"tool":"get_day","result":{"tool_name":"get_day","success":true,
 "result":{"message":"Tool dispatch not yet implemented"},"error":null}, ...}
```

That is **A4 and A5 verbatim**, in the shipping product, right now. `success: true`
while doing nothing — the exact "silently lied" defect from the post-mortem.

SQLite confirms the core feature wrote nothing:

```
>>> sqlite3 /tmp/audit3.db "select count(*) from events"
0
```

The phase-3 "Done means" box — *"one English sentence commits a real event, read back
out of SQLite"* — is **false in the running product**, and `test_say_creates_events`
(the only test that claims to check it) passes. See §3.

---

## 2. WebSocket: masked again, exactly as in v1

### 2a. `websockets` is not a declared dependency

`pyproject.toml` `[project.dependencies]`:
```
fastapi, uvicorn>=0.30, sqlalchemy, alembic, argon2-cffi, sqlite-vec,
python-multipart, httpx
```
No `websockets`. No `wsproto`. No `uvicorn[standard]`. Verified in the venv:

```
$ .venv/bin/python -c "import websockets"
ModuleNotFoundError: No module named 'websockets'
$ .venv/bin/python -c "import wsproto"
ModuleNotFoundError: No module named 'wsproto'
```

### 2b. The real server 404s every upgrade

```
$ curl -i -H "Connection: Upgrade" -H "Upgrade: websocket" \
       -H "Sec-WebSocket-Version: 13" \
       -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
       http://127.0.0.1:8199/ws
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

Server log, verbatim:
```
WARNING:  Unsupported upgrade request.
WARNING:  No supported WebSocket library detected. Please use
          "pip install 'uvicorn[standard]'", or install 'websockets' or 'wsproto' manually.
INFO:     127.0.0.1 - "GET /ws HTTP/1.1" 404 Not Found
```

**This is byte-for-byte the v1 B5 environment.** `chronos/api/app.py:203` *does* call
`await websocket.accept()` — the code fix landed — but uvicorn cannot reach it, so the
entire realtime feature is dead in the product while the tests pass.

### 2c. All 9 WebSocket tests use `TestClient` only

Every test in `TestWebSocket` goes through `client.websocket_connect(...)`
(lines 843, 849, 855, 864, 870, 883-890, 911, 920, 932). Not one opens a socket to
the real port. `TestClient` ships its own in-process WS implementation, which is
exactly the masking mechanism the post-mortem names:

> "`TestClient` … carries its own in-process WebSocket implementation, which is
> precisely why 112 phase-3 tests passed while the real server returned 404 on every
> upgrade."

7 of the 9 pass. The 2 that fail (`test_ws_authenticated_on_upgrade`,
`test_ws_fan_out_to_all_clients`) fail for reasons **unrelated** to the missing WS
library — see §6.

**There is no test in this file that would fail if the real `/ws` upgrade 404'd.**

### 2d. Mutation test: does removing `accept()` turn anything red?

I mutated `chronos/api/app.py:203` from `await websocket.accept()` to `pass` and ran
`TestWebSocket`. The run **hung** — it did not fail fast, it wedged until the 180 s
tool timeout, because `send_json` on an unaccepted socket blocks in the TestClient
portal rather than raising. That is itself the answer: **removing `accept()` produces
a hang, not a clean failure, and no `pytest-timeout` is configured** to convert the
hang into a red. File restored (`diff -q` clean, `await websocket.accept()` back at
line 203). A hang that no gate converts to a failure is functionally a passing test.

**Answer to "(c) is there any test that would fail if `accept()` were removed?" —
No. Not one, reliably.**

---

## 3. Route reachability: per-route classification (all 20, over real HTTP)

`test_all_routes_present` **crashes** rather than passing (§6, `'_IncludedRouter'
object has no attribute 'path'`), so registration is *not* even shape-checked. But
registration was never the point. I hit every route on the real server instead.

| # | Route | Real HTTP | Does real work? | Verdict |
|---|---|---|---|---|
| 1 | `GET /api/health` | 200 | yes | OK, genuinely open |
| 2 | `GET /api/events` | 200 `[]` | real query, empty DB | weak (empty-body only) |
| 3 | `GET /api/nodes` | 200 `[]` | real query | weak |
| 4 | `GET /api/buckets` | 200 real bucket rows | **yes** | OK — strongest route |
| 5 | `GET /api/briefing` | 200 real payload | yes | OK |
| 6 | `GET /api/search` | 200 `[]` | query runs | **weak** — empty DB, never asserts a hit |
| 7 | `GET /api/reminders` | 200 `[]` | real query | weak |
| 8 | `GET /api/timer` | 200 `null` | real | weak (null-tolerant) |
| 9 | `GET /api/timer/summary` | 200 zeroed totals | real | weak — asserts only field names |
| 10 | `GET /api/timer/presets` | 200 `[default 25/5×4]` | **yes** | OK |
| 11 | `POST /api/timer/presets` | 200 echoes input | persists | **weak — echoes back, never re-reads** |
| 12 | `GET /api/stats` | 200 zeroed payload | real query | weak |
| 13 | `GET /api/settings` | 200 `{}` | real | weak |
| 14 | `PUT /api/settings` | 200 | writes | weak — asserts the echo, not the DB |
| 15 | `POST /api/say` | 200 | **NO — "not yet implemented"** | **FAIL — A4, see §1** |
| 16 | `POST /api/commands` | 200 `success:true` | **NO — "not yet implemented"** | **FAIL — A5, see §1** |
| 17 | `POST /api/timer/start` | **500** | crashes | **FAIL — see below** |
| 18 | `POST /api/timer/stop` | 409 (no timer) | untested live | untested |
| 19 | `POST /api/keys/renew` | not probed live | rotates | untested live |
| 20 | `POST /api/voice` | 000 (hang) | **INDETERMINATE** | see §7 |

### 3a. `POST /api/timer/start` is a hard 500 in the product

```
POST /api/timer/start -> 500 {"detail":"Internal server error"}
```

Server traceback, verbatim:
```
File "/root/Chronos/chronos/api/routes.py", line 806, in timer_start
    _timer_session_to_dict(session),
File "/root/Chronos/chronos/api/routes.py", line 224, in _timer_session_to_dict
    "mode": session.mode.value if session.mode else None,
AttributeError: 'str' object has no attribute 'value'
```

`timer_start` **writes the row and then 500s while serialising it**:
```
>>> select id,label,mode,ended_at from timer_sessions
('39e9ddbd-…','t','stopwatch',None)
```
The session is persisted and the client is told 500. That is a data-integrity /
client-contract violation with no test at HTTP level.

Curiously the *second* start returns the correct 409, so the "one timer at a time"
rule works — but the success path of the route is broken and
`test_start_timer` / `test_second_timer_returns_409` / `test_stop_timer` are all
currently **red** for it (§6), so the suite is not hiding this one. It is simply
unfixed.

---

## 4. Tests that cannot fail (defect class (a))

| Line(s) | Test | Why it cannot fail |
|---|---|---|
| 405-412 | `test_install_key_redaction` | Body is three comments and an unused `logger = …`. Calls `install_key_redaction()` and asserts nothing. Literal self-admission: *"This test passes if install_key_redaction() doesn't raise"*. The comment at 412 says so outright. |
| 414-433 | `test_key_never_in_log_output` | Never inspects log output. Adds a `StreamHandler` to a logger, calls `redact_key_from_url(url)` **directly** and asserts the *pure function's* output. This is a duplicate of line 377's unit test wearing an integration test's name. The `logger.info` at 428 goes to stderr and is never captured or asserted. |
| 573-578 | `test_all_routes_present` | Registration check only — the exact "shape check" the proposal bans. It is also **crashing** (`'_IncludedRouter' object has no attribute 'path'`, because `include_router` now mounts an `_IncludedRouter` rather than flattening), so it is currently neither a shape check nor a red-for-the-right-reason. |
| 580-589, 659-667 | `test_health_*` | Only real assertions in the whole REST block. Health is the one route that actually works. |
| 841-845 | `test_ws_authenticated_on_upgrade` | Body is `with client.websocket_connect("/ws"): pass` with the comment *"Should not reach here — auth fails"*. There is **no assertion in the body at all**. It passes if the connection succeeds *or* raises; only the context-manager exit can fail. It is currently red for an unrelated reason (§6). |
| 909-916 | `test_ws_client_hello` | Sends `hello`, asserts nothing. `app.py:224-227` handles `hello` with `pass`. Would pass against a server that ignores the frame entirely. |
| 918-925 | `test_ws_client_say` | Sends `say`, asserts nothing. `app.py:228-229` handles `say` with `pass`. Same. |
| 927-940 | `test_ws_one_connection_per_client` | Asserts nothing. The docstring concedes *"This is a design constraint — the hub maintains a set of clients"* then tests that two connections exist. Tests `websocket_connect`, not Chronos. |
| 1037-1046 | `test_smoke_script_exists`, `test_smoke_script_is_executable` | Existence/mode checks — banned class. `test_smoke_script_is_executable` also **silently passes** if the file does not exist (`if smoke_path.exists():` wraps the only assertion). |
| 1048-1063 | `test_smoke_script_boots_server` | Passes `port 0` with the comment *"(may not work)"*, 30 s timeout, and asserts only `returncode == 0`. Red today (§6). |
| 714-724 | `test_say_creates_events` | **Conditional assertion:** `if data.get("committed"): assert len(events) > 0`. When the stub returns `committed: false`, the body never executes. This test passes *precisely because the feature is broken*. Its docstring claims *"One English sentence commits a real event, read back out of SQLite"* — it does neither, and never touches SQLite. |
| 503-507 | `test_create_app_default_path` | Asserts an env var round-trips into `app.state`. Red today from a non-idempotent migration (§6). |

### 4a. `test_all_routes_present` / `create_app` DDL hazard

The fixture helper at 60-78 documents the cause honestly:

> "`run_migrations()` is not idempotent (it raises 'table nodes already exists' on a
> second run)."

Confirmed live: `test_create_app_default_path` fails with
`sqlite3.OperationalError: table nodes already exists` because `CHRONOS_DB=/tmp/test-chronos.db`
persists between runs. **A test that fails on its second invocation is not a test.**

---

## 5. Auth gaps (defect class (d))

**Is `/api/health` the only unauthenticated route? NO.**

Every `/api/*` route is correctly gated — I confirmed 401 on `/api/nodes` unauthenticated
over real HTTP. But the spec says *"`/api/health` is the only unauthenticated route"*,
and the app serves four more, all 200 with no key:

```
$ curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8199/openapi.json   -> 200
$ curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8199/               -> 200
$ curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8199/docs           -> 200
$ curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8199/redoc          -> 200
```

`/openapi.json` publishes the full authenticated API surface to an unauthenticated
client. No test in the file asserts anything about these paths. **Severity: MEDIUM**
(it is a real §3 deviation with zero coverage, though exposure is bounded to schema
metadata).

**Key-in-query-string never logged: PROVEN WORKING — but only by luck of scope.**

The post-mortem's B11/B12 pair is genuinely fixed at the source: `auth.py:143-158`
installs a **`logging.setLogRecordFactory`** factory that rewrites `msg` *and* `args`,
rather than a logger-attached filter. That is the correct remedy and it is called from
`app.py:139`. I proved it end-to-end against the real server, not in-process:

```
$ curl "http://127.0.0.1:8199/api/nodes?key=$K"
$ grep -c "$K" /tmp/audit3.log
1                      <- the only occurrence is the deliberate first-run print
$ grep "api/nodes" /tmp/audit3.log | tail -1
INFO:  127.0.0.1 - "GET /api/nodes?key=*** HTTP/1.1" 200 OK
```

Good — the record factory reaches uvicorn's own access logger. **However:**

- The *header* leak (B12) is **NOT fixed in production code**, only in tests.
  `redact_key_from_url` (`auth.py:122-126`) matches `?key=` and `&key=` and nothing
  else. `install_key_redaction`'s factory runs `redact_key_from_url` over `args`, so a
  logged `X-Chronos-Key` header dict is **not** redacted. `test_x_chronos_key_header_never_logged`
  is currently **RED** (§6) — the test is right and the code is wrong. No `log_capture`
  handler exists for uvicorn in the product, so this is a latent leak, not an
  observed one.
- My mutation test proves the redaction tests *do* have teeth for the query-string
  path. I inserted `return  # MUTANT` as the first line of `install_key_redaction`
  (restored immediately, `diff -q` clean):
  ```
  2 failed, 6 passed
  FAILED TestKeyRedactionInLogs::test_query_string_key_redacted_in_log
  FAILED TestKeyRedactionInLogs::test_x_chronos_key_header_never_logged
  ```
  So `test_install_key_redaction` and `test_key_never_in_log_output` stayed green under
  a fully neutered implementation — direct proof they cannot fail.

**Key renew: rotation tested, disconnection NOT tested.**

- `TestKeyRenew` covers: new key differs, hash updated, old key stops verifying
  (`test_renew_old_key_stops_working`), renew requires auth. Those are real.
- §3 says *"key-renew rotates the key **and disconnects every client**."* The route
  does call `await hub.close_all(code=4001, reason="key rotated")` (`routes.py:1287`),
  but **no test connects a client and asserts it is disconnected by a renew.** The
  hub-level `test_hub_close_all` tests `close_all` in isolation with `AsyncMock`s.
  So the *composition* — renew ⇒ real client dropped — is untested, and the gap is
  exactly the kind of wiring gap Class A is made of. **Severity: MEDIUM.**

**503-vs-401 divergence.** `test_require_key_no_hash_returns_503` expects 503 when no
hash is stored. The spec (§3) says only *"Everything else is 401 without a valid key."*
503 is a defensible reading (key not yet generated ⇒ server not ready) but it is the
test author's invention, not spec text. Currently red anyway (§6). **Low.**

---

## 6. The 20 failures + 7 errors, classified

`TEST BUG` = the test is wrong or unrunnable. `CODE BUG` = implementation contradicts
the spec. `TEST INFRA` = the test cannot execute in this environment.

### FAILURES (20)

| Test | Class | Citation / evidence |
|---|---|---|
| `TestRequireKey::test_require_key_success` | **TEST INFRA** | `async def functions are not natively supported. You need to install … pytest-asyncio`. `pytest-asyncio` is **not** in `[project.optional-dependencies] dev` (only `pytest`, `ruff`) and `asyncio_mode = "auto"` — required by the proposal's environment facts — is **absent from `pyproject.toml`**. All 5 fail identically. |
| `TestRequireKey::test_require_key_missing_returns_401` | **TEST INFRA** | same cause |
| `TestRequireKey::test_require_key_wrong_key_returns_401` | **TEST INFRA** | same cause |
| `TestRequireKey::test_require_key_no_hash_returns_503` | **TEST INFRA** | same cause |
| `TestRequireKey::test_require_key_query_string_fallback` | **TEST INFRA** | same cause |
| `TestRequireKeyWebSocket::test_require_key_ws_success` | **TEST INFRA** | same cause |
| `TestRequireKeyWebSocket::test_require_key_ws_missing_returns_4001` | **TEST INFRA** | same cause |
| `TestRequireKeyWebSocket::test_require_key_ws_wrong_key_returns_4001` | **TEST INFRA** | same cause |
| `TestAppFactory::test_create_app_default_path` | **TEST BUG** | `sqlite3.OperationalError: table nodes already exists`. Test leaves `/tmp/test-chronos.db` behind; non-idempotent `run_migrations()` poisons reruns (§4a). Not idempotent ⇒ not a test. |
| `TestRestRoutes::test_all_routes_present` | **TEST BUG** | `AttributeError: '_IncludedRouter' object has no attribute 'path'`. Iterating `app.routes` assumes flattening that `include_router` no longer provides. Even when fixed it is a registration-only shape check (§4). |
| `TestPostApiSay::test_say_commits_unambiguous_commands` | **CODE BUG** | `assert data["committed"] is True` → `E assert False is True`. Real HTTP shows `"message":"Intent pipeline not yet implemented"` (`routes.py:279`). **A4.** This is the test working correctly. |
| `TestTimer::test_start_timer` | **CODE BUG** | `AttributeError: 'str' object has no attribute 'value'` at `routes.py:224`. Real HTTP: 500. Row persisted, client told 500 (§3a). |
| `TestTimer::test_second_timer_returns_409` | **CODE BUG** | same `_timer_session_to_dict` crash on the *first* start, so the test never reaches its 409 assertion. |
| `TestTimer::test_stop_timer` | **CODE BUG** | same crash |
| `TestTimer::test_get_running_timer` | **CODE BUG** | same crash |
| `TestWebSocket::test_ws_authenticated_on_upgrade` | **TEST BUG** | `starlette.websockets.WebSocketDisconnect`. The test has **no assertion in its body** (841-845); it asserts only that its `with` block completes. It is a naked `websocket_connect` whose docstring contradicts its behaviour. Delete or rewrite. |
| `TestWebSocket::test_ws_fan_out_to_all_clients` | **TEST BUG** (compound) | Blocked by the `timer_start` 500 (§3a) — the REST mutation it uses to trigger a broadcast is broken. Also unrunnable in principle: `build_state_message` is called with hardcoded empty lists (`app.py:209-215`), so fan-out is driven by the hub, not by state. |
| `TestSmokeScript::test_smoke_script_boots_server` | **CODE BUG (test partially right)** | `smoke.sh` runs `chronos serve` from `PATH`, not the venv. **The script itself is the defect:** it checks only `/api/health`. The phase doc demands health, 401-no-key, 401-wrong-key, 200-good-key, *one sentence → real event read from SQLite*, and 409 on a second timer. The script asserts **one** of those seven. So even a passing `smoke.sh` would not satisfy "Done means". |
| `TestKeyRedactionInLogs::test_x_chronos_key_header_never_logged` | **CODE BUG** | Test is correct per B12; `redact_key_from_url` (`auth.py:122-126`) handles only `?key=`/`&key=`, never headers. Real latent §3 violation. |
| `TestVoiceRoute::test_voice_no_audio_returns_400` | **TEST BUG (narrow)** | `E assert 422 == 400`. §8.2 specifies `audio → transcript` and **no status code**; 422 is FastAPI's own validation response for a missing required multipart field and is more correct than 400. The test encodes an author-invented number. (Also see §7 — the *other* voice test passes while the route is broken in production.) |

### ERRORS (7) — all `TestRealtimeHub`, all one fixture

```
def clock():
    from chronos.contracts import Clock
    return Clock()
E   TypeError: Protocols cannot be instantiated
```

`chronos.contracts.Clock` is a `Protocol`. The fixture instantiates it. **TEST BUG** —
and a namespace collision: `clock` here means the contracts Protocol, while
`app.state.clock` elsewhere means a concrete runtime clock. All 7 hub tests
(`test_hub_connect`, `test_hub_disconnect`, `test_hub_broadcast`, `test_hub_close_all`,
`test_hub_build_state_message`, `test_hub_build_patch_message`, `test_hub_build_timer_message`)
never execute. **Net effect: the entire `RealtimeHub` class has zero effective
coverage** — fan-out, broadcast-to-all, and message construction are all untested in
practice. Compounding it, all 7 use the C15 anti-pattern
`asyncio.get_event_loop().run_until_complete(...)`, which the proposal flags as removed
in Python 3.14 — this host *is* 3.14.

---

## 7. `POST /api/voice`: the "unverifiable because of concurrent edit" item

Over real HTTP, `POST /api/voice` returned curl code `000` (no response, connection
closed / hang) for both an unsupported type and `audio/wav`, twice, with no new log
line. `voice.py:56-59` does `from chronos.ai.providers.adapter import build_stt_adapter`
— and `git status` showed `chronos/ai/adapter.py` **deleted** at that moment by the
concurrent restructuring agent.

**INDETERMINATE.** I am not attributing this to phase 3. But the test-side finding
stands regardless and is the point: `test_voice_no_audio_returns_400` (red, §6) and
`test_voice_unsupported_format_returns_415` (**passing**) both stop at the auth/validation
gate. **There is no test that a valid audio upload returns a `transcript`** — so a route
that 500s or hangs on every real request is completely invisible to this suite.

---

## 8. The one thing this suite does genuinely well

Credit where due, and it is not nothing:

- Argon2 storage/verification is real: `test_store_instance_key_uses_argon2id` asserts
  `$argon2id$`, `m=65536`, `t=2`, `p=1` against an actual hash. Cannot pass against a stub.
- `test_plaintext_key_never_in_settings` reads the raw `settings` table and asserts the
  plaintext is absent. Real DB, real assertion.
- `test_redact_key_from_url_*` are genuine pure-function tests, and my mutation proves
  `install_key_redaction`'s record factory is load-bearing (removing it goes red).
- `test_hub_broadcast` uses `AsyncMock` and asserts `send_json` was called once per
  client with the exact message — a correct assertion, marred only by the broken
  `clock` fixture.

The failure mode is not that these tests are bad. It is that **they are the only 6
out of 108, and the 102 others are shape checks.**

---

## 9. Severity tally

**BLOCKER (4)**
1. `POST /api/say` ships the `"Intent pipeline not yet implemented"` stub in the running
   product; `committed: false`, zero rows in `events`. A4, unregressed. §1.
2. `POST /api/commands` ships `"Tool dispatch not yet implemented"` behind
   `success: true`. A5, unregressed. §1.
3. `websockets` absent from `pyproject.toml`; the real server 404s **every** `/ws`
   upgrade. B5 environment, unregressed, masked by TestClient. §2.
4. Zero tests execute against the real server over real HTTP except one that checks
   `/api/health` only. The proposal's Layer 3 is **not implemented**.

**HIGH (6)**
5. `TestRealtimeHub` — 7 errors, `Clock` Protocol instantiated. The hub has zero
   effective coverage. §6.
6. `pytest-asyncio` missing and `asyncio_mode = "auto"` missing ⇒ 8 auth tests cannot
   run. §6.
7. `POST /api/timer/start` returns 500 in the product while persisting the row. §3a.
8. `test_say_creates_events` uses `if data.get("committed"):` — passes because the
   feature is broken, and never reads SQLite despite its docstring. §4.
9. `test_install_key_redaction` asserts nothing, self-documented as such. §4.
10. `test_key_never_in_log_output` never inspects a log; duplicates a unit test. §4.

**MEDIUM (8)**
11. `test_ws_client_hello` / `test_ws_client_say` / `test_ws_one_connection_per_client`
    assert nothing. §4.
12. `test_ws_authenticated_on_upgrade` has no assertion in its body. §4.
13. `test_all_routes_present` crashes (`_IncludedRouter`) and is a registration-only
    check even when fixed. §4, §6.
14. `smoke.sh` checks 1 of the 7 things the phase doc's "Done means" requires, and
    invokes bare `chronos` instead of the venv. §6.
15. Key-renew ⇒ **client disconnection** is implemented but untested. §5.
16. `X-Chronos-Key` header value is not redacted by `redact_key_from_url`; B12 latent.
    §5.
17. `/openapi.json`, `/`, `/docs`, `/redoc` are unauthenticated 200s, contradicting
    *"`/api/health` is the only unauthenticated route"*. Untested. §5.
18. No `pytest-timeout`: removing `accept()` produces a **hang**, not a failure. §2d.

**LOW (6)**
19. `test_create_app_default_path` is not idempotent; fails on rerun. §4a.
20. `test_voice_no_audio_returns_400` demands 400 where §8.2 specifies nothing and 422
    is returned. §6.
21. `test_require_key_no_hash_returns_503` invents a status the spec does not state. §5.
22. `test_smoke_script_exists` / `_is_executable` are existence checks; the latter
    silently passes when the file is absent. §4.
23. All 7 `TestRealtimeHub` tests use the C15-removed
    `get_event_loop().run_until_complete()`. §6.
24. Suite runtime 109 s is dominated by one 30 s subprocess smoke call and 9 in-process
    ASGI portals — cost spent without real-server coverage.

**Tests with no coverage at all:** a successful authenticated `/ws` upgrade against a
real socket; the 409-second-timer path *over HTTP with a working start*; key-renew
client eviction; a valid `/api/voice` upload producing a transcript; `/api/search`
returning a hit; any read-back from SQLite after a write via any route other than
timer sessions.

---

## 10. Recommendations (report only — I changed nothing)

1. Add `websockets>=12` to `[project.dependencies]` (or `uvicorn[standard]`). **Nothing
   else in this list matters until the realtime feature exists in the product.**
2. Delete `test_install_key_redaction`, `test_key_never_in_log_output`,
   `test_ws_client_hello`, `test_ws_client_say`, `test_ws_one_connection_per_client`,
   `test_ws_authenticated_on_upgrade` as written. Replace with assertions or nothing.
3. Add a real-HTTP test module (Layer 3) that boots `chronos serve` on a throwaway DB and
   hits all 20 routes with no key / wrong key / good key. Use it as the sole gate for
   route reachability.
4. Wire the intent pipeline into `/api/say` and the tool dispatcher into `/api/commands`;
   then make `test_say_creates_events` unconditional **and** make it read
   `select id,title,starts_at_ms from events` out of SQLite, exactly as the phase doc
   says. Delete the `if data.get("committed")` guard.
5. Add `pytest-asyncio` to dev deps and `asyncio_mode = "auto"` to
   `[tool.pytest.ini_options]`.
6. Fix the `clock` fixture — use a concrete clock implementation, not the Protocol — and
   convert the 7 hub tests to `asyncio.run`.
7. Rewrite `smoke.sh` to assert all seven checks and call the venv's `chronos`, not
   `PATH`'s.
8. Fix `redact_key_from_url` to cover `X-Chronos-Key` in headers and dict-shaped `args`.
9. Add a test that key-renew evicts a live WebSocket client.
10. Lock down `/openapi.json` and `/docs` (auth or explicit disable), or amend §3.