# Chronos — Consolidated Brief (5 docs)

Sources: `/root/docs/README.md`, `server/START-HERE.md`, `server/Chronos.md`,
`server/REBUILD.md`, `server/architecture.md`.

---

## 0. Authority order (non-negotiable, stated in every doc)

1. **`Chronos.md` wins every disagreement** — it defines *what* is built.
2. `architecture.md` wins on *process* (how the project is built), product goes to Chronos.md.
3. `REBUILD.md` is explicitly **not project-authoritative**; it is a handoff snapshot.
4. `README.md` / `START-HERE.md` are orientation only.

If a doc contradicts Chronos.md, Chronos.md is right.

---

## 1. State of the world — the headline tension

**`Chronos.md` + `START-HERE.md` + `README.md` all say: THERE IS NO CODE.**
Deliberate clean slate. Previous implementation deleted pre-handoff, never pushed
(`origin/main` stuck at `4833d13`, older than the code commit) — **unrecoverable**.
It had a *green test suite and could not boot its own server*.

**`REBUILD.md` describes a large existing codebase**: ~815 passing / 28 failing
across `tests/phase_1..5` + `acceptance`, a verified 17-route API surface in
`chronos/api/routes.py`, a list of 15 specific diagnosed bugs, and 3 failing
Phase-6 tests. It also carries a self-invalidating warning.

**This is the central unresolved contradiction in the handoff.** Either REBUILD.md
describes code that was subsequently deleted (most likely — dates line up with the
"clean slate" note, and REBUILD.md itself says "re-measure, these are stale"), or a
live tree exists that no doc admits to. **First action of any build session must
be to resolve this empirically**, before trusting any number in any doc.

### Proot trap (REBUILD.md §0 — the highest-severity operational warning)
`/root/Chronos` inside the agent's proot-distro **may not be the user's view**.
proot translates paths *per process*. Observed: files returning "No such file",
empty `ls -l`, working `cd`. Consequence: **every "works for me" check the prior
Manager ran is invalid.** Settle the real path + filesystem first; record the
answer at the top of `docs/schedule.md`. Blocked-on item #1 in REBUILD's next-actions.

---

## 2. Product (Chronos.md)

Local-first AI study scheduler + time tracker for **one student**. The server *is*
the app; clients are views.

Four shaping rules:
- **Server is everything** — events, timers, projects, tags, settings, audit in one SQLite file. Clients hold no state.
- **Zero-form input** — no date pickers, no dropdowns. One text box + mic that *appends* its transcript.
- **Visual output** — AI never answers in prose; it draws a calendar proposal or a diff.
- **Token frugality is a constraint, not an optimisation** — budgeted packer, never table dumps.

Loop: sentence → tasks → buckets → concrete minutes → spaced-repetition reviews → user accepts/rejects.

---

## 3. Architecture spine

One SQLite file holds tables + FTS5 index + `sqlite-vec` virtual table. Copy the
file = backup. Outbound traffic is only model inference (text/speech/embeddings)
and ntfy publishes; schedule data never leaves the host.

```
chronos/
  contracts/  frozen models + Protocols   (Phase 0/1, single owner) — ONLY shared surface
  db/         engine, session, migrations, seed
  core/       pure scheduling — no DB, no framework, no sibling imports
  ai/         providers, retry worker, intent, verify, context packer
  api/        REST     realtime/ ws hub     notify/ ntfy + reminders
  mcp/        MCP server    cli/ argparse    web/ static HUD, no build step
```

Every module imports from `contracts/` and nothing else from siblings.
`core/` is deliberately pure (functions in, values out) so its tests run in
milliseconds anywhere — matters because the build host is one shared Android container.

**Egress constraint worth flagging:** vectors/FTS live *in the same file* as
schedules, and `sqlite-vec` is explicitly barred from conflict resolution —
"overlap detection is a plain range query; no vector step participates in hard
conflict resolution."

---

## 4. Data model decisions that will bite

