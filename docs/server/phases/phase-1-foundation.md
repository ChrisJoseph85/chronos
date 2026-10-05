# Phase 1 — Foundation (contracts + db + core scheduling + ai providers/pipeline)

> **MIGRATION NOTE (2026-10-05, reason: maintainability):** This document merges
> old `phase-1-core.md` (old Phase 1, parts 1.1–1.6) and old `phase-2-ai.md`
> (old Phase 2, parts 2.1–2.8) into one new Phase 1 ("Foundation").
> Old → new mapping: 1.1→1.1, 1.2→1.2, 1.3→1.3, 1.4→1.4, 1.5→1.5, 1.6→1.6,
> 2.1→1.7, 2.2→1.8, 2.3→1.9, 2.4→1.10, 2.5→1.11, 2.6→1.12, 2.7→1.13, 2.8→1.14.
> Old phase numbers 3–6 are unchanged. Old docs `phase-1-core.md` and
> `phase-2-ai.md` are superseded by this file. Test suite merged:
> `tests/phase_1/*` (old phase_1 84 tests) + `tests/phase_2/*` renamed with
> `test_ai_*` prefix (old phase_2 68 tests) = 152 tests total.
>
> **MIGRATION NOTE (round 2, 2026-10-05, reason: maintainability):** This
> document additionally folds old `phase-3-server.md` (old Phase 3, parts
> 3.1–3.6) into this Phase 1 as new parts 1.15–1.20. Old → new mapping:
> 3.1→1.15 (app factory), 3.2→1.16 (auth), 3.3→1.17 (REST routes),
> 3.4→1.18 (voice route), 3.5→1.19 (realtime hub), 3.6→1.20 (smoke script).
> Old doc `phase-3-server.md` is superseded by this file. Test suite merged:
> `tests/phase_1/*` (152 tests) + `tests/phase_3/*` renamed with `test_srv_*`
> prefix (old phase_3 133 tests) = 285 tests total. Old phase numbers 4–6
> are unchanged.
>
> **MIGRATION NOTE (round 3, 2026-10-05, reason: maintainability):** This
> document additionally folds old `phase-4-interfaces.md` (old Phase 4, parts
> 4.4–4.5) into this Phase 1 as new parts 1.21–1.22. Old → new mapping:
> 4.4→1.21 (CLI), 4.5→1.22 (MCP). Old doc `phase-4-interfaces.md` is
> superseded by this file. Test suite merged: `tests/phase_1/*` (285 tests)
> + `tests/phase_4/*` renamed with `test_if_*` prefix (old phase_4 36 tests)
> = 321 tests total. Old phase numbers 5–6 are unchanged.
>
> **MIGRATION NOTE (round 4, 2026-10-05, reason: maintainability):** This
> document additionally folds old `phase-5-features.md` (old Phase 5, parts
> 5.1–5.6) into this Phase 1 as new parts 1.23–1.28. Old → new mapping:
> 5.1→1.23 (notify), 5.2→1.24 (search), 5.3→1.25 (briefings), 5.4→1.26
> (stats), 5.5→1.27 (audit), 5.6→1.28 (export). Old doc
> `phase-5-features.md` is superseded by this file. Test suite merged:
> `tests/phase_1/*` (321 tests) + `tests/phase_5/*` renamed with
> `test_feat_*` prefix (old phase_5 43 tests) = 364 tests total.

**Runs in parallel with phases 3–6.** Owns the frozen surface everything else
builds against, so this phase's **proposal stage gates the whole project**.

Spec: `docs/Chronos.md` §4 (data model), §4.8 (vector + full-text search),
§5 (AI layer), §6 (scheduling and conflict rules, semantic duplicate check),
§7 (time), §13 (testing).

---

## Parts

