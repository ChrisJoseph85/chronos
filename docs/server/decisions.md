# Decisions log

Every escalated conflict, its ruling and the reasoning. The next session must not
relitigate these.

Format: **date — what was disputed — ruling — why.**

---

## Carried forward from v1

These were resolved during the v1 build and remain valid. They are recorded here
so the v2 build does not rediscover them the hard way.

**Timer, start while one is running.** *Ruling: refuse.* Starting a timer while
another runs returns a clear client error, it does not silently replace the
running one. The user was asked directly and chose "refuse" over "replace".
The AI, when asked to start a timer over a running one, **asks first** — continue
the running one, or stop it and start the new one.

**Tags on projects.** *Ruling: follow the spec — tasks and subtasks only.*
`Chronos.md` §4.1 says tags apply to tasks and subtasks, never to projects. The
user's request for "tag a timer to any project" was clarified as the **time
roll-up** (§4.7), not project tagging: a task's logged time counts toward its
project by walking `parent_id` up to the nearest ancestor project. No spec change.

**`bucket_id` lives on `events`, not `nodes`.** A test author added `bucket_id` to
`nodes`, claiming a spec ambiguity. It is not ambiguous: §4.2 puts `bucket_id` on
`events`. A test that adds the column is wrong.

**A hardcoded API key in a test is never acceptable.** Three separate tests sent a
literal key (`"test-key"`, `"test-key-123"`) and expected 200. All three were
wrong: §3 requires the real generated instance key. The correct fix is for the
test to mint a key and set `app.state.api_key_hash` — never for the app to accept
a literal. Making the app accept one would be a backdoor.

**`create_app`'s signature is frozen.** `create_app(db_path=None)` is load-bearing
for the CLI, the smoke script and the tests. A test that invents
`create_app(conn, store, key=...)` is wrong and must be corrected.

**An optional search index must never break a core write.** Indexing a node into
FTS/vec is best-effort: an absent table logs and continues. A schema without
`node_fts` must still allow `create_node` to succeed.

**Broad `except` around a query is a bug waiting to happen.** v1's search silently
returned nothing because a bare `except Exception` swallowed an argument error.
Catch only the errors that mean "table missing/unusable", and log them.

**The Manager is a last resort, not a first call.** Only a Proposer escalates to
the Manager. Test agents, Code agents and Mediators report to their Proposer.
An escalation that arrives over a Proposer's head is refused and sent back down,
even when the answer is obvious — answering it teaches the build that skipping the
ladder works. Every escalation carries a ticket (`docs/tickets.md`) with what is
disputed, both positions, **what has already been tried**, and the evidence.

**Two agents independently flagging a major fault means the proposal is wrong.**
If the Test agent and the Code agent agree, against the plan, the fault is probably
in the Proposer's own proposal rather than the implementation. The Proposer must
stop, rethink, and get the Manager's confirmation before work continues. This is
the only escalation a Proposer raises without a 2:2.

---

## v2

**2026-10-03 — Phase 0 contracts freeze: 8 spec ambiguities ruled.**

The Phase-1 Proposer flagged 8 ambiguities in the spec during the contracts
proposal. All 8 were reviewed and ruled as follows:

1. **`node_links` table** — The spec mentions `node_links` (§4.1) but gives no
   DDL. **Ruling: add the table.** `(source_id, target_id, PRIMARY KEY
   (source_id, target_id))` with FKs to `nodes(id)` ON DELETE CASCADE. The
   `link_nodes` tool (§5.5) requires it.

2. **`offsets_days` for non-custom tiers** — When `tier != "custom"`, the
   `schedule_series` tool ignores `offsets_days` and uses the tier defaults
   (hard `[1,2,4,8,16]`, medium `[3,7,15,30]`, easy `[10,30,90]`). The stored
   `offsets_days` always reflects the actual offsets used. **Ruling: approved.**

3. **`Event.bucket_id` timing** — Nullable at creation, set by the scheduler
   when the event is placed. **Ruling: approved.**

4. **`TimerSession.target_ms` for pomodoro** — `target_ms` is the focus
   duration; break duration is derived from the pomodoro preset (default
   25/5 x 4). **Ruling: approved.**

5. **`AuditEntry.id` autoincrement** — Use SQLite's native `INTEGER PRIMARY KEY`
   (rowid alias) behavior. **Ruling: approved.**

6. **`Reminder.offset_min` sign convention** — Positive = before start (e.g., 10
   = 10 minutes before), 0 = at start. `fire_at_ms = event.start_ms -
   offset_min * 60000`. **Ruling: approved.**

7. **`Schedule.weekdays` JSON format** — Stored as `[1..7]` ISO weekday ints
   (1=Monday, 7=Sunday). **Ruling: approved.**

