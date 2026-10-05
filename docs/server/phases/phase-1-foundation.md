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
- [ ] full suite green
- [ ] per-part scratch tests and probe scripts deleted; the phase's spec tests kept
      (`manager.md` §10)

---

## Verification

```bash
.venv/bin/python -m pytest tests/phase_1 -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check chronos tests
```

`chronos/core/` tests must run in milliseconds. If they need a database, the
logic is in the wrong module. No AI-layer test may touch the network. Inject
fake providers.

---

## OWNERSHIP-PROPOSAL (for the manager, who alone edits MANAGER-PLAN.md)

Proposed new ownership row for merged Phase 1:

| Phase | Test files | Code files |
|---|---|---|
| 1 Foundation | `tests/phase_1/*` | `chronos/contracts/` `chronos/db/` `chronos/core/` `chronos/ai/` minus `briefings/`/`stats`/`export` which stay Phase 5 |

Note: old phase numbers 3–6 are unchanged. Old `tests/phase_2/` is deleted
(contents moved to `tests/phase_1/test_ai_*`). Old docs `phase-1-core.md` and
`phase-2-ai.md` are superseded by `phase-1-foundation.md`.
