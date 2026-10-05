# Phase 5 audit — `tests/phase_5/test_features_spec.py` vs spec & phase doc

Read-only audit. No files were modified. Probe scripts live in the scratch dir
(`/root/.hermes/cache/scratch/p*.py`) and are not part of the repo.

## 0. Current state (STEP 1)

```
$ cd /root/Chronos && .venv/bin/python -m pytest tests/phase_5 -q
25 failed, 30 passed in 1.96s
```

**All 25 failures are in `chronos/ai/`** — `briefings.py`, `stats.py`, `export.py`,
files another agent owns in flight. Breakdown of cause:

| Cause | Count |
|---|---|
| `ImportError: cannot import name 'generate_briefing' from chronos.ai.briefings` | 7 |
| `ImportError: cannot import name 'get_stats' from chronos.ai.stats` | 6 |
| `TypeError: ClarificationBudget.__init__() missing 1 required positional argument: 'clock'` | 3 |
| `ImportError: cannot import name 'export_events_csv' from chronos.ai.export` | 3 |
| `ImportError: cannot import name 'find_or_create_node' from chronos.ai.briefings` | 2 |
| `ImportError: cannot import name 'export_cost_csv' from chronos.ai.export` | 2 |
| `ImportError: cannot import name 'find_or_create_tag' from chronos.ai.briefings` | 1 |
| `ImportError: cannot import name 'export_timers_csv' from chronos.ai.export` | 1 |

Classification: these are **TEST bug (wrong API shape assumed)**, not code bugs.
The modules export `StatsCollector`, `CSVExporter`, `BriefingGenerator`,
`ClarificationBudget(db, clock)` — class-based, contract-shaped. The tests were
written against free functions (`get_stats(db=...)`, `generate_briefing(db=...)`,
`export_events_csv(db, output)`) that do not exist and never did. Per instruction I
have not analysed the `chronos/ai/` implementations deeply. **Note for the owning
agent:** the question is whether to add free-function shims or to rewrite these 25
tests against the real class APIs. Do not "fix" it by adding wrappers just to make
tests green without deciding which API is canonical.

The 30 passing tests are in `chronos/notify/`, `chronos/db/search.py`,
`chronos/db/audit.py`. Several of those pass vacuously — see below.

---

## 1. FINDING (CRITICAL): the contentless-FTS workaround makes `keyword_score`
##    permanently `None`, and the degradation tests pass on the LIKE fallback

### 1a. The data proves no real FTS result can ever resolve to a node

Frozen contract `chronos/contracts/ddl.py:125`:

```sql
CREATE VIRTUAL TABLE node_fts USING fts5(title, notes, content='');
```

`content=''` is a **contentless** table. Its `rowid` is a synthetic INTEGER, not
the node id. Probe:

```
$ .venv/bin/python .../p1.py
fts rowids: [(1,)]                      # node id is 'node-1'; FTS rowid is 1
--- probe: does FTS MATCH work at all on this table? ---
[(1, -1e-06)]                           # FTS itself works fine and yields a bm25
--- search via search_nodes ---
results: [('node-1', None, None, None)] # keyword_score=None, vector_distance=None
```

`search_nodes` did return `node-1`. It did **not** come from FTS. It came from the
LIKE fallback. Instrumenting `_like_fallback` proves it:

```
$ .venv/bin/python .../p2.py
=== C. is the LIKE fallback what made B pass? Instrument it ===
  _like_fallback invoked with: ['Test']
```

`_keyword_stage` (`search.py:600-607`) resolves each FTS rowid via `_node_exists`;
rowid `1` is not a node id, so `resolved` is empty and it drops to
`_like_fallback`. `_like_fallback` documents its own poverty (`search.py:652-654`):
*"This produces NO bm25 value ... so keyword_score stays None."*

### 1b. `bm25` is `None` for a **second, independent** reason — a real code bug

`_row_value` resolves a positional row by index using
`_FTS_COLUMN_ORDER = ("node_id", "title", "bm25", "vec_distance")`
(`search.py:529`). But the actual query is:

```sql
SELECT rowid AS node_id, bm25(node_fts) AS bm25 FROM node_fts ...
```

