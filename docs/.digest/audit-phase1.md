# Phase 1 Audit — tests/phase_1/test_contracts_spec.py

READ-ONLY audit. No files modified. Auditor: phase-1 audit subagent.

## Baseline state (verified)

```
$ .venv/bin/python -m pytest tests/phase_1 -q
215 passed in 1.85s

$ .venv/bin/ruff check chronos/contracts tests/phase_1
Found 20 errors.
```
The phase-1 plan's Verification block (`docs/server/phases/phase-1-core.md` §Verification)
requires `.venv/bin/ruff check chronos tests` to be clean. It is not. 20 errors, including
2 unused imports (`enum.Enum`, `typing.get_type_hints`) and 13 E501 line-too-long.

**This is the same failure class as the v1 build: 215 green tests, one file, zero of them
touch the database.** Confirmed by direct inspection:

```
$ find tests -name '*.py'
tests/phase_1/test_contracts_spec.py     <- the ONLY phase-1 test file (1806 lines)
tests/phase_2..6/...                     <- each a single *_spec.py, same shape

$ grep -nE 'chronos\.(db|core)|sqlite|aiosqlite|sqlalchemy|create_engine' tests/phase_1/*.py
(no output — 0 hits)
```

`chronos/db/` (engine, seed, repos, audit, search) and `chronos/core/scheduling.py` (524 lines)
are shipped, importable, and **completely unexercised by phase 1's tests**. The whole phase-1
"data layer" box is unverified.

---

## Findings by severity

### BLOCKER

---

#### B1. `tests/phase_1` never executes the database. v1's exact defect, unfixed.

Evidence above: zero `sqlite3` / `chronos.db` / `chronos.core` imports in the only phase-1 test file.

Concretely, six of the phase doc's nine "Done means" boxes are **behavioural** claims about
code that exists and is never called. I ran the real seed by hand to see what the tests
are declining to check:

```
$ python -c "... sqlite3.connect(':memory:') ; seed_buckets(conn) ..."
seeded: 4307
by level: [('D', 3652), ('M', 121), ('W', 523), ('Y', 11)]
DAY buckets whose parent is NOT a week: 0
orphan buckets: 0
second seed returned: 0   total rows now: 4307   (idempotent OK)
```

So the implementation happens to be correct today. **No test would notice if it stopped being
correct.** Specifically these are all untested:

- The 10-year seed produces ~4300 rows with the Y/M/W/D distribution. Untested.
- Every day bucket's parent is a WEEK (the exact v1 regression the phase doc calls out at
  line 50: *"v1 shipped with every day parented to a month. Do not repeat it."*). **Untested.**
  This is the single highest-value regression in the phase and it has zero coverage.