- **Time**: UTC epoch-ms `INTEGER` in DB; ISO-8601-with-offset at every API boundary. **One instance timezone** governs all bucket math and rendering. No per-client/per-event tz.
- **Grid: 1 minute** (explicitly overridden the earlier "1-hour slots" claim). Hour rules every 60 min; HUD renders hours with expandable minute detail, never a 1440-row grid.
- `nodes` = adjacency list (`parent_id`), kind `project|task|subtask`, `ON DELETE CASCADE`. Tags apply to tasks/subtasks, **never projects**; tags never duplicated (reuse by name).
- `events`: `node_id NULL` = ad-hoc; `kind` = focus|class|break|review|admin; carries `series_id`, `review_index`, `derived_from` for traceability; `soft_deleted`. Index `(start_ms, end_ms)` is the conflict primitive; `(series_id)` for bulk ops.
- **Buckets are materialized, not computed.** Nested `Y→M→W→D`, ids `'Y:2026'`/`'M:2026-08'`/`'W:2026-W31'`/`'D:2026-08-04'`, plus `seq` 1..4 ordinal within parent. First run seeds **10 years forward ≈ 4,300 rows** (10 yr / ~120 mo / ~522 wk / ~3653 day). Background job extends when **<180 days remain**.
- **Review series** = explicit day offsets only (no GP/geometric formulas): hard `1,2,4,8,16`; medium `3,7,15,30`; easy `10,30,90`. **Every series must be bounded** — `max_count` and/or `ends_on_ms`, DB-level CHECK, API rejects unbounded. *Rationale recorded: a previous build of this idea had endless review sets.* Creation = **one transaction, one tool call**, all events written at once.
- **No rewind.** A bad review → user bulk-deletes and reschedules (one tool call, one transaction). Auto-rewind was explicitly rejected.
- **Schedules** (recurring commitments) are **hard blocks**: nothing auto-placed inside; override is possible but must be explicit from the user and is **audited**. Always date-bounded; can exclude weekdays; voice-editable ("stop showing school after three months").
- **Reminders are real rows**, not derived — cancellable individually. Defaults 10 min before + at start, **and the AI must confirm the offset list before commit**.
- **Timer**: one at a time, server-authoritative, survives client disconnect. If the server dies mid-timer → `reconciled = 1`, elapsed wall time recorded, gap logged, **never silently discarded**. Three modes: `stopwatch` (counts up, ignores any target sent — does not silently become a countdown), `timer` (counts to `target_ms`), `pomodoro` (alternates focus/break across `cycle`; a full-length focus = completed cycle, an early stop = not). Project rollup is **derived** by walking `parent_id` to the nearest ancestor project, so re-parenting re-points totals. **Pomodoro breaks are excluded from work totals** but still logged (a break is rest; counting it would inflate every project by a quarter). Presets live in `settings` JSON key `timer.pomodoro_presets` — unreadable value falls back to default 25/5×4 rather than disabling the buttons.
- **Search is 3-stage, all local**: FTS5 narrows → sqlite-vec cosine ranks → model judges genuine duplication. `node_fts` is `content=''` (external content); `node_vec` = `vec0(node_id TEXT PK, embedding FLOAT[768])`.
- **Audit retention 7 days. Log retention 7 days.**

---

## 5. AI layer

**Providers** — three independent groups (STT / text / embeddings), all
OpenAI-compatible → *one adapter, three configs*. Configured by interactive
`chronos setup` or `.env`; `.env` never leaves the host; Settings shows which
provider is active and **never displays or edits a key**.
- STT default model `whisper-large-v3-turbo`; embeddings default local `llama-embedding`.
- **Entry order of text providers *is* the failover order.** Multiple keys per endpoint tried round-robin *before* falling through.
- GPT-OSS 120B is the default text model **only where actually served** — NIM returns HTTP 410 for `openai/gpt-oss-120b`, so that failover leg stays on Nemotron rather than naming a model the provider will reject.
- NVIDIA NIM is **only** a free cloud endpoint at `https://integrate.api.nvidia.com/v1`; self-hosting dropped.
- **Zero keys is a supported state** — falls back to a built-in offline parser so sentence scheduling still works; keys only unlock the better model.