which yields a 2-tuple `(node_id, bm25)`. `bm25` sits at index **1**, the table maps
it to index **2**. Probe:

```
$ .venv/bin/python .../p3.py
=== F. _row_value tuple-index bug ===
  raw sqlite row: [(1, -1e-06)]
  _row_value(row,'bm25') -> None
  _FTS_COLUMN_ORDER = ('node_id', 'title', 'bm25', 'vec_distance')
  => bm25 is at tuple index 1 but _FTS_COLUMN_ORDER maps it to index 2 -> ALWAYS None
=== G. same query with dict row_factory ===
  dict row: {'node_id': 1, 'bm25': -1e-06} -> _row_value: -1e-06
```

So `keyword_score`/`bm25` is `None` for **every** code path that returns positional
rows, independent of the contentless-rowid problem. Only a `sqlite3.Row` factory
recovers it. This is a genuine CODE bug (`search.py:529`) that no test catches,
because no test asserts a non-`None` bm25 anywhere.

**Answer to "is bm25/keyword_score ever genuinely produced?" — No.** Not once, on any
code path exercised by these tests or reachable in the real app.

### 1c. `index_node` **raises `IntegrityError`** against the real schema

```
=== E. index_node on REAL schema ===
  RAISES: IntegrityError datatype mismatch  <-- only OperationalError is caught!
```

`index_node` (`search.py:877`) writes `INSERT INTO node_fts(rowid, title, notes)
VALUES (node_id, ...)` where `node_id` is a TEXT uuid. `node_fts.rowid` is INTEGER.
Only `sqlite3.OperationalError` is caught (`search.py:881`), so `IntegrityError`
propagates.

```
=== K. what happens when node_fts insert fails with a NON-OperationalError? ===
  PROPAGATES: IntegrityError datatype mismatch <-- breaks the 'never breaks a write' contract
```

This directly violates the phase doc "Done means": *"nodes are indexed on
create/update/delete; an absent FTS table never breaks a write"* and §4.8/phase-5
*"an absent FTS table must never break a write"*. In the real app a node create
would raise. **This is the v1 defect re-created with a different error type**: v1's
`create_node` "never wrote to the FTS table, so search returned nothing in the real
app while the search tests passed" — here `create_node` writes and *crashes*, while
the tests pass.

### 1d. Which tests are testing FTS, and which are testing the workaround?

| Test | What it actually proves |
|---|---|
| `test_missing_vec_table_degrades_to_keywords_only` | Asserts `len(results) > 0`. Proved by `_like_fallback`, **not** FTS. Passes on a total FTS failure. |
| `test_missing_fts_table_still_works` | Asserts **nothing**. `results` is discarded. Passes if the function returns `[]`, `None`, or raises-and-is-caught. |
| `test_search_with_sqlalchemy_session` | Asserts **nothing**, against an **empty** in-memory DB with no tables. This is the v1 defect *reproduced inside the test*: a Session that silently returns nothing. |
| `test_search_with_sqlite3_connection` | Asserts **nothing**; only that it doesn't blow up. |
| `test_fts5_narrows_candidates` | Asserts `call_order[0] == 'fts5'`, where the mock's `side_effect` **appends `'fts5'` on every `db.execute`**. It proves a `db.execute` happened first, not that FTS ran. The first execute in `search_nodes` is the `sqlite_master` existence probe. |
| `test_bm25_and_vector_distance_are_distinct_fields` | Asserts `'bm25' in r or 'keyword_score' in r` — a **key-presence** check. `_shape_results` always writes those keys, value `None` included. Passes with every score `None`. |
| `test_scores_are_absolute_not_normalized` | Asserts `'score' in r`. Same key-presence weakness. |
| `test_absent_fts_table_never_breaks_write` | See §2 — proves nothing about writes. |

**Would search work for a real user?** Keyword search: yes, but *by accident* —
through the `LIKE '%term%'` fallback, which does substring matching, not tokenised
matching, has no ranking, and returns `keyword_score=None`. Semantic search:
`sqlite-vec` requires the `node_vec` table, which nothing in phase 5 populates on
the real path (`index_node`'s vec branch needs an `embedder` argument that no caller
passes). So in the shipped app search is a degraded LIKE scan with null scores, and
the passing green tests say nothing about that.