- Chain walks cleanly to a year with no orphans. Untested.
- Seed idempotency. Untested (test_bucket_seed_spec_idempotent only greps the word
  "idempotent" out of a dict's repr — see M4).
- Repo round-trip of every entity. Untested.
- Cascade deletes. Untested.

Note the DDL also fails to apply on a stock sqlite3: `CREATE VIRTUAL TABLE node_vec USING
vec0(...)` → `sqlite3.OperationalError: no such module: vec0`. No test catches this either,
so the "fresh database" story has an untested failure mode.

---

#### B2. Three permanently-true assertions on the review tier offsets (§4.4 / A.6).

Lines 1656-1672, class `TestReviewTierDefaults`. All three end in `or True`:

```python
1657: def test_hard_tier_offsets(self):
1662:     assert "1, 2, 4, 8, 16" in spec_str or "1,2,4,8,16" in spec_str.replace(" ", "") or True  # Placeholder
1667:     assert "3, 7, 15, 30" in spec_str or "3,7,15,30" in spec_str.replace(" ", "") or True  # Placeholder
1672:     assert "10, 30, 90" in spec_str or "10,30,90" in spec_str.replace(" ", "") or True  # Placeholder
```

Worse than inert: they search `str(BUCKET_SEED_SPEC) + str(DDL_STATEMENTS)` — the *wrong
objects entirely*. The real constants live in `chronos/core/scheduling.py`:

```python
TIER_OFFSETS: dict[ReviewTier, list[int]] = {
    ReviewTier.HARD:   [1, 2, 4, 8, 16],
    ReviewTier.MEDIUM: [3, 7, 15, 30],
    ReviewTier.EASY:   [10, 30, 90],
}
```
Verified live. These tests pass because `or True`, not because the offsets are right.
They should import `TIER_OFFSETS` and assert equality.

---

#### B3. One-timer-at-a-time is NOT enforced anywhere, and the tests do not notice.

Phase doc line 82 and "Done means": *"One timer runs at a time, across all three modes."*
Spec §4.7: *"One timer runs at a time."*

`SqliteTimerSessionRepo.create` (`chronos/db/repos.py:1267`) is a bare INSERT — no guard on
an existing running session, and no partial unique index in the DDL. Demonstrated live:

```
$ python -c "... create TimerSession t1; create TimerSession t2 ..."
B) RUNNING (ended_at IS NULL) TIMERS SIMULTANEOUSLY: 2
```

Two timers run at once. No test covers one-timer-at-a-time at any layer (no repo test, no
core test, no schema test). This is a **live implementation defect that shipped green.**

---

#### B4. Stopwatch-ignores-target is not tested, and is testable-but-absent.

Phase doc line 83 / "Done means". Spec §4.7 DDL comment: `target_ms INTEGER, -- NULL for a
stopwatch, which has no target`. `TestDDL::test_ddl_timer_sessions_columns` (line 1436) does
assert `TARGET_MS` is present as a substring — but only that the column *exists*, which is
the opposite of the requirement. There is no test that a stopwatch session cannot carry a
target, and no test of the countdown/count-up behaviour. `chronos/core/scheduling.py`
contains no `stopwatch`/`target` handling at all (grep: 0 hits), so if the rule lives
anywhere it is not there.

---

### MAJOR

---

#### M1. The "import graph is a DAG with no cycles" box is not tested. `TestImportGraph` greps source text.

Phase doc line 39 and "Done means" box 1: *"The import graph must be a DAG with no cycles."*
`TestImportGraph` (lines 1585-1646) never builds a graph. It does `inspect.getsource(mod)`
and asserts substrings like `"from chronos.contracts.models" not in source`.

Three ways this is defeated, all verified:

1. **Any real cycle can be injected and the suite stays green.** I added a genuine cycle
   into `chronos.contracts.enums` — a relative import, an aliased absolute import, and a
   function-level import:
   ```
   $ python -c "...inject cycle into enums, then run TestImportGraph..."
   6 passed in 0.12s
   ```
   A true cycle, undetected. `test_enums_module_has_no_contracts_imports` only matches the
   exact literal `from chronos.contracts.models`; `from .models import Node` slips through.
2. `import chronos.contracts.models as m` / `from ..contracts import x` slips through.
3. A cycle *between* modules the test never inspects (e.g. `ddl` ↔ `constants`, or anything
   outside `chronos.contracts`) is invisible.

The real check is: parse each module with `ast`, build the intra-package edge set, and assert
topological ordering exists (or that `import` in a fresh interpreter terminates for every
permutation). None of that is present.

---

#### M2. Every `TestDDL` column check is a whole-file substring search, not table-scoped.

`test_ddl_buckets_columns` (1313), `test_ddl_nodes_columns` (1181), `test_ddl_events_columns`
(1269), `test_ddl_schedules_columns` (1366), `test_ddl_review_series_columns` (1350),
`test_ddl_audit_columns` (1484), `test_ddl_timer_sessions_columns` (1436) all do:

```python
ddl_text = "\n".join(DDL_STATEMENTS).upper()
for col in [...]:
    assert col in ddl_text
```

The haystack is every statement concatenated. A column named in *any* table satisfies any
table's check. Demonstrated: I replaced the schema with one where `buckets` has **no `seq`,
no `start_ms`, no `end_ms`, no `level`** — only `id`, `parent_id`, `bucket_level` — and
`test_ddl_buckets_columns` still passed, because those names exist in `nodes`.

```
$ python -c "... substitute gutted DDL, run selected column tests ..."
1 failed, 4 passed
FAILED ...test_ddl_timer_sessions_columns   (only because TARGET_MS was absent everywhere)
```

So `test_ddl_buckets_columns` passed against a `buckets` table with **zero** of the six
columns it claims to check. Same for `nodes_columns`, `schedules_columns`, `events_columns`.
Note some tests *do* scope correctly with a regex (`test_ddl_nodes_parent_fk`,
`test_ddl_review_series_check_constraint`) — the pattern exists in the file and was simply not
applied to the column loops. Fix is mechanical: reuse the `re.search(r"CREATE TABLE X\s*\(...")`
already used two lines below in the same class.

Secondary: the `CREATE TABLE NODES\s*\((.*?)\)` regex at lines 1191/1199/1208 is non-greedy
and stops at the **first `)`** — the `)` of the first `ON DELETE CASCADE` FK. Any column or
constraint after the first FK is invisible to those tests. The file's own comment at lines
1337-1339 acknowledges this bug for `review_series` and fixes it there with a `\n\);` anchor.
The same bug is still live in `nodes`, `tags`, `node_tags`, `events`, `schedules`.

---

#### M3. `test_bucket_seed_spec_has_expected_counts` passes on pure junk.

```python
1545: has_counts = any(keyword in spec_str for keyword in ["YEAR","MONTH","WEEK","DAY","4300","4303"])
1549: assert has_counts
```

I replaced `BUCKET_SEED_SPEC` with `{"junk":"junk"}`:
```
$ python -c "... TestBucketSeedSpec + TestReviewTierDefaults with junk spec ..."
5 failed, 5 passed
FAILED ...test_bucket_seed_spec_has_years
FAILED ...test_bucket_seed_spec_nesting
FAILED ...test_bucket_seed_spec_id_formats
FAILED ...test_bucket_seed_spec_idempotent
FAILED ...test_bucket_seed_spec_auto_extension
```
`test_bucket_seed_spec_has_expected_counts` is among the **5 that passed on junk**. (`"junk"`
contains no listed keyword — but `"no years no counts"` does, via the substring `YEAR` inside
`YEARS`.) The test only proves the English words appear *somewhere in a repr*. It pins no
count: `4303` is never required, only one of six tokens.

These are `str(BUCKET_SEED_SPEC)` grep assertions on a **dict repr** — the most brittle and
least meaningful assertion style in the file, and the type is `dict`, so the repr is an
implementation detail that any refactor breaks while proving nothing.

---

#### M4. `test_bucket_seed_spec_*` — six tests that grep a dict's repr instead of asserting values.

All of `TestBucketSeedSpec` (1526-1578) inspect `str(BUCKET_SEED_SPEC)`, which I verified is:

```python
{'years': 10, 'expected_counts': {'year':10,'month':120,'week':522,'day':3653,'total':4303},
 'id_formats': {'year':'Y:2026','month':'M:2026-08','week':'W:2026-W31','day':'D:2026-08-04'},
 'nesting': 'Y → M → W → D', 'idempotent': True, 'auto_extension_threshold_days': 180}
```

So the dict *does* carry the right numbers — and the tests throw them away in favour of
substring hunting:

- `test_bucket_seed_spec_has_years` (1537): `assert "10" in spec_str or hasattr(..., "years")`.
  The literal `"10"` matches `120`, `3653`, `4303`, `10`… in any repr. `hasattr` on a dict is
  `False`, so it is effectively a `"10"` substring test. It cannot fail on this object.
- `test_bucket_seed_spec_nesting` (1551): `assert "Y" in spec_str; assert "M" in ...; assert "W" in ...; assert "D" in ...`
  Single letters. Every repr containing "MIXED"/"DEFAULT"/"ID" passes. This is the *nesting
  rule* — the top-priority v1 regression — reduced to "the alphabet is present".
- `test_bucket_seed_spec_id_formats` (1560): `any(fmt in spec_str for fmt in ["Y:","M:","W:","D:"])`.
  `any`, not `all`. Asserting *one* of four ID formats satisfies a test about four.
- `test_bucket_seed_spec_auto_extension` (1578): `assert "180" in spec_str`. Substring on repr.

Correct form is `assert BUCKET_SEED_SPEC["years"] == 10`, `assert BUCKET_SEED_SPEC["nesting"] == "Y → M → W → D"`,
`assert set(BUCKET_SEED_SPEC["id_formats"]) == {...}`. The data is right there and unused.

---

#### M5. "Bounded-series enforced at BOTH repo and schema" — only the schema is tested; the repo has no check.

Phase doc "Done means" box 5. Only the schema half exists:
`test_ddl_review_series_check_constraint` (1334) correctly asserts the literal
`CHECK (MAX_COUNT IS NOT NULL OR ENDS_ON_MS IS NOT NULL)` — genuinely good, and the only
well-scoped DDL assertion in the class.

There is **no test at the repo layer**. And the repo genuinely has no such check —
`SqliteReviewSeriesRepo.create` (`chronos/db/repos.py:766`) goes straight to `INSERT`. It is
refused today only because SQLite re-raises the DDL CHECK:

```
A) refused at repo: IntegrityError CHECK constraint failed: max_count IS NOT NULL OR ends_on_ms IS NOT NULL
```

So "at both repo and schema" is one rule implemented in one place, counted twice. A caller
using the repo against a non-CHECK-constrained path, or an error message that doesn't say
"review series must be bounded", ships silently.

---

#### M6. Repo round-trip + cascade: zero coverage, and the FK enforcement is unverified.

Phase doc "Done means" box 4. There is no repo test file at all. I could not complete a
cascade probe against the shipped schema — `node_tags` composite PK and `ON DELETE CASCADE`
are textually asserted (1252-1260) but I got `UNIQUE constraint failed: node_tags.node_id,
node_tags.tag_id` on a plain insert, and the whole DDL set fails to apply on stock sqlite3
because of the missing `vec0` module. Nothing in the suite establishes that deleting a node
removes its children, its node_tags rows, and its timer_sessions. `TestProtocols` only checks
that `NodeRepo` has methods named `create`/`delete` — it never calls them.

### MINOR

---

#### m1. 20 ruff errors; the phase's own Verification block is red.
2 × F401 unused imports (`enum.Enum` line 18, `typing.get_type_hints` line 19), I001 unsorted
imports, RUF012 mutable class default (508), RUF003 en-dash in a comment (544), 13 × E501
including a **161-character** line at 729. The plan requires `.venv/bin/ruff check chronos tests`
clean.

#### m2. 20 existence-only assertions — `assert X is not None`.
Lines 856, 860, 882, 907, 919, 931, 956, 978, 1000, 1015, 1030, 1052, 1071, 1083, 1094, 1112,
1131, 1159, 1531. These are import-time tautologies: the module-level `from chronos.contracts
import ...` at line 29 has already raised `ImportError` if the name is missing. They can never
fail independently. `test_ddl_statements_exists`, `test_bucket_seed_spec_exists` and the twelve
`test_*_repo_exists` are all in this class.

#### m3. The whole file is guarded by `pytest.importorskip`.
Line 27: `contracts = pytest.importorskip("chronos.contracts", reason="chronos/contracts/ not yet implemented")`.
Once the package exists this is inert — but it means that **if `chronos.contracts` ever fails to
import, the entire phase-1 suite silently skips and reports green.** There is no
`collect_error`, and the module docstring (lines 8-10) still says the tests "fail now because
chronos/contracts/ does not exist yet", which is stale. A future regression that breaks the
contracts import turns 215 tests into a vacuous pass. This is the "tests that cannot fail"
hazard at suite scale.

#### m4. Unused-import signals dead intent, not just lint.
`enum.Enum` and `typing.get_type_hints` are imported and never used (lines 18-19). A
`get_type_hints`-based check that the dataclass field *annotations* match the spec (§4.1-§4.7
column types) was clearly intended and never written. Type conformance is entirely untested —
the DDL is INTEGER, the models are unvalidated dataclasses, and nothing connects them.

#### m5. No test relates the model defaults to the DDL defaults.
`TestModelConstruction` asserts dataclass defaults in Python (e.g. `event.kind == EventKind.FOCUS`,
`reminder.channel == "ntfy"`, `schedule.hard_block is True`) while `TestDDL` asserts
`DEFAULT 'focus'`, `DEFAULT 'ntfy'`, `DEFAULT 1` as substrings. These two are the same fact
stated twice, in two representations, with **no test tying them together**. They can drift
silently. A single test executing the real DDL and reading `PRAGMA table_info` would pin both
and would simultaneously fix B1.

#### m6. `core/` purity is asserted nowhere.
Phase doc "Done means" box 7 / Verification: *"`chronos/core/` is pure — its tests run in
milliseconds with no database."* There are no `core/` tests at all, so the box is vacuously
"met" — and unenforced. No test asserts that `chronos/core/` avoids `sqlite3`, `sqlalchemy`,
`fastapi`, `pydantic`, or any framework import. `scheduling.py`'s own docstring claims "no DB,
no framework imports"; nothing checks it. (Its current imports are clean — verified — but
nothing would catch it becoming otherwise.)

