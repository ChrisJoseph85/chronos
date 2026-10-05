# Chronos — consolidated brief (contracts, decisions, behaviour, process)

Sources: `docs/server/{contract-and-interfaces,decisions,scheduling-behaviour,tickets,questions-for-user}.md`
Compiled: 2026-10-03. Authority order: `docs/Chronos.md` > frozen contracts > these docs.

---

## 1. Frozen API surface (build to this, do not relitigate)

### CLI
`chronos serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]` ·
`setup` (interactive) · `key-renew` · `db-upgrade` · `token-cost [--days 7]` · `export` · `say -` ·
`get day|timer|briefing`
Terse, no prompts, pipe-safe. **Non-negotiable: the console script must actually execute** — the last
build's entry point pointed at a nonexistent module (690 green tests, server could not boot). Add a
contract test that runs the installed script.

### Auth (§3)
- One **instance key**, generated on first run, printed once, stored **Argon2-hashed**.
- Required on **every** REST request, WS upgrade, MCP call, CLI command.
- Header `X-Chronos-Key`; `?key=` query fallback for header-less MCP clients.
- `/api/health` is the **only** unauthenticated route (so clients can report "server down" vs. spinning).
- Key must **never** reach a log line (header *or* query) — uvicorn logs full headers, redact there too.
- Admin = anyone holding the key (ruling 23).

### REST routes
```
POST /api/say            {text} -> proposal
POST /api/commands       raw tool dispatch
POST /api/voice          multipart audio -> STT
GET  /api/events         ?from=<ms>&to=<ms>
GET  /api/nodes          ?parent=<id>
GET  /api/buckets        level / date
GET  /api/briefing       ?date=<YYYY-MM-DD>
GET  /api/search         ?q=
GET  /api/reminders
GET  /api/timer          POST /api/timer/start  POST /api/timer/stop
GET  /api/timer/summary  GET|POST /api/timer/presets
GET  /api/stats          GET|PUT /api/settings   POST /api/keys/renew
GET  /api/health         (open)
```

`/api/say` returns a **proposal, never a silent commit**:
`{intent, tool_calls[], proposal_id, committed:false, events[], message}`.
Must work with **zero provider keys** (offline parser is the floor; keys only improve models). An
ambiguous sentence proposes **and** asks, at most one `question`. An unimplemented endpoint must
**not** return `success: true`.

### WebSocket
`/ws`, authenticated **before** `accept()`; unauthenticated upgrades close **4001**. Must call
`await websocket.accept()` or the upgrade 404s. **`websockets` must be a declared dependency** —
uvicorn ships none; Starlette `TestClient` has its own, which masked 112 green tests against a server
that 404'd every upgrade. Pushes: state, timer, proposal, question.

### Clients are out of scope
Browser UI and Android app are separate projects outside this repo. The server's only obligation: the
exposed API is a contract — endpoints, auth, response shapes must not drift.

---

## 2. Landmine list (each one previously shipped as a green suite + broken product)