### 1e. `/api/search` bypasses `search.py` and has the v1 broad-`except`

`chronos/api/routes.py:626-680` implements `GET /api/search` with its own inline
SQL and:

```python
except Exception:
    # FTS5 not available — fall back to LIKE
```

This is exactly the pattern phase 5 warns about: *"v1 shipped a version that
silently returned nothing under a Session because a broad `except` swallowed the
argument error. Narrow the catch."* It is wider than v1's — it catches everything,
and its LIKE fallback also masks every FTS bug in 1a-1c behind a working search box.
No phase-5 test covers this route.

---

## 2. FINDING (HIGH): degradation tests pass by swallowing errors

`test_absent_fts_table_never_breaks_write` is the clearest case:

```
$ .venv/bin/python .../p3.py
=== J. test_absent_fts_table_never_breaks_write ===
  no raise -- but _table_exists swallows via MagicMock.fetchone() truthy
  => _table_exists gets a MagicMock (truthy) so the FTS branch IS entered;
     the OperationalError is then swallowed by `except sqlite3.OperationalError: pass`.
```

The test builds a `MagicMock` whose `execute` always raises, calls `index_node`,
and asserts nothing. It **does not perform a core write at all**, so the phase-doc
requirement *"an absent FTS table must never break a write"* is untested. It only
shows that `index_node` doesn't propagate `OperationalError`. Meanwhile a real
`IntegrityError` does propagate (1c) and would break the write. The test and the
contract disagree, and the test is the one that's green.

Other degradation tests with no assertion at all: `test_missing_fts_table_still_works`,
`test_search_with_sqlalchemy_session`, `test_search_with_sqlite3_connection`,
`test_reminder_row_is_real_row` (body is `pass`).

**Good news — the v1 broad-`except` is absent from the audited modules.** Verified by
scan:

```
$ awk '/except Exception/{print FILENAME":"FNR}' chronos/db/search.py chronos/notify/*.py chronos/db/audit.py chronos/ai/*.py
chronos/db/search.py:464:  # Only sqlite3.OperationalError is swallowed — a broad `except Exception` is
```

That is the only hit, and it is a **comment**. Every real catch in `search.py`,
`notify/scheduler.py` and `db/audit.py` is `sqlite3.OperationalError` (or narrow).
`notify/scheduler.py` additionally filters `soft_deleted` and `state != 'cancelled'`
in SQL *and* re-checks in Python. So `search.py` itself is clean on this axis; the
broad `except Exception` survives in `chronos/api/routes.py:657` (§1e), which phase 5
does not own or test.

---

## 3. FINDING (HIGH): the clarification-budget restart test is untestable as written

Spec §5.7 and phase-5 both: *"The budget must persist across a process restart"*, and
the phase doc quotes v1's triage verbatim — *"counter is in memory, not persisted"*
— then demands *"A fresh object built from the same database must see the day as
spent."*

The test does construct a fresh object from "the same database":

```python
mock_db = MagicMock()
budget1 = ClarificationBudget(db=mock_db)
budget1.record_question(date_ms=1700000000000)
budget2 = ClarificationBudget(db=mock_db)
assert budget2.can_ask(date_ms=1700000000000) is False
```

**But `mock_db` is a `MagicMock`.** It stores nothing retrievable. A budget that
keeps its counter on `self`, in a module-level global, or in a plain dict passes this
identically to one that writes to SQLite. The test therefore **cannot fail on the
exact defect the spec quotes.** It is green for an in-memory counter. This is the
single most direct recurrence of a v1 defect that the phase doc singled out by name.

This is currently *masked*: all 3 `TestClarificationBudget` tests fail on
`TypeError: ClarificationBudget.__init__() missing 1 required positional argument:
'clock'`. So the persistence question is **unresolved**, not answered.

**I cannot verify whether the budget actually persists** — `chronos/ai/briefings.py`
is owned by another agent in flight and its `ClarificationBudget` is mid-change.
Stating so rather than guessing. Required to close this: a real on-disk SQLite
connection (or a real repo object), `budget1.record_question(...)`, then a **fresh
`ClarificationBudget` over the same file/connection** asserting
`can_ask(...) is False`. A `MagicMock` cannot express that.

