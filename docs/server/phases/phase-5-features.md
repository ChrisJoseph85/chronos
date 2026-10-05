# Phase 5 — Features (notify, briefings, stats, search, audit, export)

**Runs in parallel with phases 1–4 and 6.** Depends on the frozen contracts and on
the repo interface from phase 1. Its routes are registered in the phase 3 factory.

Spec: `docs/Chronos.md` §4.4 (series), §4.5 (schedules), §4.6 (reminders),
§4.7 (timer, audit, cost), §4.8 (search), §5.4 (hierarchy reuse), §5.7
(clarification budget), §6 (semantic duplicate check), §9.1 (briefing), §10
(notifications).

---

## Parts

| Part | Files | Owner |
|---|---|---|
| 5.1 ntfy + reminder scheduler | `chronos/notify/` | one code agent |
| 5.2 search | `chronos/db/search.py` | one code agent |
| 5.3 briefings + budget | `chronos/ai/briefings.py` | one code agent |
| 5.4 stats | `chronos/ai/stats.py` | one code agent |
| 5.5 audit viewer | `chronos/db/audit.py` | one code agent |
| 5.6 CSV export | `chronos/ai/export.py` | one code agent |

All six are independent once the interface proposal is frozen.

---

## Behaviour the tests must pin

**Notifications (§4.6, §10)**
- ntfy is the only backend in scope, behind a `Notifier` interface so Gotify can
  be added without touching callers. One HTTP POST per publish.
- `DEFAULT_REMINDER_OFFSETS_MIN` has **exactly one definition** in the whole
  project: `[10, 0]` — 10 minutes before, and at the start. *(v1 defined it twice
  and they drifted.)*
- A reminder row is a real row, cancellable individually. The scheduler runs on
  the realtime tick and publishes anything due. Cancelled reminders never fire.

**Search (§4.8, §6)**
- Three stages, all on the host: FTS5 narrows candidates on keywords, sqlite-vec
  ranks by cosine similarity, then the model judges whether the top hits are
  genuine duplicates.
- **Degrade at every step: a missing vec table means keywords only. Never raise.**
- Scores are **absolute**. A normalised score means the reuse threshold can never
  fire.
- **bm25 is not a similarity.** Keyword rank and vector distance are different
  quantities and must be surfaced as distinct fields.
- Search must work against **both** a SQLAlchemy `Session` (what the app uses) and
  a raw `sqlite3.Connection` (what tests pass). v1 shipped a version that silently
  returned nothing under a Session because a broad `except` swallowed the
  argument error. Narrow the catch.
- **Nodes must actually be indexed.** v1 shipped `create_node` that never wrote to
  the FTS table, so search returned nothing in the real app while the search
  tests passed. Index on create, re-index on update, remove on delete — and make
  it best-effort: an absent FTS table must never break a write.

**Duplicate check (§6)**
- Before a create, search over ±1 day surfaces candidates that look like the same
  work. It **warns and proposes; it never moves anything.**
- The window may be widened through `check_conflict`, up to ±7 days.
- Hierarchy reuse (§5.4): before creating a node, search for an existing match and
  reuse above a similarity threshold. **Tags are never duplicated** — an existing
  tag by name is always reused.

**Briefings (§9.1, §5.7)**
- Content: unallocated tasks for today, unallocated tasks for this week, rollover,
  due reviews, and **at most one question**.
- Briefings are **generated, not templated** — the content must vary with the
  underlying data. A fixed template is not a briefing.
- The clarification budget is **one question per day**, queued in the briefing
  panel rather than blocking. When the day's budget is spent, questions roll into
  tomorrow's.
- **The budget must persist across a process restart.** *(v1's triage recorded
  this exact failure: "counter is in memory, not persisted". A fresh object built
  from the same database must see the day as spent.)*
- The briefing reports what it considered — "checked 30 tasks, showing 8".

**Stats (§8.2, §4.7)**
- Counts, streaks, and token spend by day.
- `cost_usd` comes from a real price table. An unknown price is `None` — **never a
  fake `0.0`**.
- Every provider attempt, failed or not, is recorded.
- Audit retention is 7 days; log retention is 7 days.

**Audit viewer (§4.7)**
- Browsable and **filterable** by action, by target and by time range.
- Read-only. Rows older than 7 days are excluded.

**CSV export**
- Events, timers and cost. A header row; one row per record.
- Values containing commas, quotes or newlines are quoted so the file **opens
  cleanly in a spreadsheet**.
- An unknown cost is an **empty cell** — not `0.0`, not `None`.

---

## Done means

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
.venv/bin/python -m pytest tests/phase_5 -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check chronos tests
```

No test may touch the network. Inject fakes.
