# Chronos — AI Study Scheduler & Time Tracker

Local-first scheduling and cognitive management for a single student.
The server is the entire application; clients are views and controls.

This document is the source of truth. Decisions live here, not in any
conversation — read this file first, regardless of what you were told before.

**Status:** Milestone 1. Build order in §14. Agent workflow in `docs/agents.md`.

---

## 0. Resolved contradictions

Every item the original drafts stated two incompatible ways about, and what we
actually do. Nothing was dropped silently.

| # | Old conflict | Decision |
|---|---|---|
| 1 | Rust host (§3) vs FastAPI (§21.3) | Python + FastAPI |
| 2 | SQLite vs Postgres DDL (`JSONB`, `TIMESTAMPTZ`) | SQLite only |
| 3 | Per-event keys (§2, §19.2) vs single key (§7) | One shared instance key |
| 4 | "No secrets in clients" vs client holds the key | Client holds *the* key; provider keys never leave the host |
| 5 | Vector DB mandated (§21.2) vs banned (§14.2) | Vector DB is in, local `sqlite-vec` |
| 6 | Pinecone / Chroma (§21.5) | Rejected — cloud. Local embeddings |
| 7 | 1-hour slots (§3.4) vs 5-minute grid (§21.1) | 1-minute grid |
| 8 | §15 Node.js client as orchestration layer | Removed. All logic on the host |
| 9 | Concurrency via queue + lock file (§3.1) | Removed. SQLite transactions serialize writes |
| 10 | "Client may cancel mid-request; server discards it" | Removed. Requests are short; cancel means stop listening |
| 11 | RAID 5 requirement (§19.5) | Removed. Not a laptop/Termux concern |
| 12 | "time-peak aliasing / utf-8 timespeak-alias" (§19.5) | Removed. Hallucinated; no such standard exists |
| 13 | Brain-training mini-games (§21.4) | Removed |
| 14 | Glassmorphism / orbital ring HUD (§21.1) | Removed. Flat screens, dark HUD styling |
| 15 | Google Calendar / ICS / location sync (§3, §14.3) | Removed. Own calendar renderer, no external sync |
| 16 | 4 parallel bucket lists (§13) | Nested Y→M→W→D chain |
| 17 | Buckets computed vs stored | Materialized tables, 10 years, auto-extended |
| 18 | GP/geometric review formulas (§21.2, "GPb engine") | Explicit day offsets only |
| 19 | Automatic rewind when a review goes badly | No rewind. User bulk-deletes and reschedules |
| 20 | Series with no end (§14 implied infinite) | Every series terminates |
| 21 | Server-only timer (§5) vs offline timer sync (§16.2) | Server-only. A timer outlives a client disconnect, not a server crash |
| 22 | Per-event key authority for conflict resolution (§19.2) | Removed. One key authorizes everything |
| 23 | "Admin-level override" (§20) | Admin = anyone holding the instance key |
| 24 | Jev (TypeSafe System One decision model) | Dropped. Text models only |
| 25 | NVIDIA NIM self-hosted | Dropped. NIM used only as a free cloud endpoint |
| 26 | "AI generates a GP formula then patches bad dates" | The AI proposes explicit dates; a verify pass audits them |
| 27 | Buckets hardcoded vs derived | Materialized rows, seeded 10 years forward |

---

## 1. Product

You speak or type a sentence. The AI turns it into tasks, files them into time
buckets, proposes concrete minutes on the calendar, and registers spaced
repetition reviews. You accept or reject the proposal.

Four rules shape everything:

- **The server is everything.** Events, timers, projects, tags, settings and
  audit history live in one SQLite file on the host. Clients hold no state worth
  the name.
- **Zero-form input.** No date pickers, no time dropdowns. One text box and a
  mic button that appends its transcript after whatever is already in the box.
- **Visual output.** The AI never answers in prose. It draws a proposal on the
  calendar or a diff in the briefing panel.
- **Token frugality is a constraint, not an optimisation.** Context is assembled
  by a budgeted packer, never by dumping tables at the model.