---

## 4. FINDING (HIGH): both cost tests are vacuous — they cannot catch a fake `0.0`

Spec and phase doc are emphatic: *"An unknown price is `None` — never a fake
`0.0`"*, and CSV *"An unknown cost is an empty cell — not `0.0`, not `None`."*

Both stats cost tests are wrapped in a truthiness guard:

```python
spend = stats.get('token_spend', stats.get('daily_spend', []))
if spend:
    assert spend[0][2] is None or spend[0].get('cost_usd') is None
```

Probe:

```
=== O. test_cost_usd_none_for_unknown_price is VACUOUS ===
  no-spend-key: spend=[] -> assertions run=False -> test passes=True
  fake 0.0 row: spend=[[..., 0.0]] -> assertions run=True -> test passes=False
```

If `get_stats` returns a dict with **no** `token_spend`/`daily_spend` key, `spend`
is `[]`, the guard is false, **zero assertions execute, and the test passes** — on
an implementation that fabricates `0.0` everywhere. The spec's headline requirement
is therefore unverified. `test_cost_usd_non_zero_for_known_price` has the same
`if spend:` guard and the same hole, and additionally asserts `spend[0][2] == 0.05`,
which is just the literal the test itself fed into the mock — a passthrough, never a
price-table computation.

Neither test supplies a real price table or drives `StatsCollector._compute_cost`.
Both are currently failing on `ImportError` anyway (§0), so this hole is dormant,
not closed.

**Every test that touches cost:**

| Test | Would it catch a fake `0.0`? | Why |
|---|---|---|
| `test_cost_usd_none_for_unknown_price` | **No** | `if spend:` guard → zero assertions when the key is absent |
| `test_cost_usd_non_zero_for_known_price` | **No** | same guard; value is a passthrough of the mock's own literal |
| `test_export_empty_cell_for_unknown_cost` | **Partially** | asserts `row[-1] == ''`, but never checks that the last column *is* cost. An exporter that omits cost and ends the row with another field passes. No header assertion for `'cost'`. |
| `test_stats_includes_token_spend_by_day` | No | key-presence only |

`chronos/ai/stats.py:227-238` does implement a real `provider_prices` lookup
returning `None` for unknown, and `export.py:165` documents the empty-cell rule — but
**no phase-5 test exercises either**, so the contract is unpinned.

---

## 5. Lower-severity findings

- **`test_default_offsets_single_definition` is a no-op.** Its body is the same
  import-and-compare as `test_default_offsets_value`, with the comment
  *"Single definition is enforced by code review / ruff"*. The phase doc's Done
  means calls this out as a real requirement (*v1 defined it twice and they drifted*).
  Verified by scan: there is currently exactly **one** definition,
  `chronos/contracts/constants.py:4`. So the requirement holds, but **nothing
  enforces it** — a second literal `[10, 0]` in any module would not fail a test.
- **`test_fts5_narrows_candidates` is a stage-ordering test with a broken oracle.**
  Its `side_effect` tags *every* `db.execute` as `'fts5'`, so the assertion
  `call_order[0] == 'fts5'` can only ever pass. It would also pass if FTS were
  deleted and the first execute were the `sqlite_master` probe.
- **`test_duplicate_check_searches_plus_minus_one_day`** asserts
  `'86400000' in query_str or '1 day' in ... or 'julianday' in ...`. That matches a
  SQL *comment* — and `search.py:575` literally carries
  `"-- window: 1 day = 86400000 ms, max 7 days"`. The assertion is satisfied by a
  comment with no bound enforcement behind it.
- **`test_audit_viewer_filterable_by_time_range`** asserts `'at' in str(call_args).lower()`.
  `'at'` is a substring of `created_at`, `updated_at`, `fetchall`, `format`, and
  `timestamp` — it passes on essentially any audit query. Same weakness in
  `test_audit_viewer_filterable_by_action` (`'action'`) and `_by_target`
  (`'target'`, also a substring of nothing else here, so marginally better).