| New | Old | Files | Owner |
|---|---|---|---|
| 1.1 contracts | 1.1 | `chronos/contracts/` | one code agent |
| 1.2 db engine + schema | 1.2 | `chronos/db/engine.py`, `bootstrap.py`, `orm.py` | one code agent |
| 1.3 bucket seed | 1.3 | `chronos/db/buckets.py` | one code agent |
| 1.4 repo | 1.4 | `chronos/db/repo.py` | one code agent |
| 1.5 core scheduling | 1.5 | `chronos/core/scheduling.py` | one code agent |
| 1.6 migrations | 1.6 | `alembic/` | one code agent |
| 1.7 provider adapter | 2.1 | `chronos/ai/providers/adapter.py` | one code agent |
| 1.8 provider chain | 2.2 | `chronos/ai/providers/chain.py` | one code agent |
| 1.9 retry worker | 2.3 | `chronos/ai/providers/worker.py` | one code agent |
| 1.10 speech (STT) | 2.4 | `chronos/ai/providers/stt.py` | one code agent |
| 1.11 context packer | 2.5 | `chronos/ai/pipeline/packer.py` | one code agent |
| 1.12 intent + verify | 2.6 | `chronos/ai/pipeline/intent.py`, `verify.py` | one code agent |
| 1.13 tool dispatcher | 2.7 | `chronos/ai/pipeline/tools.py` | one code agent |
| 1.14 cost + prices | 2.8 | `chronos/ai/cost.py`, `prices.py`, `cost_hook.py` | one code agent |
| 1.15 app factory | 3.1 | `chronos/api/app.py` | one code agent |
| 1.16 auth | 3.2 | `chronos/api/auth.py` | one code agent |
| 1.17 REST routes | 3.3 | `chronos/api/routes.py` | one code agent |
| 1.18 voice route | 3.4 | `chronos/api/voice.py` | one code agent |
| 1.19 realtime hub | 3.5 | `chronos/realtime/` | one code agent |
| 1.20 smoke script | 3.6 | `scripts/smoke.sh` | one code agent |
| 1.21 CLI | 4.4 | `chronos/cli/` | one code agent |
| 1.22 MCP | 4.5 | `chronos/mcp/` | one code agent |
| 1.23 notify + reminders | 5.1 | `chronos/notify/` | one code agent |
| 1.24 search | 5.2 | `chronos/db/search.py` | one code agent |
| 1.25 briefings + budget | 5.3 | `chronos/ai/briefings.py` | one code agent |
| 1.26 stats | 5.4 | `chronos/ai/stats.py` | one code agent |
| 1.27 audit viewer | 5.5 | `chronos/db/audit.py` | one code agent |
| 1.28 CSV export | 5.6 | `chronos/ai/export.py` | one code agent |

Part 1.1 must land before 1.2–1.14 start. Parts 1.2–1.6 can run in parallel
with each other; parts 1.7–1.10 are independent of 1.11–1.14; all within the
four-agent ceiling once the interface proposal is frozen.

---

## Interface this phase owns

Everything in `chronos/contracts/`. **This is the frozen shared surface.** After
Phase 0 it changes only by deliberate, announced act. See old Phase 1 §
"Interface this phase owns" (models, enums, `ToolCall`/`ToolResult`/
`TOOL_SCHEMAS` for the 27 tools in §5.5, repo/`Clock`/`IdGen`/`Embedder`/
`Notifier`/`SearchBackend` protocols, DAG import graph).

---

## Behaviour summary (see spec; full detail in `docs/Chronos.md`)

Foundation behaviour = old Phase 1 behaviour + old Phase 2 behaviour.
Pointers only; do not duplicate spec text here:

