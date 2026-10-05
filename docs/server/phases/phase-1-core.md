# Phase 1 — Core (contracts, db, scheduling)

**Runs in parallel with phases 2–6.** Owns the frozen surface everything else
builds against, so this phase's **proposal stage gates the whole project**.

Spec: `docs/Chronos.md` §4 (data model), §6 (scheduling and conflict rules),
§7 (time), §13 (testing).

---

## Parts

| Part | Files | Owner |
|---|---|---|
| 1.1 contracts | `chronos/contracts/` | one code agent |
| 1.2 db engine + schema | `chronos/db/engine.py`, `bootstrap.py`, `orm.py` | one code agent |
| 1.3 bucket seed | `chronos/db/buckets.py` | one code agent |
| 1.4 repo | `chronos/db/repo.py` | one code agent |
| 1.5 core scheduling | `chronos/core/scheduling.py` | one code agent |
| 1.6 migrations | `alembic/` | one code agent |

Part 1.1 must land before 1.2–1.6 start. Parts 1.2–1.6 can then run in parallel
within the four-agent ceiling.

---

## Interface this phase owns

Everything in `chronos/contracts/`. **This is the frozen shared surface.** After
Phase 0 it changes only by deliberate, announced act.

- Models for every entity in `Chronos.md` §4: `Node`, `Tag`, `NodeTag`, `Event`,
  `Bucket`, `ReviewSeries`, `Schedule`, `Reminder`, `TimerSession`, `AuditEntry`.
- Enums: `NodeKind`, `NodeStatus`, `EventKind`, `SeriesState`, `TimerMode`,
  `TimerPhase`, `ReminderState`, `BucketLevel`, `ReviewTier`.
- `ToolCall`, `ToolResult`, `TOOL_SCHEMAS` for the 27 tools in §5.5.
- Protocols: the repo protocols and `Clock`, `IdGen`, `Embedder`, `Notifier`,
  `SearchBackend`.
- The import graph must be a DAG with no cycles.

---

## Behaviour the tests must pin

**Buckets (§4.3)**
- A fresh database seeds **exactly 10 years** forward: 10 year, ~120 month,
  ~522 week, ~3653 day rows — about 4,300 total.
- The chain is nested **Y → M → W → D**. A day's parent is the **week** that
  contains it; a week's parent is its month; a month's parent is its year.
  *(v1 shipped with every day parented to a month. Do not repeat it.)*
- Bucket ids follow `Y:2026` / `M:2026-08` / `W:2026-W31` / `D:2026-08-04`, and a
  week id's number equals the **ISO week of its own start date**.
- The seed is idempotent.

**Events (§4.2, §6)**
- Times are UTC epoch **milliseconds**, stored as integers.
- Overlap detection is a plain range query.
- `soft_deleted` events are **not** conflicts.

**Scheduling (§6, §7.2)**
- An event overlapping an existing **non-deleted** event is pushed to the first
  free minute satisfying duration, hard blocks and day bounds. Deterministic.
- The result carries **both** the requested and the actual slot.
- The grid is **1 minute**: start and end snap to the minute.
- A negative duration is rejected, not silently accepted.

**Review series (§4.4)**
- Default tiers, as day offsets: hard `1,2,4,8,16`; medium `3,7,15,30`;
  easy `10,30,90`.
- A series **must be bounded** — `max_count` and/or `ends_on_ms`, at least one.
  An unbounded series is refused. *(v1 shipped a version that wrote zero review
  events and another that accepted unbounded series. Do not repeat either.)*
- Creating a series writes **all** its review events in one transaction, each
  carrying `series_id`, `review_index` and `derived_from = anchor_node_id`.
- No geometric/GP formulas. No automatic rewind.

**Schedules (§4.5)**
- Every schedule is bounded by a start and end date and may exclude weekdays.
- `paused` schedules do not block. Non-`hard_block` schedules do not block.

**Timers (§4.7)**
- **One timer runs at a time**, across all three modes.
- A **stopwatch ignores a target** — it must not become a countdown.
- A pomodoro **break** is excluded from work totals but still recorded.
- A focus phase stopped early is **not** a completed cycle.
- Logged time is reported per node: the node's own total, the total including
  descendants, and the project total for a tagged task. The project is resolved
  by walking `parent_id` up to the nearest ancestor project.

**Timezone (§7.1)**
- One instance timezone. Local wall time → UTC on every write and render.
  Round-trips preserve the instant.

---

## Done means

- [ ] `contracts/` import graph is a DAG with no cycles
- [ ] a fresh database seeds 10 years of nested Y→M→W→D buckets, counts as above
- [ ] every day bucket's parent resolves to a week; the chain walks cleanly to a year
- [ ] repo round-trips every entity, with cascades
- [ ] the bounded-series rule is enforced at both the repo and the schema
- [ ] one-timer-at-a-time and stopwatch-ignores-target are enforced
- [ ] `core/` is pure — its tests run in milliseconds with no database
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
logic is in the wrong module.