---

## 2. Architecture

```
┌── Clients (any device on the LAN) ──────────────────────────┐
│  Web HUD (served by the host, default)                      │
│  Android app        CLI client        MCP client (agent)    │
└───────┬──────────────────┬──────────────────┬───────────────┘
        │ REST + WebSocket │                  │ MCP
  ┌─────▼──────────────────▼──────────────────▼──────┐
  │  Host: uvicorn + FastAPI                          │
  │  ├ auth (instance key)      ├ ai/ (providers,    │
  │  ├ api/ (REST)              │  intent, verify,  │
  │  ├ realtime/ (websocket)    │  context packer)  │
  │  ├ mcp/                     ├ core/ (scheduling, │
  │  ├ core/                    │  series, conflict)│
  │  ├ notify/ (ntfy, reminders)└ cli/               │
  └─────┬──────────────────────────────────────┬──────┘
        │                                      │
  ┌─────▼─────────────┐              ┌─────────▼──────────┐
  │ SQLite            │              │ llama-embedding    │
  │ ├ nodes, tags     │              │ (local, on the     │
  │ ├ events          │              │  phone, behind     │
  │ ├ buckets         │              │  /v1/embeddings)   │
  │ ├ review_series   │              └────────────────────┘
  │ ├ reminders       │
  │ ├ schedules       │◀── sqlite-vec (same file)
  │ ├ timer_sessions  │◀── FTS5     (same file)
  │ ├ settings, audit │
  └───────────────────┘
```

One SQLite file holds the tables, the FTS5 index and the sqlite-vec virtual
table. Copy the file, and you have a backup.

Outbound network traffic is limited to: model inference (text, speech,
embeddings), and ntfy publishes. Schedule data never leaves the host.

### 2.1 Module boundaries

Every module imports from `chronos/contracts/` and nothing else from its
siblings. `contracts/` is the frozen shared surface; changing it is a
deliberate, announced act. Each module owns its files exclusively — no two
agents edit the same directory.

```
chronos/
  contracts/   frozen models + Protocols          (Phase 1, single owner)
  db/          engine, session, migrations, seed  (Phase 1, single owner)
  core/        pure scheduling logic — no DB, no framework imports
  ai/          providers, retry worker, intent, verify, context packer
  api/         REST routes
  realtime/    websocket hub
  notify/      ntfy publisher, reminder scheduler
  mcp/         MCP server
  cli/         argparse entry points
  web/         static HUD, no build step
tests/
docs/
```

`core/` is deliberately pure: functions in, values out, no database handle and
no `sqlite_vec`. Its tests therefore run on any machine in milliseconds, which
matters because the build host is one shared Android container.

---

## 3. Auth

- One **instance key**, generated on first run, printed once, stored Argon2-hashed.
- Every REST request, WebSocket upgrade, MCP call and CLI command requires it.
  Header `X-Chronos-Key`, with a query-string fallback for MCP clients that
  cannot set headers.
- `chronos key-renew` rotates it and disconnects every client.
- A key in a query string is never written to a log.
- Single user. No roles, no registration, no multi-tenancy.

---

## 4. Data model

All times are UTC epoch milliseconds (`INTEGER`) in the database. ISO-8601 with
offset at every API boundary. One instance timezone (§7) governs all bucket
maths and all rendering.

### 4.1 Hierarchy and tags

```sql
CREATE TABLE nodes (
    id         TEXT PRIMARY KEY,                    -- uuid4
    parent_id  TEXT REFERENCES nodes(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                       -- project|task|subtask
    title      TEXT NOT NULL,
    notes      TEXT,
    status     TEXT NOT NULL DEFAULT 'active',     -- active|done|archived
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    done_at    INTEGER
);
CREATE INDEX ix_nodes_parent ON nodes(parent_id);

-- Tags apply to tasks and subtasks, never to projects.
CREATE TABLE tags (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    color TEXT
);
CREATE TABLE node_tags (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    tag_id  TEXT NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (node_id, tag_id)
);
```