| Area | Requirement | Failure it prevents |
|---|---|---|
| Entry point | console script executes | 690 tests passed, server unbootable |
| Deps | `websockets` declared | 112 tests passed, every WS upgrade 404'd |
| **FTS** | `node_fts` is external-content (`content=''`); `rowid` **INTEGER** — TEXT uuid mapped deterministically (SHA-256 → 62-bit) | TEXT uuid rowid → `datatype mismatch`, **nothing indexed, search empty forever** |
| Vec | degrade gracefully when `sqlite-vec` absent — keywords still work | optional index breaking core writes |
| Threading | `DatabaseEngine.conn` is **thread-local**; resolve per call, never capture the boot-thread conn into `app.state`/repo | `sqlite3.ProgrammingError` on every worker request |
| Migrations | all DDL `CREATE ... IF NOT EXISTS` + `schema_version` | second boot against existing DB fails |
| Enums | round-trip via enum constructor (`EventKind(row["kind"])`) | five uppercase defaults shipped raw-TEXT `.value` crashes |
| Buckets | Y→M→W→D, 10y, ~4,300 rows, idempotent seeding; **week 1 of year 1 starts in Dec of prior year** → parent month must exist, else clamp the week, never drop it | missing/dangling weeks |
| Review series | **bounded** — `max_count` and/or `ends_on_ms`, enforced at repo **and** schema | unbounded series |
| Series state | lowercase `active\|retired\|cancelled`, spec declares **no CHECK** | |
| Timers | one at a time — **unique partial index**, not just route logic | |
| Timer semantics | stopwatch **ignores** target and its time **counts** toward totals; pomodoro **breaks excluded** | easy inversion, wrong totals |
| Events | snap to minute grid; day boundaries from `instance.timezone` (never hardcoded UTC); overlap **half-open** (`from` incl, `to` excl) | |
| Tags | never attach to **projects** (§4.1) — tasks/subtasks only | |
| Exceptions | never broad-`except` a query; catch only "table missing/unusable" and **log** | v1 search silently returned nothing via bare `except Exception` |

---

## 3. Frozen rulings — 62 spec ambiguities, all approved

**Contracts freeze (Phase 0), 8:**
1. Add `node_links` table — `(source_id, target_id, PK(source_id,target_id))`, FKs → `nodes(id)` ON DELETE CASCADE (needed by `link_nodes`).
2. `offsets_days`: for `tier != "custom"` the tool uses tier defaults (hard `[1,2,4,8,16]`, medium `[3,7,15,30]`, easy `[10,30,90]`); stored value always reflects offsets actually used.
3. `Event.bucket_id` nullable at creation, set by scheduler at placement.
4. `TimerSession.target_ms` for pomodoro = focus duration; break from preset (default 25/5 ×4).
5. `AuditEntry.id` = native `INTEGER PRIMARY KEY` (rowid alias).
6. `Reminder.offset_min`: positive = **before** start, 0 = at start; `fire_at_ms = start_ms - offset_min*60000`.
7. `Schedule.weekdays` = `[1..7]` ISO ints (1=Mon).
8. `Bucket.seq` = 1-based ordinal in parent, **not** capped at 4 (the "1..4" meant the 4 levels).