#### m7. §7.1 timezone round-trip is entirely untested.
Phase doc "Timezone" behaviour block: local wall time → UTC on every write and render,
round-trips preserve the instant. `chronos/core/time_utils.py` exists. Zero phase-1 tests
import it. Grep confirms no `zoneinfo`, `tz`, or `local_ms` anywhere in the test file.

---

## "Done means" checklist — box by box

| # | Box | Enforcing test? |
|---|-----|----------------|
| 1 | contracts import graph is a DAG with no cycles | **NO** — M1. Source-text grep; a real injected cycle passes (6/6 green). |
| 2 | fresh DB seeds 10 years of nested Y→M→W→D, counts as above | **NO** — B1/M3/M4. Zero DB execution; counts grepped from a dict repr, `any()`-of-one keyword. |
| 3 | every day bucket's parent resolves to a week; chain walks to a year | **NO** — B1. **The v1 regression the plan explicitly warns about has no test.** No `TestBucketSeedSpec` test checks parentage at all. |
| 4 | repo round-trips every entity, with cascades | **NO** — M6. No repo test file exists. |
| 5 | bounded-series enforced at both repo AND schema | **PARTIAL** — M5. Schema: yes (`test_ddl_review_series_check_constraint`, good). Repo: no test, and no repo check exists. |
| 6 | one-timer-at-a-time AND stopwatch-ignores-target enforced | **NO** — B3/B4. Neither enforced; two timers demonstrably run at once. |
| 7 | `core/` is pure — millisecond tests, no database | **NO** — m6. No `core/` tests; purity unasserted. |
| 8 | full suite green | **PARTIAL** — phase 1 is green (215) but ruff is red (20 errors, m1). |
| 9 | per-part scratch tests deleted; spec tests kept | **YES** — `tests/phase_1/` holds exactly one file, no scratch scripts. |