A task may be linked to others with no structural meaning (see
`node_links`), which is how "this depends on that" is recorded without
inventing a parent.

### 4.2 Events

```sql
CREATE TABLE events (
    id           TEXT PRIMARY KEY,
    node_id      TEXT REFERENCES nodes(id) ON DELETE CASCADE,  -- NULL = ad-hoc
    title        TEXT NOT NULL,
    start_ms     INTEGER NOT NULL,
    end_ms       INTEGER NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'focus',   -- focus|class|break|review|admin
    bucket_id    TEXT REFERENCES buckets(id),
    series_id    TEXT,                            -- review series, if any
    review_index INTEGER,                         -- 1..N within the series
    derived_from TEXT,                            -- source event id
    soft_deleted  INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);
CREATE INDEX ix_events_window ON events(start_ms, end_ms);
CREATE INDEX ix_events_series ON events(series_id);
```

Overlap detection is a plain range query on `ix_events_window`. No vector step
participates in hard conflict resolution.

### 4.3 Buckets

```sql
CREATE TABLE buckets (
    id        TEXT PRIMARY KEY,   -- 'Y:2026' 'M:2026-08' 'W:2026-W31' 'D:2026-08-04'
    level     TEXT NOT NULL,      -- Y|M|W|D
    parent_id TEXT REFERENCES buckets(id),
    start_ms  INTEGER NOT NULL,
    end_ms    INTEGER NOT NULL,
    seq       INTEGER NOT NULL    -- 1..4 ordinal within the parent
);
```

First run creates 10 years forward: 10 year, ~120 month, ~522 week and ~3653 day
rows — about 4,300 in total. A background job extends the range whenever fewer
than 180 days remain.

An unallocated task points at one bucket level. Scheduling walks it down: bucket
→ day → minutes.

### 4.4 Review series

```sql
CREATE TABLE review_series (
    id             TEXT PRIMARY KEY,
    node_id        TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    tier           TEXT NOT NULL,     -- hard|medium|easy|custom
    offsets_days   TEXT NOT NULL,     -- JSON int array, e.g. [3,6,15,30]
    anchor_node_id TEXT NOT NULL,     -- the completed node that started it
    max_count      INTEGER,           -- NULL = no count bound
    ends_on_ms     INTEGER,           -- NULL = no date bound
    state          TEXT NOT NULL,     -- active|retired|cancelled
    created_at     INTEGER NOT NULL,
    CHECK (max_count IS NOT NULL OR ends_on_ms IS NOT NULL)
);
```

Creating a series writes all of its review events in **one transaction, one
tool call**. Each event carries `series_id`, `review_index` and
`derived_from = anchor_node_id`, so any member traces to its origin and the whole
set can be bulk-deleted or bulk-rescheduled in a single request.

Default tiers, as day offsets from the completed session:

| Tier | Offsets |
|---|---|
| hard | 1, 2, 4, 8, 16 |
| medium | 3, 7, 15, 30 |
| easy | 10, 30, 90 |

The AI picks the tier and can be overruled per request. **A series must be
bounded**: `max_count` and/or `ends_on_ms`, at least one. The API rejects an
unbounded series — a review set that never ends is a bug the user complained
about in a previous build of this idea.

A bad review does not rewind anything. The user asks for the series to be
deleted and rescheduled, which is one tool call and one transaction.

### 4.5 Recurring commitments ("Schedules")

```sql
CREATE TABLE schedules (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    starts_ms      INTEGER NOT NULL,
    ends_at_ms     INTEGER NOT NULL,
    start_minute   INTEGER NOT NULL,   -- minute of day, e.g. 510 for 08:30
    duration_min   INTEGER NOT NULL,
    weekdays       TEXT NOT NULL,      -- JSON int array [1..7], ISO weekday
    hard_block     INTEGER NOT NULL DEFAULT 1,
    paused         INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL
);
```

Schedules are hard blocks: the scheduler will not place an event inside one, and
AI proposals must route around them. Overriding is possible but must be explicit
from the user, and is recorded in the audit log.