8. **`Bucket.seq` range** — `seq` is the 1-based ordinal within the parent, not
   capped at 4. The "1..4" in the spec refers to the 4 levels, not a cap on
   seq values. **Ruling: approved.**

All rulings are consistent with the spec text and the phase-1 doc. The
contracts proposal is frozen as `v2.0-contracts`.

---

**2026-10-03 — Phase 2–5 proposals frozen: 36 spec ambiguities ruled.**

All four phase proposals (2–5) were reviewed and frozen. The 36 ambiguities
across them were ruled as follows:

**Phase 2 (AI layer) — 10 ambiguities:**
1. **Cloudflare in retry order** — The chain cycles through configured adapters
   in `TEXT_PROVIDERS` order. "Cloudflare" in §5.2 refers to Groq's Cloudflare
   front. **Ruling: approved.**
2. **STT failover** — Single adapter, no failover. Error propagates to API layer.
   **Ruling: approved.**
3. **Embeddings failover** — No automatic failover in Phase 2. **Ruling: approved.**
4. **First attempt synchronous** — First adapter tried immediately; subsequent
   retries are background. **Ruling: approved.**
5. **Token counting** — Character-based estimate (`len(text) // 4`) for packing;
   provider-returned counts for cost. **Ruling: approved.**
6. **Lookup-only detection** — No mutation tool calls = lookup-only. **Ruling: approved.**
7. **Verify model selection** — Last adapter in chain (typically free NIM). **Ruling: approved.**
8. **Cost table location** — SQLite `token_cost` table in main DB. **Ruling: approved.**
9. **Similarity threshold** — Configurable, default 0.85. **Ruling: approved.**
10. **Reminder offset confirmation** — Included in `create_event`, confirmed on
    proposal acceptance. **Ruling: approved.**

**Phase 3 (server) — 8 ambiguities:**
1. **`/api/say` auto-commit** — Auto-commit for unambiguous commands; proposal for
   conflicts. **Ruling: approved.**
2. **`/api/commands` vs `/api/say`** — `/api/say` for natural language,
   `/api/commands` for raw tool calls. **Ruling: approved.**
3. **WebSocket hello key** — Header/query for upgrade auth; hello key as fallback.
   **Ruling: approved.**
4. **`GET /api/timer` without node_id** — Return running timer regardless of node.
   **Ruling: approved.**
5. **`PUT /api/settings` merge** — Merge semantics, not replace. **Ruling: approved.**
6. **`POST /api/timer/presets` append** — Append, not replace. **Ruling: approved.**
7. **Voice audio formats** — webm/opus, mp3, wav, ogg. **Ruling: approved.**
8. **`/api/health` response** — status, version, db_path, uptime_seconds. **Ruling: approved.**

**Phase 4 (interfaces) — 8 ambiguities:**
1. **CLI key storage** — Raw key in `~/.chronos/key` (0600), hash in DB. **Ruling: approved.**
2. **`chronos export` format** — JSON only in v1; CSV deferred to Milestone 4. **Ruling: approved.**
3. **`chronos say` server dependency** — Error+exit if server down. **Ruling: approved.**
4. **MCP transport** — HTTP with `/mcp` endpoint. **Ruling: approved.**
5. **HUD screen routing** — Top nav bar with anchors. **Ruling: approved.**
6. **Calendar drag/resize** — HTML5 DnD + edge handles. **Ruling: approved.**
7. **WebSocket reconnection** — Exponential backoff 1–30s. **Ruling: approved.**
8. **CLI `get` subcommands** — Only day/timer/briefing per §9.2. **Ruling: approved.**

**Phase 5 (features) — 10 ambiguities:**
1. **Reuse similarity threshold** — Default 0.85, configurable. **Ruling: approved.**
2. **`check_conflict` return type** — Extended to `array[SearchResult]` (backward-compatible). **Ruling: approved.**
3. **Question storage** — Audit table with `action="question"`. **Ruling: approved.**
4. **`provider_prices` seeding** — Seed at deployment time. **Ruling: approved.**
5. **Briefing generation** — Query-based assembly; AI may enhance. **Ruling: approved.**
6. **`token_costs` table** — Records every attempt; stats aggregates by day. **Ruling: approved.**
7. **Audit viewer pagination** — limit/offset, default 100. **Ruling: approved.**
8. **CSV timestamp format** — ISO-8601 with offset. **Ruling: approved.**
9. **`NodeSearch`↔`NodeRepo` wiring** — Phase 1 implementation detail. **Ruling: approved.**
10. **`Briefing` dataclass vs dict** — Dataclass internally, dict at API boundary. **Ruling: approved.**