**2 of 9 boxes enforced. 5 not enforced at all. 2 partial.**

Against the plan's "Behaviour the tests must pin", 15 of 24 bullets have no test:
bucket seed (all 5), overlap query (1), `soft_deleted` not a conflict (1), push-back + both
slots (2), 1-minute grid (1), negative duration rejected (1), series writes all events in one
transaction (1), no geometric rewind (1), paused/non-hard_block do not block (2), pomodoro
break excluded from totals (1), early-stopped focus ≠ completed cycle (1), per-node own/descendant/
project totals with `parent_id` walk (1), timezone round-trip (1).

---

## Most important finding

**`tests/phase_1` never executes the database — the v1 defect, verbatim, unfixed — and one of
the plan's two named anti-regressions (day buckets parented to weeks) has zero coverage while
the other (bounded series) is enforced in only one of the two required layers.**

215 green tests assert that enums have members, dataclasses have field names, and a list of SQL
strings contains certain words. Every one of them passes with the entire data layer deleted.
I removed `BUCKET_SEED_SPEC`'s content and 5 of 10 tests still passed; I gave `buckets` a table
with none of its six claimed columns and `test_ddl_buckets_columns` stayed green; I injected a
genuine import cycle into `enums.py` and all 6 `TestImportGraph` tests stayed green.

