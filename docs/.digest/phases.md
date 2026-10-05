# Chronos — Build Phase Plans: Consolidated Brief

Source: `/root/docs/server/phases/phase-{1..6}*.md`
Upstream spec: `docs/Chronos.md`; process rules in `manager.md` §10.

---

## 1. Structure at a glance

Six phases, all declared "runs in parallel" with each other, but all gated by a
**Phase 0** that freezes `chronos/contracts/`. Parallelism is *interface* parallelism,
not code parallelism: phases 1–5 build against the frozen contract/repo surface, phase 6
packages whatever emerges.

| Phase | Surface | Parts | Gate for the rest of its phase |
|---|---|---|---|
| 1 Core | contracts, db engine/schema/seed/repo, `core/scheduling.py`, alembic | 6 | 1.1 contracts must land before 1.2–1.6 |
| 2 AI | providers (adapter/chain/worker/stt), pipeline (packer/intent/verify/tools), cost | 8 | interface freeze only |
| 3 Server | FastAPI factory, auth, REST, voice, realtime hub, smoke script | 6 | 3.1 app factory + 3.2 auth gate 3.3–3.6 |
| 4 Interfaces | web HUD (no build step), CLI, MCP | 5 | 4.1–4.3 one surface; 4.4/4.5 independent |
| 5 Features | ntfy+reminders, search, briefings, stats, audit viewer, CSV export | 6 | all independent after freeze |
| 6 Deploy | Dockerfile, compose, Termux, packaging, CI, deploy scripts | 6 | none; start early |

**Four-agent ceiling** applies throughout. Every part is "one code agent."
Every phase repeats the same closing checklist item: delete per-part scratch tests
and probe scripts, keep the phase's spec tests (`manager.md` §10).

### Common verification block (phases 1–5)
```bash
.venv/bin/python -m pytest tests/phase_N -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check chronos tests
```
Phases 2 and 5 add a hard rule: **no test may touch the network — inject fakes.**

---

## 2. The frozen surface (Phase 1 owns it)

`chronos/contracts/` is the project's load-bearing boundary. Contents:
- Models: `Node`, `Tag`, `NodeTag`, `Event`, `Bucket`, `ReviewSeries`, `Schedule`,
  `Reminder`, `TimerSession`, `AuditEntry`.
- Enums: `NodeKind`, `NodeStatus`, `EventKind`, `SeriesState`, `TimerMode`,
  `TimerPhase`, `ReminderState`, `BucketLevel`, `ReviewTier`.
- `ToolCall`, `ToolResult`, `TOOL_SCHEMAS` for the **27 tools** (§5.5).
- Protocols: repo protocols plus `Clock`, `IdGen`, `Embedder`, `Notifier`, `SearchBackend`.
- **Import graph must be a DAG with no cycles.** Changes only by deliberate, announced act.