Every schedule is bounded by a start and end date and may exclude weekdays —
"school, no Saturday or Sunday, ends in three months". Schedules are editable by
voice like everything else, including "stop showing school after three months"
and "delete all of them".

### 4.6 Reminders

```sql
CREATE TABLE reminders (
    id           TEXT PRIMARY KEY,
    event_id     TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    fire_at_ms   INTEGER NOT NULL,
    offset_min   INTEGER NOT NULL,
    state        TEXT NOT NULL DEFAULT 'pending',  -- pending|sent|cancelled
    channel      TEXT NOT NULL DEFAULT 'ntfy',
    created_at   INTEGER NOT NULL
);
CREATE INDEX ix_reminders_due ON reminders(state, fire_at_ms);
```

Default offsets are **10 minutes before and at the start** (§5.4: the AI
confirms the offset list before anything is committed). A reminder row is a real
row, not a derived value, so it can be cancelled individually. The scheduler job
runs on the realtime tick and publishes anything due.

### 4.7 Timer, settings, audit

```sql
CREATE TABLE timer_sessions (
    id         TEXT PRIMARY KEY,
    node_id    TEXT REFERENCES nodes(id),
    label      TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,               -- NULL = running
    source     TEXT NOT NULL,         -- device id
    reconciled INTEGER NOT NULL DEFAULT 0,
    mode       TEXT NOT NULL DEFAULT 'stopwatch',  -- stopwatch | timer | pomodoro
    target_ms  INTEGER,               -- NULL for a stopwatch, which has no target
    phase      TEXT,                  -- pomodoro only: focus | break
    cycle      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE audit (
    id        INTEGER PRIMARY KEY,
    at        INTEGER NOT NULL,
    device_id TEXT,
    action    TEXT NOT NULL,
    target    TEXT,
    context   TEXT,
    cost_usd  REAL
);
```

One timer runs at a time. Start or stop from any connected device; the server is
the source of truth. A running timer survives a client disconnect. If the server
dies mid-timer, the session is flagged `reconciled = 1` on the next boot, the
elapsed wall time is recorded, and the gap is logged — never silently discarded.

Audit retention is 7 days. Log retention is 7 days.

#### Three modes

`mode` picks how the session is counted. A stopwatch counts up and has no
target, so it ignores any target a client sends rather than silently becoming a
countdown. A timer counts down to `target_ms`. A pomodoro alternates `focus` and
`break` phases across `cycle`, and a focus phase that ran its full length is a
completed cycle while one stopped early is not.

Every session is tagged to a task or a project via `node_id`. The project is
resolved by walking `nodes.parent_id` up to the nearest ancestor project, so a
task's time counts toward its project without being re-tagged and without the
client knowing which project that is. Re-parenting a task re-points its rollup,
because the link is derived rather than stored.

Logged time is reported per node: the node's own total, the same total including
all descendants, and the project total for a tagged task. Pomodoro breaks are
excluded from those totals — a break is rest, and counting it would inflate every
project by a quarter — but the break is still recorded in the session log.

Custom pomodoro presets are a JSON list under the `timer.pomodoro_presets`
setting key, so adding a preset later is not a schema change. The default
25/5 × 4 preset is always available, and an unreadable stored value falls back to
that default rather than disabling the mode buttons.

### 4.8 Vector and full-text search

```sql
CREATE VIRTUAL TABLE node_fts USING fts5(title, notes, content='');
CREATE VIRTUAL TABLE node_vec USING vec0(
    node_id    TEXT PRIMARY KEY,
    embedding FLOAT[768]
);
```

Search runs in three stages, all on the host: FTS5 narrows candidates on
keywords, sqlite-vec ranks them by cosine similarity, then the model judges
whether the top hits are genuine duplicates.

---

## 5. AI layer

### 5.1 Providers

Three independent provider groups, configured via an interactive startup
script or `.env`, switchable at runtime from Settings. `.env` holds every
secret and is never sent to a client. The Settings screen shows which provider
is active and lets you switch between already-configured ones; it never
displays or edits a key.