**Retry/failover** — unbounded cycling but **never on the request path**. A `say`
returns immediately with a queued result; a background worker retries with
exponential backoff + jitter over Cloudflare → Groq → NIM on 429/5xx/timeout.
`RETRY_SKIP_AFTER_SECONDS` (default 120) offers a manual skip so a dead provider
can't trap the UI. `RETRY_MAX_INFLIGHT` caps concurrency (otherwise a dead
provider quietly eats memory). Every attempt logged to the daily token-cost table.

**Roles** — three, no separate decision model: Understand (TEXT primary),
Verify (cheap tier, audits tool calls against the user's actual words),
Classify (cheap tier, dedupe scoring, tier + bucket choice). Verify matters most
for **bulk ops** (a whole review series, a run of recurring events) where one
wrong number repeats; on mismatch it corrects dates/offsets/slots *before* commit.

**Tool set (26)** — nodes CRUD + link, tag/untag, event CRUD,
`schedule_series`/`delete_series`/`reschedule_series`, `search_nodes`,
`check_conflict`, `find_free_slots`, `get_free_time`, schedule CRUD,
`start_timer`/`stop_timer`/`log_time`, `get_day`/`get_week`/`get_month`/`get_briefing`, `ask_question`.
Rules: dates always **absolute ISO-8601 in the instance tz** (the model never emits a bare "day 8"); a series is **one** call never N; **no AI-callable move tool** (only `create_event`, which may report a pushed-back slot, and `delete_event`); **hard blocks and overlaps resolved in code, never by the model**.

**Context pack** under a token ceiling, in order: (1) identity + hard blocks +
preferences as a *stable prefix first* so provider prompt caching applies,
(2) target node's ancestor chain, (3) semantic/keyword hits capped at top N as
titles + relative dates, (4) ±1 day of events, (5) the user's utterance verbatim,
**last**. Overflow drops lowest-priority-upward; the packer records what it cut so
the UI can say "checked 30 tasks, showing 8".

**Clarification budget** — one proactive question per day by default, queued in
the briefing panel rather than blocking; when spent, questions roll into
tomorrow's briefing. Configurable.

---

## 6. Scheduling & conflict — three mechanisms, one job each

1. **Hard slot conflict** — at commit, an overlap is pushed to the first free
   minute satisfying duration + hard blocks + day bounds. Deterministic, plain
   SQL, **no model**. Response carries **both requested and actual slot**.
2. **Semantic duplicate** — before create, FTS5 + sqlite-vec over ±1 day warns
   and proposes; **never moves anything** (it can be wrong). Model returns a
   confidence, user decides. Widenable via `check_conflict` to ±7 days.
3. **Hard blocks** — recurring commitments; explicit override permitted + audited.

Proposals render as a **before/after diff** and commit on acceptance.

---

## 7. Interfaces

CLI: `chronos serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]`,
`setup`, `key-renew`, `db-upgrade`, `token-cost [--days 7]`, `export`,
`chronos say -`, `chronos get day|timer|briefing`. `--no-web`/`CHRONOS_WEB=0`
= headless API only. **No systemd, no root, no OS timezone config.** Targets:
Linux desktop/laptop, Termux on Android, Windows. Build host = `occ` prootdistro
on an Android phone (`ssh tu` → `proot-distro login occ`), Fedora 44 aarch64;
local checkout canonical, `./deploy.sh` syncs in.

Auth — **one instance key**, generated first run, printed once, stored
**Argon2-hashed**. Required on every REST request, WS upgrade, MCP call, CLI
command. Header `X-Chronos-Key`, **query-string fallback for MCP clients** that
cannot set headers; a key in a query string is **never logged**.
`chronos key-renew` rotates and disconnects every client. `/api/health` is the
only open route. Single user, no roles, no registration, no multi-tenancy.

REST (18 routes): `/api/voice`, `/api/say`, `/api/commands`, `/api/events`,
`/api/nodes`, `/api/buckets`, `/api/briefing`, `/api/search`, `/api/reminders`,
`/api/timer/{start,stop,summary,presets}`, `/api/stats`, `/api/settings` (GET+PUT),
`/api/keys/renew`, `/api/health`.

WS `/ws` — one conn per client. Server: `state` (full snapshot on connect),
`patch`, `proposal`, `question`, `timer`, `queued`, `retrying`.
Client: `hello`{key,device}, `say`, `accept|reject|skip`{proposal_id}.
**Every mutation broadcasts to all clients**; writes serialize on SQLite's write
lock, readers never block.

MCP `/mcp` — same tool set for external agents, same instance key, same
validation as the user's own voice input, every call audited. Agents query through
the *real* scheduler ("am I free tomorrow evening?").

---

## 8. Clients (context only — NOT in scope)

Web HUD is the default, served by the host: flat, dark, **no glassmorphism /
orbital-ring HUD**, no build step, plain HTML/CSS/vanilla JS. **No Django, no
framework** — a second backend means a second ORM and a second auth system for an
app whose premise is one SQLite file on one machine. Six-screen bottom nav
(tasks, calendar, timer, briefing, AI, settings) with a **persistent AI bar on
every screen** (collapsed, mic + expandable typing). **The client is thin**:
mirrors server state, owns nothing — no local DB, no localStorage except the
key, no optimistic writes, re-read after every mutation.

Android app = a separate project with its own Agent, documented separately.
`architecture.md` §3 is explicit: **"Android is not a phase."**

---

## 9. Notifications & ops

**ntfy** — Apache-2.0 server, **GPL-2.0 F-Droid Android build, no Google
services** so nothing reaches the internet. One HTTP POST per publish. Priorities
map to review-due / proposal-awaiting / timer milestones. Publishing goes through
a `Notifier` interface so Gotify can be added without touching callers; HUD also
uses the Web Notifications API when permitted.

Ops: **Android doze** kills a backgrounded server → run `termux-wake-lock` first;
`/api/health` lets a client show "server is down" instead of an endless spinner.
Embedding model ~**274 MB**, downloads on first use — announced with progress,
**never silently inside a request**.

---

## 10. Explicitly out of scope (§12 + architecture §3)

RAID · external calendar sync (ICS/Google Calendar — own renderer instead) ·
brain-training mini-games · multi-user auth · cloud vector DBs (Pinecone/Chroma
rejected as cloud) · a Node.js client / orchestration layer · glassmorphism ·
offline timer capture on clients · self-hosted NIM · **the browser client and
Android app for this agent** · Jev / TypeSafe System One decision models ·
queue+lockfile concurrency (SQLite transactions serialize writes) ·
per-event key authority · client mid-request cancel (requests are short; cancel
means stop listening) · RAID 5 · *"time-peak aliasing / utf-8 timespeak-alias"*
(explicitly flagged **hallucinated — no such standard exists**).

Two removals worth remembering because they are historical scars: **automatic
rewind on a bad review** and **unbounded review series** — both were prior-build
user complaints.

---

## 11. Build process (architecture.md v2)

**v1 was sequential and failed**: nothing could start until the prior phase landed,
and it **hid defects behind a green suite — four defects reached merged commits
because a test asserted the bug as correct.** v2 runs all six phases in parallel
against an interface frozen up front; the cost is the interface must be right
immediately, the benefit is every phase is testable from day one.

**Phase 0 = interface freeze, must complete first.** `chronos/contracts/` (every
model, enum, Protocol, tool schema — the *only* shared surface), the full DDL for
Chronos.md §4, the bucket seed, and the already-written `docs/phases/phase-*.md`.
Owned by Manager + Phase-1 Proposer. When `contracts/` is committed and tagged,
Phase 0 is done and all six phases start. A phase that finds the frozen interface
wrong **does not change it silently** — it raises a conflict and the Manager rules.

| Phase | Owns |
|---|---|
| 1 | contracts, db, core scheduling |
| 2 | ai providers, pipeline, intent, verify, packer |
| 3 | api, realtime, auth |
| 4 | web HUD, cli, mcp |
| 5 | notify, briefings, stats, search, audit, export |
| 6 | deployment: Termux, Docker, packaging, CI |

Each phase subdivides into **parts**; a part is one file or a tight file group,
owned by exactly one code agent. This is the unit of work — target **≤30 min**
(an 83-minute dive died in v1).

> Note a real inconsistency: Chronos.md §14 describes a **different, mostly
> sequential** phasing (Phase 1 foundation sequential → Phase 2 leaves ≤3 agents →
> Phase 3 integration → milestones 2/3/4 later) with a module-level dependency
> table. `architecture.md` v2 defines six parallel phases. Chronos.md wins on
> *product*, architecture.md wins on *process* — so the process to follow is the
> six-parallel-phase one, but the boundary between the two docs is genuinely
> blurry and worth a ruling.

### Agent hierarchy — five roles, **no agent ever holds two roles**

```
MANAGER (one, whole project; owns schedule, not code)
 └ PROPOSER (one per phase; owns the phase interface)
    ├ TEST agent(s)      ├ CODE agent(s) (one per part)
    └ MEDIATOR (one per phase, called only on conflict)
```

- **Manager**: ≤4 agents running at any moment (hard limit), dispatches Proposers,
  verifies every claim with real output, commits/tags with **explicit paths, never
  `git add -a`** (it has already stolen a parallel agent's untracked work),
  **never blocks on the user** (defers to `questions-for-user.md`, takes the
  recommended default, keeps building), kills looping/finished agents early.
- **Proposer**: writes the **interface proposal before any code** — every file,
  public name, signature, logic in prose. Manages its Test and Code agents
  directly; they report to the Proposer, not the Manager.
- **Test agent**: reads **spec text only, never the implementation** (writing
  tests from code "tests that the code does what the code does" — always passes,
  catches nothing). Writes `tests/phase_<n>/test_<module>_spec.py`, **cites the
  spec section in each test**, test first, failures expected. Tags every failure
  `REAL BUG` / `SPEC AMBIGUITY` / `MY TEST WRONG`. Deletes per-part scratch
  tests/probes once verified — the phase spec tests are the permanent record.
- **Code agent**: one part, one owner; satisfies tests; **may not edit any test
  file**; raises a conflict rather than "fixing" a test.
- **Mediator**: called only when the Proposer can't settle it; rules code-wrong or
  test-wrong; **may not weaken an assertion**; escalates if the *spec* is ambiguous
  rather than guessing.

### Conflict ladder — nothing skips a rung

**Escalation discipline: no agent ever contacts the Manager directly.** Every
disagreement goes up **exactly one level** to the Proposer; only the Proposer may
carry it further. Manager attention is the most expensive resource in the build —
an agent that "just flies over" has broken the process and should be sent back
down. Think ticket queue, not chat.

1. **Proposer** resolves it — most conflicts die here (usually an unclear interface
   proposal; clarifying it fixes both sides).
2. **Mediator** rules; binding on Test and Code agents.
3. **Vote** if Proposer and Mediator disagree — all four phase agents vote, **3:1 carries** (prevents one stubborn agent deadlocking a phase).
4. **Both Test and Code agents independently flag a major fault → the Proposer rethinks its own proposal** and gets Manager confirmation. The one case a Proposer escalates of its own accord.
5. **Manager** — on 2:2, or a rethink that fails. Manager **resolves** or **forwards to the user** when it turns on product intent rather than correctness. Manager's decision is final; record every ruling + reasoning in `docs/decisions.md` so the next session doesn't relitigate.

A ticket carries four things, or it is "not a conflict yet, an unfinished attempt":
(1) what is disputed — one sentence, not a narrative; (2) both positions with spec
citations; (3) **what has already been tried** — a ticket with no "already tried"
is sent straight back down; (4) evidence — failing assertion, real output,
file:line.

### Scheduling — hard ceiling of 4 concurrent agents

One slot normally the Manager's own verification/commits. Proposal stage = 1 agent;
build stage = 2 (+Mediator if called). So **~2 phases build at once**, or more if
some are still in proposal. Priority when scarce: (1) **blocked** phase (agents
need a ruling) → (2) **finishing** phase (landing a part frees the work
permanently) → (3) **proposal** stage (cheap, unblocks two agents later) →
(4) **starting fresh** (nothing depends on it yet). Exceeding four makes the
Manager slower, because it cannot verify what it cannot track.

### Definition of done

- **Part**: its tests pass, the full suite passes, Manager has seen the real output.
- **Phase**: every part done and the public surface matches the phase doc.
- **Project**: all six phases done, `scripts/smoke.sh` passes on a real boot, Chronos.md §13 coverage satisfied.

---

## 12. Test system — the four rules

1. **A test must be able to fail.** Mutate the behaviour, confirm red, restore. Banned: `assert "X" in str(SPEC)`, source-file greps, `assert True`, existence-only checks.
2. **The test author is not the implementer.** Tests first, then a *different* agent makes them pass. "The single most important rule in this folder."
3. **Never edit a test to make it pass.** The spec decides which side is wrong.
4. **A red test with a correct assertion is a deliverable.**

**Five layers**: contract tests (console script + every route over real HTTP);
real-database tests (execute the DDL, read back through the enum — **never grep
it**); interface tests against a real booted server; spec-derived acceptance tests
written first; `scripts/smoke.sh` as the gate.

**Gates before any phase is done**: phase tests pass · full suite 0 failures ·
`ruff check chronos tests` = **0** · `smoke.sh` exit 0 · contract tests reach every
entry point · every `Done means` box has a test that fails if broken · an
independent agent gave a green-light verdict.

`smoke.sh` is the gate because **a green unit suite is not a running app** — the
exact failure mode that killed the last build. Contract tests first catches the
entire "code exists but nothing calls it" class.

**Chronos.md §13 required coverage**: conflict push-back maths · bucket boundary
seeding · series termination enforcement · key auth · timezone round-trips ·
retry/failover against fake providers · hierarchy reuse thresholds · one
end-to-end AI path with a stub model. Timer coverage **needs a real DB** because
the behaviours are relational, not arithmetic: only one session at a time across
all three modes · a stopwatch ignores a target sent to it · a task's time rolls up
to its project · a pomodoro break is excluded from work totals · a focus phase
stopped early is not a completed cycle.

---

## 13. REBUILD.md known-broken list (if the code survives — verify each by running it, don't re-diagnose)

| Area | Fault |
|---|---|
| Review series | DDL had wrong state set *and* wrong case → every insert failed; spec wants `active\|retired\|cancelled` with **no** CHECK |
| Search | `node_fts` external-content (`content=''`) with TEXT uuid as `rowid` → `datatype mismatch`; **nothing could ever be indexed**, search silently returned empty forever. Fixed via SHA-256→INTEGER rowid |
| ~half the API 500s | `DatabaseEngine.conn` is thread-local but `create_app` captured the boot-thread connection → `SettingsRepoProxy` |
| Timer maths inverted | filtered `mode != 'stopwatch'` → **stopwatch logged zero**, pomodoro breaks **inflated** totals (spec §4.7 is the opposite) |
| Timezone | `tz = UTC` hardcoded, `instance.timezone` ignored for every day boundary → a 4pm task lands at the wrong hour |
| DDL defaults | five uppercase defaults (`events.kind`, `reminders.state`, `reminders.channel`, `timer_sessions.mode`, `timer_sessions.cycle`) — last also `TEXT` where spec says `INTEGER` |
| `/ws` | missing `websocket.accept()`; also needed `websockets>=12.0` because uvicorn shipped no WS implementation and Starlette's `TestClient` masked it |
| `/api/commands` | returns `success: true` while unimplemented — **it lies** |
| Ambiguous sentences | guess a time instead of calling `ask_question` (spec §5.5/§5.7) |
| `/ws` `say` | no proposal pushed over the socket → accept/reject never exercised there (REST works) |
| Phase 5 regression | `test_missing_vec_table_degrades_to_keywords_only` fails after the FTS change — decide whether the fallback or the test is wrong |
| Phase 6 | 2–3 failing: `test_compose_healthcheck_and_ports_agree_with_the_image`, `test_termux_health_check_polls_rather_than_sleeps` (the latter asserts on a Termux script that **cannot run on this host at all**) |
| Setup | `chronos setup` covers providers + embeddings but **does not ask for timezone**; no `scripts/setup.sh` for Linux — spec §8.1's primary target |
| Ruff | ~140 errors, must reach 0 |

Note the recurring shape of most of these: a test or a DDL asserted the
*opposite* of the spec and thereby locked the bug in. This is precisely the v1
failure mode architecture.md §7 was written about.

---

## 14. REBUILD.md Manager operating rules — learned the hard way

- **One writer per file.** Two agents on one file = silent overwrite.
- **Plain `terminal` only.** `execute_code` + grep/search crashes this project repeatedly — **it killed 5 of 9 audit agents with zero deliverables.** (Directly relevant: this digest task used the file tools, not that path.)
- **Write files first, then test. Read ≤5 files before editing.**
- **Scope every pytest run to the agent's own directory.** Never bare `tests/` — three agents doing that turned 100s runs into 400s timeouts.
- **Never foreground `sleep`, never foreground a server.** Background it or the call wedges forever. Two agents lost to this.
- **Split large scope by file. Target ≤30 min.**
- **Verify every agent claim yourself.** Every number in any doc must come from a run you performed.
- **Have an adversary check the fixers.** One audit caught a false "green" claim, a false "I didn't touch that file" claim, and a stale xfail.
- **A phase's CI must not depend on commands the project hasn't made green.** That alone got phase 6 judged UNMAINTAINABLE.
- **Unverifiable stays UNTESTED, honestly.**
- **Record every lesson**, don't re-derive it next session.
- Explicit paths in `git`, never `git add -a`.
- Never commit a secret; `.env` is never committed.

REBUILD's ordered next actions: (1) settle proot — blocked; (2) re-measure every
suite, update `docs/schedule.md`; (3) contract tests for console script + every
route; (4) work the known-broken list; (5) implement `scheduling-behaviour.md`
(clarification + timezone prompt — "the product's core interaction"); (6) build
the client per `client-build-spec.md`; (7) hand Android to the Android Agent;
(8) ruff → 0; (9) commit + tag per phase.

---

## 15. Environment

proot-distro container `Chronos`, **aarch64**, **Fedora 44**. No systemd, no
Docker daemon, no Android.

**Use `/usr/bin/python3` explicitly** — bare `python3` may resolve to an agent
runtime's private interpreter, producing a venv the user cannot run. This cost
hours once.

```bash
cd <checkout>
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests -q
```

**Cannot be verified here, ever** — mark honestly, delegate to CI, never claim
what you could not run: `docker build`, `docker compose up`,
volume-survives-replacement, image size, daemon HEALTHCHECK, and every
Termux/Android path.

---

## 16. Referenced but not in this brief

`errors-and-test-proposal.md` (README/START-HERE name it `errors-and-test-proposal.md`,
REBUILD names it `rebuild-lessons-and-test-proposal.md` — **filename mismatch,
probably the same doc**), `contract-and-interfaces.md` (the frozen API surface),
`scheduling-behaviour.md` (buckets, proposals, when the AI must ask),
`phases/` (6 phase docs), `proposals/` (frozen interface proposals — settled,
don't relitigate), `manager.md`, `decisions.md`, `proot-distro.md`,
`mobile-hud.md`, `client-build-spec.md`, `android-app.md`, `agents.md`,
`questions-for-user.md`, `tickets.md`, `docs/notifications.md`,
`docs/schedule.md`, `docs/experimental/android.md`.

---

## 17. Three things to resolve before writing any code

1. **Does code exist or not?** README/START-HERE say zero; REBUILD describes ~815 tests and 15 diagnosed bugs. Measure the tree; do not trust either.
2. **Which filesystem is the user's?** proot path translation invalidated every prior local verification. Settle it and put the answer at the top of `docs/schedule.md`.
3. **Which phasing is authoritative?** Chronos.md §14's mostly-sequential plan vs architecture.md v2's six parallel phases. Chronos.md wins product, architecture.md wins process — a ruling belongs in `decisions.md`.