The trap is that the implementation is *currently correct* — I ran the seed and days do resolve
to weeks (0 misparented of 3652) and it is idempotent. So this will not announce itself. The
tests would catch exactly one real regression out of the phase, and only by luck.

### Minimum fixes, highest value first

1. Add `tests/phase_1/test_seed_db.py`: apply `DDL_STATEMENTS` to `:memory:`, call
   `seed_buckets`, assert level counts, assert **every** day bucket's parent is a WEEK, assert no
   orphans, assert idempotency. This one file closes boxes 2 and 3 — the v1 regression.
2. Delete the three `or True` assertions (B2); import `TIER_OFFSETS` from
   `chronos.core.scheduling` and assert equality.
3. Delete `TestImportGraph`'s five source-grep tests; replace with an `ast`-based intra-package
   edge graph and a topological-order assertion (M1).
4. Scope every `TestDDL` column loop to its own table via the `re.search(r"CREATE TABLE X\s*\(...")`
   already present in the same class, and fix the `.*?\)` truncation to the `\n\);` anchor
   (M2).
5. Add repo round-trip + cascade tests, and add the missing one-timer-at-a-time guard —
   which today is an **actual shipped bug** (B3): two `ended_at IS NULL` sessions coexist.
6. Replace `pytest.importorskip` with a hard import so a contracts import failure is a red
   suite, not a green skip (m3).
7. Fix the 20 ruff errors so the phase's own Verification block passes (m1).