**Interactive setup.** On first run (or when `chronos setup` is invoked), the
server walks the user through provider configuration:

1. **STT provider** — ask for the speech-to-text endpoint (must be
   OpenAI-compatible), the model name (default `whisper-large-v3-turbo`), and
   how many API keys to enter. Then ask for each key.
2. **Text providers** — ask how many text providers to configure. For each
   one, in order: ask for a name (e.g. `groq`, `nim`), the base URL, the
   model name, and how many API keys to enter. Then ask for each key.
3. **Embeddings** — ask for the endpoint (default: local `llama-embedding`)
   and model name.

The order in which text providers are entered **is** the failover order. If
provider 1 fails (429, 5xx, timeout), the system tries provider 2, and so on.
Multiple keys per endpoint are tried round-robin before falling through to
the next provider.

All three speak OpenAI-compatible shapes. Only the base URL and model name
differ, so there is one adapter and three configurations.

GPT-OSS 120B is the default text model, but only where it is actually served:
NIM returns HTTP 410 for `openai/gpt-oss-120b`, so the failover leg stays on
Nemotron rather than naming a model the provider will reject. Speech and
embeddings are separate models with different jobs and cannot use the text
model.

NVIDIA NIM appears solely as the free cloud endpoint at
`https://integrate.api.nvidia.com/v1`. It is not self-hosted.

**Configuration storage.** The interactive setup writes to `.env`. The server
can also run with no keys at all — it falls back to a built-in offline parser,
so scheduling by sentence still works. Keys unlock the better model.

### 5.2 Retry and failover

Retries are effectively unbounded — providers cycle until something succeeds —
but they never happen on the request path.

- A `say` or tool request returns immediately with a queued result.
- A background worker retries with exponential backoff plus jitter, cycling
  Cloudflare → Groq → NIM, on 429, 5xx and timeout.
- After `RETRY_SKIP_AFTER_SECONDS` (default 120) the client is offered a manual
  skip, so a dead provider can never trap the interface indefinitely.
- `RETRY_MAX_INFLIGHT` caps concurrent retry jobs. Excess requests queue. Without
  this cap a dead provider would quietly consume memory.
- Every attempt, failed or not, is written to the daily token-cost table.

### 5.3 Roles

| Role | Job | Model |
|---|---|---|
| Understand | voice or text → structured intent → tool calls | TEXT, primary |
| Verify | audit proposed tool calls against the user's actual words | TEXT, cheap tier |
| Classify | duplicate scoring, tier choice, bucket level | TEXT, cheap tier |

There is no separate decision model. Verification is a second pass with the
cheapest configured text model and a narrow job: did these tool calls mean what
the user said? On a mismatch it corrects dates, offsets and slots before anything
is committed. This matters most for bulk operations — an entire review series, a
run of recurring events — where a single wrong number repeats.

### 5.4 Reminders and hierarchy creation

The AI may create structure while scheduling: a project, its task, a subtask, a
tag. Two rules make that safe:

- Before creating, search for an existing node that matches. Above a similarity
  threshold the existing one is reused rather than duplicated.
- Tags are never duplicated. An existing tag by name is always reused.

When the AI creates or schedules anything, it proposes its reminder offsets
alongside the slot, and the user confirms both before commit.

### 5.5 Tool set

```
create_node · update_node · delete_node · link_nodes
tag_node · untag_node
create_event · update_event · delete_event
schedule_series · delete_series · reschedule_series
search_nodes · check_conflict · find_free_slots · get_free_time
create_schedule · update_schedule · pause_schedule
start_timer · stop_timer · log_time
get_day · get_week · get_month · get_briefing
ask_question
```

Rules:

- Dates in tool arguments are absolute ISO-8601 in the instance timezone. The
  model never emits a bare "day 8". If a pattern does not fit a computable rule,
  it calls `ask_question` or lists explicit dates.