**Phase 2 — AI layer (10):** retry cycles adapters in `TEXT_PROVIDERS` order ("Cloudflare" = Groq's CF front) · STT single adapter, no failover, error propagates · no embeddings failover in P2 · first attempt synchronous, retries background · token count = `len(text)//4` estimate for packing, provider counts for cost · lookup-only = no mutation tool calls · verify model = last adapter (typically free NIM) · cost table = SQLite `token_cost` in main DB · similarity threshold configurable, default 0.85 · reminder offset included in `create_event`, confirmed on accept.

**Phase 3 — server (8):** `/api/say` auto-commits unambiguous, proposes on conflict · `/api/say`=NL, `/api/commands`=raw tools · WS auth via header/query with hello-key fallback · `GET /api/timer` w/o `node_id` returns running timer regardless of node · `PUT /api/settings` **merges** · `POST /api/timer/presets` **appends** · voice accepts webm/opus, mp3, wav, ogg · `/api/health` returns status, version, db_path, uptime_seconds.

**Phase 4 — interfaces (8):** raw CLI key in `~/.chronos/key` (0600), hash in DB · `chronos export` JSON only in v1, CSV deferred to Milestone 4 · `chronos say` errors+exits if server down · MCP = HTTP at `/mcp` · HUD = top nav bar with anchors · calendar DnD = HTML5 DnD + edge handles · WS reconnect exponential backoff 1–30s · `get` subcommands limited to day/timer/briefing.

**Phase 5 — features (10):** reuse threshold 0.85 configurable · `check_conflict` returns `array[SearchResult]` (backward-compatible) · questions stored in audit table with `action="question"` · `provider_prices` seeded at deploy time · briefing = query-based assembly, AI may enhance · `token_costs` records every attempt, stats aggregates by day · audit viewer limit/offset default 100 · CSV timestamps ISO-8601 with offset · `NodeSearch`↔`NodeRepo` wiring is a P1 detail · `Briefing` dataclass internally, dict at API boundary.

**Phase 6 — deploy (8):** pin `python:3.14.7-slim-bookworm` · multi-arch `linux/amd64` + `linux/arm64` via buildx · embedding download: log one line before first download, `llama-embedding` renders its own progress bar · Termux packages `python git rust binutils libsqlite` · Windows documented as untested, path `pip install -e .` + `chronos serve` · no registry push this phase · `scripts/backup.sh` with timestamped copies · write `docs/docker.md` alongside `docs/termux.md`.

**All six phase proposals frozen → Stage 2 (build) may begin.**

---

## 4. Rulings carried forward from v1

- **Timer start while one runs → refuse**, not replace (user chose this directly). AI asked to do it must **ask first**: continue the running one, or stop it and start the new.
- **Tags never on projects** (§4.1). "Tag a timer to a project" = time **roll-up** (§4.7): logged time counts toward the project by walking `parent_id` to the nearest ancestor project. No spec change.
- **`bucket_id` lives on `events`, not `nodes`** (§4.2). A test that adds the column is wrong.
- **Hardcoded API key in a test is never acceptable.** Tests that sent literal `"test-key"` expecting 200 were all wrong. Correct fix: mint a key and set `app.state.api_key_hash`. Making the app accept a literal would be a backdoor.
- **`create_app(db_path=None)` signature is frozen** — load-bearing for CLI, smoke script, tests. A test inventing `create_app(conn, store, key=...)` must be corrected.
- **Optional search index must never break a core write** — absent table logs and continues; `create_node` succeeds without `node_fts`.
- **The Manager is a last resort, not a first call.** Only a Proposer escalates to the Manager; Test/Code/Mediators report to their Proposer. An escalation arriving over a Proposer's head is refused and sent back down **even when the answer is obvious** — answering teaches the build that skipping the ladder works.
- **Two agents independently flagging a major fault ⇒ the proposal is wrong.** Test + Code agreeing against the plan means re-think; Proposer stops and gets Manager confirmation before continuing. The only escalation a Proposer raises without a 2:2.

---

## 5. Scheduling behaviour (the gap that made the product feel broken)

This doc is **not project-authoritative** — `docs/Chronos.md` wins. Behaviour was missing even though
`/api/say` returned sensible-looking proposals.

### Core loop
1. User speaks/types a sentence.
2. AI parses to a task and files it into a time bucket (Y/M/W/D).
3. AI judges whether the sentence carried enough time info:
   - **enough** → propose a concrete slot, commit on accept;
   - **not enough** → propose a slot **and** ask one clarifying question.
4. Never committed silently — accept or reject.
5. Anything unconfirmed waits in the **briefing bar, the landing view**, first thing on return.

**Underlying rule: the AI never invents a commitment. Silence is not acceptance.**

### Current gap table
| Gap | Today | Required |
|---|---|---|
| Ambiguous sentence | guesses a concrete time, treats it as a slot | propose **and** ask (`ask_question`) |
| Clarifying question | never emitted by `/api/say` | at most one per proposal |
| Proposal visibility | no server-side support | not implemented at all |
| Briefing | a screen you navigate to | landing view, unconfirmed first |
| No silent commit | `committed:false` but a guess looks accepted | guessed slots **visibly marked unconfirmed** |

### Clarification rules
At most **one** question per proposal · only when needed · **still show a concrete suggested time** so
the user can accept as-is · answerable in one tap (accept / reject / pick) · **queued** into the
briefing, not blocking · **budgeted** — `ClarificationBudget` already exists in
`chronos/ai/briefings.py` with per-day budget and day rollover; do not ask on every sentence.

### Timezone (explicit user requirement)
`chronos setup` must prompt for **TIMEZONE** after STT → text providers → embeddings. Today setup covers
providers/embeddings only, and routes **hardcode `tz = UTC`**, so `instance.timezone` is ignored for all
day-boundary math (§7.1) and a 4pm task lands at the wrong wall-clock hour. **Two changes required:**
(1) setup prompts; (2) routes read `app.state.timezone` instead of `tz = UTC`. Validate a real IANA zone
(`America/New_York`, `Europe/London`), reject nonsense clearly, and **confirm the system zone** rather
than silently defaulting to UTC. Asking for a timezone the server then ignores is worse than not asking.

### Client obligations (mirrors state, does not compute it)
Briefing bar is the landing view, unconfirmed proposals + pending questions first · guessed/uncertain
slots visibly marked unconfirmed, not styled like confirmed ones · AI bar on **every** screen (a question
must never require navigating to a tab) · after accept/reject, **re-read from the server**, never assume.

### Acceptance criteria
1. "schedule the review" → proposal **with a question**, not a silently-guessed confirmed slot.
2. "DB review tomorrow 4pm for 45 mins" → proposal, **no** question.
3. Nothing committed without explicit acceptance.
4. An unconfirmed proposal survives restart and is the first thing shown.
5. Accepting resolves it and removes it from the briefing bar.
6. `chronos setup` asks for timezone; value validated and stored.
7. Non-UTC timezone: a 4pm task reports as 4pm local from `/api/events` and `/api/briefing`.
8. Clarification budget respected.

**Red tests already exist** in `tests/acceptance/test_say_flow_acceptance.py`, written before the
wiring, several still red — treat them as the **specification of record**.

---

## 6. Escalation process (tickets)

Disagreements between Test and Code agents climb **one rung at a time** as a written ticket. Blank
field ⇒ not a conflict yet, sent back. Template fields: DISPUTED (one sentence, not a narrative) ·
POSITIONS (each with spec §) · ALREADY TRIED (which rungs, what was said, why it didn't settle) ·
EVIDENCE (exact assertion verbatim, actual command output not a summary, `file:line`) · MY READING
(raiser's own view; receiver may disagree).

- **R1 Proposer** — default destination; expected to absorb the large majority.
- **R2 Mediator** — only if Proposer can't settle; rules code-wrong or test-wrong; **binding** on both.
- **R3 Vote** — only if Proposer and Mediator disagree; all four phase agents vote; **3:1 carries**.
- **R4 Proposer rethinks** — Test and Code *independently* agree something is majorly wrong ⇒ fault
  likely in the proposal; Proposer stops, rethinks, gets **Manager** confirmation. Only Proposer
  escalation without a 2:2.
- **R5 Manager** — on a 2:2 or failed rethink; resolves, or forwards to the user when it turns on
  product intent rather than correctness.

Rules: one rung at a time (tickets raised two levels up are refused) · no agent weakens an assertion to
make a suite pass, at any rung · no agent edits a test it did not write except under a Mediator ruling ·
Manager's ruling is final and gets recorded in `docs/decisions.md` · **if the spec itself is ambiguous,
say so and escalate** — do not guess, and do not let a majority vote invent product intent; that goes to
the user.

---

## 7. Open questions for the user

**None.** `docs/server/questions-for-user.md` is empty. Per `docs/manager.md` §8 the Manager appends
there when a human decision is needed but **does not block**: it takes the recommended default, marks
the work provisional, and continues — revisiting it when the user answers.

---

## 8. Build-order takeaway

Contracts + phases 0–6 all frozen; Stage 2 (build) is unblocked. Highest-risk items, in order:
(1) the `/api/say` clarification + proposal-visibility + briefing-landing path (8 red acceptance tests
are the spec of record); (2) timezone plumbing (setup prompt + kill hardcoded `tz = UTC` in routes);
(3) infra landmines that have each shipped green suites against a broken server — entry point, declared
`websockets` dep, INTEGER `rowid` FTS5, thread-local connections, idempotent migrations, enum
round-tripping.