Two signatures/universals worth flagging as API-level contracts:
- `chronos.api.create_app(db_path=None) -> FastAPI` — phase 3 says this is
  "load-bearing"; CLI, smoke script and tests all call it, and it must open the
  exact file `db_path` names (otherwise every request 401s against a different
  database's key).
- `DEFAULT_REMINDER_OFFSETS_MIN = [10, 0]` — exactly one definition project-wide (phase 5).

---

## 3. Invariants that recur across phases (the anti-v1 list)

The plans are unusually explicit about previously-shipped failures. These are the
highest-value lines in the whole set:

**Data / time**
- Bucket chain is nested **Y → M → W → D**; a day's parent is the **week** containing
  it. (v1 parented every day to a month.) Seed exactly 10 years forward: 10 year,
  ~120 month, ~522 week, ~3653 day ≈ 4,300 rows; idempotent. Week id number = ISO week
  of its own start date.
- Times are **UTC epoch milliseconds as integers**. Scheduling grid is **1 minute**.
- `soft_deleted` events are not conflicts.
- One instance timezone; local wall time → UTC on every write and render.

**Review series** — must be **bounded** (`max_count` and/or `ends_on_ms`, at least
one), enforced at both repo and schema layer; unbounded is refused. (v1 shipped both
a zero-review-events version and an unbounded-accepting version.) Creation writes
**all** review events in one transaction, each with `series_id`, `review_index`,
`derived_from = anchor_node_id`. Default tiers as day offsets: hard `1,2,4,8,16`;
medium `3,7,15,30`; easy `10,30,90`. No geometric/GP formulas, no automatic rewind.

**Timers** — one timer at a time across all modes; a stopwatch **ignores** its target;
pomodoro breaks excluded from work totals but still recorded; an early-stopped focus
phase is not a completed cycle; time reported per node (own / with descendants / project
rollup resolved by walking `parent_id` to the nearest ancestor project).

**AI** — failover **never raises to the caller** (absolute); retries are unbounded but
**never on the request path** (return a queued result); exponential backoff + jitter
cycling Cloudflare → Groq → NIM; `RETRY_SKIP_AFTER_SECONDS` default 120 offers a manual
skip; `RETRY_MAX_INFLIGHT` caps concurrency. Every attempt, success or failure, is
written to the daily token-cost table. `cost_usd` comes from a real price table:
**unknown price is `None`, never a fake `0.0`** (and an empty cell in CSV, not `0.0`).
A **lookup-only turn gets a second turn** or the model parses correctly then silently
no-ops. The **current time must be in the context prefix** or "tomorrow" is unresolvable.
Verify pass never invents a call the user did not ask for. All 27 tools dispatch; none
stubbed; **a series is one tool call, never N**; **no AI-callable move tool** (only
`create_event`/`delete_event`); conflicts resolved in code, never by the model.

**Providers** — one OpenAI-compatible adapter, three configs (text/speech/embeddings);
no provider-specific code paths. NIM is only the free cloud endpoint
`integrate.api.nvidia.com/v1`, never self-hosted. Default text `openai/gpt-oss-120b`
on Groq; the NIM leg must use `nvidia/nemotron-3-super-120b-a12b` (NIM 410s the former).
Speech `whisper-large-v3-turbo`; embeddings default to **local** `llama-embedding`
(~274 MB, downloaded on first use with announced progress, never silently inside a
request). Roles: Understand / Verify / Classify — no separate decision model.

**Search** — three host-side stages: FTS5 keyword narrowing → sqlite-vec cosine ranking
→ model judges duplication. Degrade at every step, **never raise** (missing vec table =
keywords only). Scores are **absolute** (a normalised score means the reuse threshold
can never fire). **bm25 is not a similarity** — surface as a distinct field. Must work
against both a SQLAlchemy `Session` and a raw `sqlite3.Connection`; narrow the `except`
(a broad one silently swallowed an argument error and returned nothing under a Session).
Nodes must actually be **indexed on create, re-indexed on update, removed on delete**,
best-effort — an absent FTS table must never break a write. (v1's `create_node` never
wrote to FTS, so real search returned nothing while tests passed.) Tags are never
duplicated — an existing tag by name is always reused.

**Server** — one instance key, generated once, **Argon2-hashed**; required on every
REST request, WS upgrade, MCP call and CLI command via `X-Chronos-Key` with a
query-string fallback for MCP. **`/api/health` is the only unauthenticated route.**
A query-string key is **redacted at record-creation time**, not by a logger filter
(filters don't run for descendant loggers like `httpx._client`). `key-renew` rotates and
disconnects every client. Single user — no roles, no registration, no multi-tenancy.
Second timer start → **409**, not a crash or silent replace. No stub left in `routes.py`
that shadows a later module's route (v1 shipped two, making features invisible while
tests passed). One hub, many clients: every mutation broadcasts to all.

**Interfaces** — HUD is plain files, no bundler/framework/build step, no glassmorphism
or orbital ring. Zero-form input: commit on blur, no save button. Mic **appends** the
transcript and **does not auto-submit**; countdown field is **hidden** (not disabled)
for a stopwatch. Never expose the instance key in the browser or console. **Every CLI
command must actually run and produce output** (v1: four of seven had never executed,
tests only asserted registration). `serve` must resolve `chronos.api.create_app` and
forward `--db`; `db-upgrade` must invoke alembic **through the current interpreter**,
load the sqlite-vec extension (schema creates a `vec0` virtual table) and honour
`CHRONOS_DB`. MCP reuses the pipeline's tool set via an injected executor — no
reimplementation — and audits every call.

**Briefings** — generated, not templated (content must vary with data). Clarification
budget is **one question per day**, queued in the panel, rolling into tomorrow when
spent, and **persisted across process restart** (v1's counter was in memory only).
Briefing reports what it considered: "checked 30 tasks, showing 8".

**Deployment** — no systemd, no root, no OS timezone config; the process is a plain
`chronos serve`. Targets: Linux desktop (primary), **Termux on Android** (must genuinely
work — `termux-wake-lock` *before* starting or doze kills it), Windows (best effort,
document what is untested). Docker: DB on a volume so container replacement is safe and
"copy the file" remains the whole backup story; no secrets baked into layers; pinned base
image. CI runs `ruff` + full pytest + docker build on a clean checkout.

---

## 4. Notable specifics worth keeping

- **Duplicates** (phase 5, §6): pre-create search over ±1 day warns and proposes;
  it **never moves anything**. `check_conflict` can widen to ±7 days.
- **Schedules** (phase 1, §4.5): always bounded by start and end date, may exclude
  weekdays; `paused` schedules and non-`hard_block` schedules do not block.
- **Reminders**: real rows, individually cancellable, fired by the realtime tick;
  cancelled reminders never fire.
- **Retention**: audit 7 days, logs 7 days; the audit viewer is read-only and
  filterable by action, target and time range.
- **REST surface** (phase 3 §8.2): ~18 routes — `/api/voice`, `/api/say`,
  `/api/commands`, `/api/events`, `/api/nodes`, `/api/buckets`, `/api/briefing`,
  `/api/search`, `/api/reminders`, timer start/stop/current/summary/presets,
  `/api/stats`, `/api/settings` GET+PUT, `/api/keys/renew`, `/api/health`.
- **WebSocket protocol**: S→C `state` (full snapshot on connect), `patch`, `proposal`,
  `question`, `timer`, `queued`, `retrying`; C→S `hello`, `say`, `accept`/`reject`/`skip`.
- **Context packer priority** (must be in this order, drop lowest first, record cuts):
  stable prefix (identity, hard blocks, prefs, **current time**) → target node's ancestor
  chain → semantic+keyword results capped at top N with titles and relative dates →
  ±1 day of events → the user's utterance **verbatim, last**.
- **Context packer/verify** interactions: tool-arg dates are absolute ISO-8601 in the
  instance timezone; the model never emits a bare "day 8"; non-computable patterns become
  `ask_question` or explicit listed dates.
- **Core purity**: `chronos/core/` tests must run in milliseconds with no database —
  if they need one, the logic is in the wrong module.
- **Auth logging pitfall** is called out twice as easy to get wrong; treat the
  record-creation-time redaction as a non-negotiable review item.

---

## 5. Phase-specific gates (the "real proof" lines)

- **Phase 1** — fresh DB seeds 10 years of nested buckets with exact counts; every day's
  parent resolves to a week; repo round-trips all entities with cascades; bounded-series
  rule enforced twice; `core/` pure.
- **Phase 2** — one adapter / three configs; failover verified against fakes; packer
  respects ceiling and records cuts; current time in prefix; lookup-only turn triggers a
  second turn; unbounded series refused by the dispatcher; unknown price → `None`.
- **Phase 3** — `./scripts/smoke.sh 8099` is the gate: *"A green unit suite is not a
  running app."* One English sentence must commit a real event readable back out of SQLite.
- **Phase 4** — run the CLI commands against a real `CHRONOS_DB` file, don't just import them.
- **Phase 5** — no fake zeros; a duplicate caught semantically rather than by title match.
- **Phase 6** — `pip install -e .` → `chronos serve` from a clean checkout; `docs/termux.md`
  and `docs/docker.md` must state exactly what was and was not verified on this host.
  *"A clear 'this could not be tested here, because X' is worth more than a claim."*