- A series is one tool call, never N.
- There is no AI-callable move tool. Only `create_event` (which may report a
  pushed-back slot) and `delete_event`.
- Hard blocks and overlaps are resolved in code, never by the model.

### 5.6 Budgeted context pack

Assembled per turn under a token ceiling:

1. Identity, hard blocks and instance preferences — a stable prefix placed first
   so provider prompt caching applies.
2. The target node's ancestor chain. Cheap in tokens, and what makes a subtask
   comprehensible without its parents being restated in full.
3. Semantic and keyword results, capped at the top N with titles and relative
   dates rather than full bodies.
4. ±1 day of events for conflict checking.
5. The user's utterance verbatim, last.

Overflow drops from the lowest priority upward. The packer records what it cut
so the UI can say "checked 30 tasks, showing 8".

### 5.7 Clarification budget

One proactive question per day by default, queued in the briefing panel rather
than blocking. When the day's budget is spent, questions roll into tomorrow's
briefing. Configurable in Settings.

---

## 6. Scheduling and conflict rules

Three mechanisms, each with one job.

**Hard slot conflict.** At commit, an event overlapping an existing
non-deleted event is pushed to the first free minute that satisfies duration,
hard blocks and day bounds. Deterministic, plain SQL, no model involved. The
response carries both the requested and the actual slot so the client can show
what happened.

**Semantic duplicate check.** Before a create, FTS5 plus sqlite-vec search over
±1 day surfaces candidates that look like the same work. This warns and
proposes; it never moves anything, because it can be wrong. The model returns a
confidence and the user decides. The window may be widened through
`check_conflict`, up to ±7 days.

**Hard blocks.** Recurring commitments from §4.5. Nothing is auto-placed inside
one. An explicit override is permitted and audited.

Proposals render as a before/after diff and commit on acceptance.

---

## 7. Time

### 7.1 Timezone

One timezone for the instance, chosen at first run and stored in settings. The
server converts local wall time to UTC on every write and render. Changing it
later re-buckets existing events and is audited. No per-client timezone, no
per-event timezone.

### 7.2 Grid

The calendar grid is **1 minute**. Hour rules every 60 minutes; the HUD renders
hours with expandable minute detail rather than a 1440-row grid. Start and end
snap to the minute.

### 7.3 Timestamps

Epoch milliseconds in the database, ISO-8601 with offset at the API boundary.

---

## 8. Server

### 8.1 Process

chronos serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]
chronos setup              interactive provider/API-key configuration
chronos key-renew
chronos db-upgrade
chronos token-cost [--days 7]
```

`--no-web` or `CHRONOS_WEB=0` runs headless, API only. No systemd, no root, no OS
timezone configuration. Targets: Linux desktop and laptop, Termux on Android,
Windows.

Build host for this project is the `occ` prootdistro on an Android phone, entered
as `ssh tu` then `proot-distro login occ` (Fedora 44, aarch64). Local checkout is
canonical; `./deploy.sh` syncs it into the container.

### 8.2 REST

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
GET    /api/timer?node_id     running timer
GET    /api/timer/summary?node_id   logged time + project rollup
GET/POST /api/timer/presets  custom pomodoro focus/break pairs
GET    /api/stats                counts, streaks, token spend by day
GET    /api/settings · PUT /api/settings
POST   /api/keys/renew
GET    /api/health
```

### 8.3 WebSocket `/ws`

One connection per client.

```
server → {type:"state",     ...}   full snapshot on connect
server → {type:"patch",    ops}    incremental change
server → {type:"proposal", ...}   awaiting accept
server → {type:"question",  ...}   clarification
server → {type:"timer",    ...}   tick, start, stop
server → {type:"queued",   id}    retry job accepted, work in progress
server → {type:"retrying", attempt, provider}
client → {type:"hello", key, device}
client → {type:"say", text}
client → {type:"accept"|"reject"|"skip", proposal_id}
```

Every mutation broadcasts to all connected clients. Concurrent writes serialize
on SQLite's write lock; readers never block.