- Contracts / DB / buckets / repo: §4, §4.3, §7.1 (see old § "Behaviour the
  tests must pin": Buckets, Events, Timezone).
- Core scheduling (conflicts, push-to-free-minute, review series, schedules,
  timers): §4.2, §4.4, §4.5, §4.7, §6, §7.2.
- AI providers (one OpenAI-compatible adapter, models, interactive setup): §5.1.
- Retry and failover (never raises, background worker, backoff+jitter,
  token-cost table): §5.2.
- Roles: §5.3.
- Context packer (ceiling, priority order, cuts, current-time-in-prefix): §5.6.
- Intent + verify (absolute ISO dates, verify-pass corrections, second turn on
  lookup-only): §5.3, §5.5.
- Tool dispatcher (27 tools, one-call series, no move tool, code-resolved
  blocks): §5.5.
- Cost (`cost_usd` from real price table, `None` on unknown): §5.2, §4.7.
- Search backing (vector + full-text): §4.8.

Cite spec § stays intact in the merged test files.

---

## Done means

- [ ] `contracts/` import graph is a DAG with no cycles
- [ ] a fresh database seeds 10 years of nested Y→M→W→D buckets, counts as above
- [ ] every day bucket's parent resolves to a week; the chain walks cleanly to a year
- [ ] repo round-trips every entity, with cascades
- [ ] the bounded-series rule is enforced at both the repo and the schema
- [ ] one-timer-at-a-time and stopwatch-ignores-target are enforced
- [ ] `core/` is pure — its tests run in milliseconds with no database
- [ ] one adapter, three configurations; no provider-specific code paths
- [ ] failover never raises, with backoff and jitter, verified against fakes
- [ ] every attempt — success and failure — lands in the token-cost table
- [ ] the packer respects its ceiling, drops lowest-priority first, records cuts
- [ ] the current time is in the prefix
- [ ] a lookup-only turn triggers a second turn
- [ ] all 27 tools dispatch; none stubbed; no move tool exists
- [ ] an unbounded series is refused by the dispatcher
- [ ] `cost_usd` is `None`, not `0.0`, when the price is unknown
- [ ] `scripts/smoke.sh` boots the real server and passes every check
- [ ] 401 without a key on every authenticated route; `/api/health` open
- [ ] the query-string key never reaches a log line
- [ ] one English sentence commits a real event, read back out of SQLite
- [ ] `create_app(db_path=...)` opens that exact file
- [ ] starting a second timer returns 409, not a crash
- [ ] the hub fans out to all connected clients
- [ ] every CLI command in §9.2 runs and produces real output
- [ ] `serve` finds the factory and forwards `--db`
- [ ] `db-upgrade` completes and creates the schema in the `CHRONOS_DB` file
- [ ] the MCP tool list matches the contracts exactly; no tool stubbed
- [ ] unauthenticated MCP calls are rejected; every call is audited
- [ ] one definition of `DEFAULT_REMINDER_OFFSETS_MIN`
- [ ] due reminders fire; cancelled ones do not
- [ ] search degrades without raising; scores absolute; bm25 kept distinct
- [ ] nodes are indexed on create/update/delete; an absent FTS table never breaks a write
- [ ] a duplicate is caught semantically, not by title match
- [ ] tags and nodes are reused, never duplicated
- [ ] the briefing varies with its data
- [ ] **the clarification budget survives a process restart**
- [ ] `cost_usd` is non-zero for a known price and `None` for an unknown one
- [ ] the audit log filters and is read-only
- [ ] a CSV export opens cleanly and has no fake zeros
- [ ] full suite green
- [ ] per-part scratch tests and probe scripts deleted; the phase's spec tests kept
      (`manager.md` §10)

---

## Verification

```bash
.venv/bin/python -m pytest tests/phase_1 -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check chronos tests
./scripts/smoke.sh 8099          # the real proof for parts 1.15–1.20: boots the server over HTTP
```

`chronos/core/` tests must run in milliseconds. If they need a database, the
logic is in the wrong module. No AI-layer test may touch the network. Inject
fake providers.

---

## OWNERSHIP-PROPOSAL (for the manager, who alone edits MANAGER-PLAN.md)

Proposed new ownership row for merged Phase 1:

| Phase | Test files | Code files |
|---|---|---|
| 1 Foundation | `tests/phase_1/*` | `chronos/contracts/` `chronos/db/` `chronos/core/` `chronos/ai/` `chronos/notify/` `chronos/db/search.py` `chronos/db/audit.py` `chronos/ai/briefings.py` `chronos/ai/stats.py` `chronos/ai/export.py` `chronos/api/` `chronos/realtime/` `scripts/smoke.sh` `chronos/cli/` `chronos/mcp/` |

Note: old phase numbers 3–6 are unchanged. Old `tests/phase_2/` is deleted
(contents moved to `tests/phase_1/test_ai_*`). Old docs `phase-1-core.md` and
`phase-2-ai.md` are superseded by `phase-1-foundation.md`.

Note (round 2, 2026-10-05): old `tests/phase_3/` is deleted (contents moved to
`tests/phase_1/test_srv_*`). Old doc `phase-3-server.md` is superseded by
`phase-1-foundation.md` (old Phase 3 parts 3.1–3.6 → new parts 1.15–1.20).
Old phase numbers 4–6 are unchanged.

Note (round 3, 2026-10-05): old `tests/phase_4/` is deleted (contents moved to
`tests/phase_1/test_if_*`: `test_cli_spec.py` → `test_if_cli_spec.py`,
`test_mcp_spec.py` → `test_if_mcp_spec.py`, byte-identical). Old doc
`phase-4-interfaces.md` is superseded by `phase-1-foundation.md` (old Phase 4
parts 4.4→1.21 CLI, 4.5→1.22 MCP). Old phase numbers 5–6 are unchanged.

Note (round 4, 2026-10-05): old `tests/phase_5/` is deleted (contents moved to
`tests/phase_1/test_feat_*`: `test_notify_spec.py` →
`test_feat_notify_spec.py`, `test_search_spec.py` →
`test_feat_search_spec.py`, `test_briefing_spec.py` →
`test_feat_briefing_spec.py`, `test_stats_audit_export_spec.py` →
`test_feat_stats_audit_export_spec.py`, byte-identical). Old doc
`phase-5-features.md` is superseded by `phase-1-foundation.md` (old Phase 5
parts 5.1→1.23 notify `chronos/notify/`, 5.2→1.24 search
`chronos/db/search.py`, 5.3→1.25 briefings `chronos/ai/briefings.py`,
5.4→1.26 stats `chronos/ai/stats.py`, 5.5→1.27 audit `chronos/db/audit.py`,
5.6→1.28 export `chronos/ai/export.py`). 321+43=364 tests total.