- **`test_audit_viewer_excludes_older_than_seven_days`** is the one SQL-text
  assertion that does bite. Verified real:
  `WHERE at >= ? -- retention: 7 days = 604800000 ms` with cutoff `1699395200000`
  = `1700000000000 - 604800000`. Correct.
- **`test_audit_viewer_is_read_only`** inspects `call[0][0]`, which is the first
  positional arg. It would miss a write issued via `execute(text=...)` or a keyword
  arg. Narrow, but real.
- **`test_hierarchy_*` / `find_or_create_node` / `find_or_create_tag`**: all three
  currently fail on `ImportError`. They live in `chronos/ai/briefings.py`, so §5.4
  reuse (§"Tags are never duplicated") is **entirely unpinned** right now.
- **No test covers `chronos/notify/scheduler.py`'s `cancel()`**, the soft-deleted
  event path, or that a fired reminder is actually **marked SENT**
  (`_MARK_SENT_SQL`). §4.6's "cancellable individually" is only half-pinned; a
  scheduler that publishes every tick forever would pass, since
  `test_scheduler_publishes_due_reminders` uses a `MagicMock` db that returns the
  same due row on every call.
- **No network test exists** (phase doc: *"No test may touch the network"*).
  `test_one_http_post_per_publish` injects a `MagicMock` session. Satisfied.

---

## 6. Severity summary

| Sev | Count | Findings |
|---|---|---|
| CRITICAL | 1 | `keyword_score`/`bm25` is permanently `None` (contentless-rowid **and** `_row_value` index bug); every "degrades to keywords" test passes on the `LIKE` fallback, not FTS (§1) |
| CRITICAL | 1 | `index_node` raises `IntegrityError` on the real schema — indexing on create is broken in production while the tests are green (§1c) |
| HIGH | 2 | degradation tests assert nothing / prove nothing about writes (§2) |
| HIGH | 1 | clarification-budget restart test uses `MagicMock` and cannot fail on an in-memory counter; unresolved, not answered (§3) |
| HIGH | 1 | both `cost_usd` tests are vacuous under `if spend:`; cannot catch a fake `0.0` (§4) |
| HIGH | 1 | `/api/search` in `routes.py` bypasses `search.py` and keeps a bare `except Exception` (§1e) |
| MEDIUM | 6 | weak SQL-substring assertions (`86400000` comment, `'at'`, `'action'`), broken stage-order oracle, no-op single-definition test, unsent-reminder gap (§5) |
| LOW | 1 | 25 failing tests are a wrong-API-shape TEST bug in `chronos/ai/` (§0) |

## 7. Recommendations (reported, not applied)

1. Fix `_FTS_COLUMN_ORDER` to match the real column arity, or index by name only —
   then add a test asserting `keyword_score` is a **float**, not `None`. This is the
   test that would have caught §1b.
2. Resolve the contentless-FTS rowid mapping properly: store the node id as an
   `UNINDEXED` column (`fts5(title, notes, node_id UNINDEXED, content='')`) and
   select that, rather than `rowid`. Then `bm25` is real and the `LIKE` fallback can
   be deleted. Requires a contract change — flag for the owner of `ddl.py`.
3. Catch `sqlite3.DatabaseError` (or `Exception`) in `index_node`/`reindex_node`/
   `remove_node_from_index`, or better, guard on a resolved rowid type, so the
   "never breaks a write" contract holds for every error class.
4. Rewrite `test_absent_fts_table_never_breaks_write` to perform a **real** node
   insert into a real SQLite DB with `node_fts` absent, and assert the write landed.
5. Rewrite `test_clarification_budget_persists_across_restart` against a real
   on-disk SQLite connection with two independent `ClarificationBudget` instances.
6. Drop the `if spend:` guards; assert `spend` is non-empty first, and drive a real
   price table so an unknown price genuinely has to become `None`.
7. In `test_export_empty_cell_for_unknown_cost`, locate the cost column **by header
   name**, not `row[-1]`.
8. Point `GET /api/search` at `chronos.db.search.search_nodes` and delete the inline
   SQL + `except Exception`, or add a test that pins the narrow catch.