### 8.4 MCP `/mcp`

Exposes the same tool set to external agents, authenticated with the instance
key. Agents can query — "am I free tomorrow evening?" goes through the real
scheduler — and act: "book me the dentist tomorrow" commits with the same
validation the user's own voice input receives, then confirms back. Every call is
audited.

---

## 9. Clients — backend-only

### 9.1 Web HUD — REMOVED 2026-10-05

Backend is API-only (REST + WebSocket + MCP). No bundled web UI. Clients are separate projects and speak the same API; the server needs no special support for any one of them.

### 9.2 CLI

```
chronos serve | setup | key-renew | db-upgrade | token-cost | export
echo "schedule DB review tomorrow 4pm for 45 mins" | chronos say -
chronos get day | timer | briefing
```

Terse output, no prompts, safe to pipe.

### 9.3 Android

Voice capture, timer control, briefing, calendar, notifications. Adaptive for
phone and tablet. Speaks the same REST and WebSocket API; the server needs no
special support.

---

## 10. Notifications

**ntfy** — Apache-2.0 server, GPL-2.0 Android app on F-Droid. The server
publishes to a topic with one HTTP POST. The F-Droid build uses no Google
services, so nothing reaches the internet. Priorities map to review-due,
proposal-awaiting and timer milestones.

Phone setup: install the **F-Droid** build, point it at your own ntfy server,
subscribe to one topic. That is documented in `docs/notifications.md`.

Sending goes through a `Notifier` interface so Gotify can be added without
touching callers. The HUD additionally uses the Web Notifications API when
permitted.

---

## 11. Operational notes

**Android doze** will kill a backgrounded server. Run
`termux-wake-lock` before starting; `/api/health` exists so a client can show a
clear "server is down" state instead of a spinner that never resolves.

**The embedding model** is roughly 274 MB and downloads on first use. The
download is announced with progress and never happens silently inside a request.

---

## 12. Explicitly out of scope

RAID. External calendar sync. Brain-training games. Multi-user auth. Cloud
vector databases. A Node.js client. Glassmorphism visuals. Offline timer capture
on clients. Self-hosted NIM.

---

## 13. Testing

Pure functions in `core/` are tested without a database and run anywhere. Only
work that genuinely needs SQLite, sqlite-vec or the WebSocket hub runs inside the
container.

Covered: conflict push-back maths, bucket boundary seeding, series termination
enforcement, key auth, timezone round-trips, retry and failover against fake
providers, hierarchy reuse thresholds, and one end-to-end AI path with a stub
model.

Timer coverage needs a real database, because the behaviours that matter are
relational rather than arithmetic: that only one session runs at a time across
all three modes, that a stopwatch ignores a target sent to it, that a task's time
rolls up to its project, that a pomodoro break is excluded from work totals, and
that a focus phase stopped early is not counted as a completed cycle.

---

## 14. Build order

**Phase 1 — foundation, one owner, sequential.** `contracts/` frozen
interfaces, then `db/` with Alembic, the full schema, the 10-year bucket seed,
FTS5 and sqlite-vec. Nothing else can start before these exist.

**Phase 2 — leaves, max three concurrent agents**, one branch each
(`feat/<module>`), merged centrally:

| Module | Depends on | Pure-Python tests |
|---|---|---|
| `core/scheduling` | contracts | yes |
| `ai/providers` | contracts | yes |
| `ai/pipeline` | contracts, db | partly |
| `notify/` | contracts, db | partly |
| `web/` | contracts, mock WS | yes |
| `cli/` | contracts | yes |
| `mcp/` | contracts | yes |
| `tests/contract` | contracts | yes |

**Phase 3 — integration, one owner.** `api/` and `realtime/`, which bind db, core
and ai together, then the end-to-end AI path.

**Later.** Milestone 2 is the rest of §5 — full tool set, budgeted packer, series,
schedules, semantic checks, briefings, stats, ntfy. Milestone 3 is CLI, MCP and
Android. Milestone 4 is failover UI, audit viewer, CSV export.