All four proposals are frozen. Phase 6 (deploy) is the last proposal to draft.

---

**2026-10-03 — Phase 6 proposal frozen: 8 spec ambiguities ruled.**

1. **Base image patch version** — Pin to `python:3.14.7-slim-bookworm`. **Ruling: approved.**
2. **Multi-arch build** — Build for both `linux/amd64` and `linux/arm64` via `docker buildx`. **Ruling: approved.**
3. **Embedding model download progress** — `llama-embedding` library provides its own progress bar; server logs a line before first download. **Ruling: approved.**
4. **Termux package names** — `python git rust binutils libsqlite`. **Ruling: approved.**
5. **Windows support** — Document as untested; expected path is `pip install -e .` + `chronos serve`. **Ruling: approved.**
6. **Docker image registry** — No registry push in this phase. **Ruling: approved.**
7. **Backup script** — `scripts/backup.sh` with timestamped copies. **Ruling: approved.**
8. **`docs/docker.md`** — Create alongside `docs/termux.md`. **Ruling: approved.**

All six phase proposals are now frozen. Stage 2 (build) can begin.

---

**2026-10-05 — Backend-only freeze (user).**

1. **Web HUD removed.** No `chronos/web/`, no `mount_hud`, no static serving. Backend is REST + WS + MCP only. Phase 4 = CLI + MCP.
2. **Token-cost removed completely.** No `token_cost` / `token_costs` table, no `provider_prices`, no `CostTracker` / `PriceTable` / `cost_hook`, no `chronos token-cost`, no token-spend in `/api/stats`, no cost CSV. Prior rulings (Phase 2 ambiguity 8, Phase 5 ambiguity 6) superseded. Cost conflict 1 in `contract-conflicts.md` closed as wont-do.
3. **FTS fixed.** `node_fts` = `fts5(title, notes)` (regular, not `content=''`). SHA-256 rowid hack removed. `search_keyword` joins back to `nodes`; `index/remove/reindex` best-effort, never break writes, narrow `except OperationalError` only.
4. **Target clarified.** Build host = proot-distro inside Termux (Fedora 44 aarch64). Termux-prefix tools (`pkg`, wake-lock) live outside. Docker behaviour unverified here, delegated to CI.
5. **`smoke.sh` is the gate** and must: use `.venv/bin/chronos`, throwaway DB only (never `$CHRONOS_DB`), poll `/api/health`, assert 401 no-key / 401 bad-key / 200 good-key, one English sentence → real row in SQLite, second timer → 409.

---

**2026-10-05 — v2 build rulings (single-phase).**

1. **NOW_MS test-wrong (1785844800000).** *Ruling: test wrong.* Hardcoded `NOW_MS=1785844800000` (2026-08-05) expired against real scheduling logic — fix the test clock, not the code.
2. **health-open wins over routes-401 case.** *Ruling: `/api/health` stays open.* A test demanding 401 on health contradicts the smoke gate and deploy probes — health is unauthenticated by design.
3. **CLI --version added.** *Ruling: add it.* Spec/UX needs `chronos --version`; implementation was missing, so the test gap was real.
4. **FTS canonical fts5(title,notes,node_id UNINDEXED).** *Ruling: this exact shape.* Keeps full-text on title+notes while storing node_id as a plain carrier — avoids the old SHA-256 rowid hack and keeps writes best-effort.
5. **seed-on-init.** *Ruling: seed at DB init.* Default buckets/settings must exist on fresh init so first-run paths never hit empty-table branches.
6. **alembic-applies-DDL.** *Ruling: migrations apply the DDL.* Alembic revisions must execute the real schema statements — a no-op migration hides drift between models and DB.
7. **settings-hash rejected.** *Ruling: rejected.* Hashing the whole settings blob adds a spurious failure mode with no spec basis — merge semantics from Phase 3 stand.
8. **provider-mgmt v1.1 (write-only keys, DB store, no .env).** *Ruling: v1.1 shape.* API keys are write-only via API, persisted in DB, never read from `.env` — avoids plaintext env leakage and matches the instance-key model.
9. **termux-uv flow (proot-distro+uv+3.14.7).** *Ruling: canonical Termux path.* proot-distro + `uv` + pinned 3.14.7 is the reproducible on-device install — `pkg python` drift caused prior breakage.
10. **phases-combined naming.** *Ruling: one suite `tests/phase_1/*` with `test_*`, `test_ai_*`, `test_srv_*`, `test_if_*`, `test_feat_*`, `test_ops_*` + `test_*_fixes_spec.py`.* Old phase 2–6 docs superseded by `phases/phase-1-foundation.md` — keeps history without re-splitting ownership.
