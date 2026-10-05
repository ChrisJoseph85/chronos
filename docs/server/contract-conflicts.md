# Contract conflicts — frozen proposals

**Status:** OPEN — awaiting user rulings
**Date:** 2026-10-04
**Scope:** contradictions *between* the six FROZEN interface proposals and the
already-built tree. Nothing here is implemented. This is a decision record.
**Format:** each entry names the docs, the exact sections, the two verbatim
statements, why it breaks at runtime, and a recommended resolution with
reasoning.

**Severity scale**

| Severity | Meaning |
|---|---|
| BLOCKER | Prevents boot, or risks data loss |
| MAJOR | Wrong behaviour at runtime |
| MINOR | Inconsistency only |

**Verification status.** Every entry was checked against the proposal text.
Entries marked `UNVERIFIED-SIDE` cite a second document that was not re-read in
this pass (phase-3, phase-4, or `docker.md`); the proposal-side quote is exact,
the counterpart quote is carried over from the build log and should be
re-confirmed before ruling.

---

## 1. `token_cost` vs `token_costs` — two cost tables

**Severity: BLOCKER**

**Disagreeing docs:** `phase-2-ai.md` §G.7 vs `phase-5-features.md` §E.2.1

**Statement A — `phase-2-ai.md` §G.7 "Token-cost table schema":**

> `CREATE TABLE token_cost (` … `prompt_tokens   INTEGER NOT NULL,`
> `completion_tokens INTEGER NOT NULL,` `total_tokens    INTEGER NOT NULL,`
> `cost_usd        REAL,                       -- NULL if price unknown`
> `success         INTEGER NOT NULL,           -- 1 = success, 0 = failure`
> `error_type      TEXT                        -- "429", "5xx", "timeout", etc.`

> `CREATE INDEX ix_token_cost_day ON token_cost(at);`
> `CREATE INDEX ix_token_cost_provider ON token_cost(provider);`

**Statement B — `phase-5-features.md` §E.2.1 "`token_costs` (§5.2, §8.2)":**

> `CREATE TABLE token_costs (` … `tokens_in   INTEGER NOT NULL,       -- input tokens`
> `tokens_out  INTEGER NOT NULL,       -- output tokens`
> `cost_usd    REAL,                   -- NULL if price unknown (phase doc — never 0.0)`
> `attempt     INTEGER NOT NULL DEFAULT 1,  -- attempt number`
> `success     INTEGER NOT NULL DEFAULT 1,  -- 1 = success, 0 = failure`
> `created_at  INTEGER NOT NULL        -- epoch ms` `);`

Note both are singular/plural of the same name with different column sets.
`phase-2-ai.md` has `total_tokens` + `error_type` and no `attempt`/`created_at`;
`phase-5-features.md` has `tokens_in`/`tokens_out` + `attempt` + `created_at`
and no `total_tokens`/`error_type`.

This is not only a schema clash. `decisions.md` (Phase 2 ambiguity 8) ruled
"SQLite `token_cost` table in main DB. *Ruling: approved.*" and (Phase 5
ambiguity 6) ruled "`token_costs` table — Records every attempt; stats
aggregates by day. *Ruling: approved.*" **The Manager approved both, on the same
date, in the same freeze.** Neither ruling acknowledges the other. The frozen
contracts (§F) do not list either table — `phase-1-contracts.md` §H says
"13 DDL tables + 2 virtual tables" and no cost table is among the 13.

**Why it breaks:** cost writes go to one table and reads to the other, so
`chronos token-cost` (§G.7), `GET /api/stats` (§G.7 note, §E.5) and
`export_cost` (§G.2) silently return zero rows. `error_type` is dropped, so the
failures column of the stats payload cannot be derived — a failed attempt with
no tokens is indistinguishable from a successful empty one.

**Recommendation: keep ONE table — `token_costs` (§E.2.1) — and amend §G.7.**
Reasoning: `phase-5` is the later freeze and its model (`TokenCost`, §E.3) plus
its CSV column list (§G.2 `export_cost`) plus its stats payload (§E.5
`tokens_in`/`tokens_out`/`attempts`/`failures`) are all internally consistent
with `tokens_in`/`tokens_out`/`attempt`. `phase-2`'s `token_cost` is referenced
by exactly one consumer (`CostTracker.record`, §G.2). Amending the smaller
surface is cheaper than rewriting §E.3/§E.5/§G.2. Concretely:
`token_costs` gains `total_tokens INTEGER` (derivable as
`tokens_in + tokens_out`, so a generated column or a repo-level default is
fine) and `error_type TEXT` to preserve §G.7's failure diagnosis; `phase-2-ai.md`
§G.7 is rewritten to `CREATE TABLE token_costs`, and §G.2 `CostTracker.record`
gains an `attempt` and `error_type` argument. Both rulings in `decisions.md`
stand — §G.7's *decision* ("a SQLite cost table in the main DB") survives; only
its name and columns change.

---

## 2. `node_fts` is contentless but must return `Node` objects

**Severity: BLOCKER**

**Disagreeing docs:** `phase-1-contracts.md` §F.12 vs §D.6, and
`phase-5-features.md` §B.3

**Statement A — `phase-1-contracts.md` §F.12 "`node_fts` (§4.8)":**

> `CREATE VIRTUAL TABLE node_fts USING fts5(title, notes, content='');`

**Statement B — `phase-1-contracts.md` §D.6 `SearchBackend`:**

> `def search_keyword(self, query: str, limit: int = 10) -> list[Node]: ...`

**Statement C — `phase-5-features.md` §B.3 `NodeSearch.remove_node` /
`reindex_node`:**

> `def remove_node(self, node_id: str) -> None:` … "Best-effort: if the FTS5
> table is absent, this is a no-op (phase doc). Removes from node_fts and
> node_vec. Never raises on a missing table."

> `def reindex_node(self, node: Node) -> None:` … "Removes the old entry and
> re-inserts with the new title/notes/embedding."

`content=''` declares a **contentless** FTS5 table. Such a table stores only
the inverted index and the rowid; the original text is not retained and cannot
be recovered by `SELECT`. `fts5(title, notes)` with no `content=` clause stores
the text. `node_fts` has no `node_id` column and no contentless-delete trigger,
so there is no second copy of the text anywhere in the schema.

**Why it breaks:** `search_keyword` is contracted to return full `Node`
objects. From a contentless table the only thing obtainable is a rowid. The
implementer must therefore join back to `nodes` — but `nodes.id` is a uuid4
`TEXT` primary key (`phase-1-contracts.md` §F.1), and there is no column in
`node_fts` that holds it. Without a uuid→rowid mapping column, the join is
impossible and `search_keyword` can only return empty/stub nodes. `remove_node`
has the mirror problem: with no stored uuid it cannot address the row to delete
except by re-running the FTS query on the text it no longer has.
(`UNVERIFIED-SIDE`: `contract-and-interfaces.md` §6 reportedly specifies that the
FTS rowid is an INTEGER derived from SHA-256 of the uuid, truncated to 62 bits
— that mapping makes a join *possible*, but it still does not make the node text
*recoverable* from the index, and it still gives `remove_node` no uuid to look
up. Re-confirm §6 before ruling.)

**Recommendation: keep `content=''` (external-content style) but make the
rowid the join key, i.e. option (b) — and only if the §6 SHA-256 rowid scheme is
confirmed.** `nodes` gains an `INTEGER` `fts_rowid` column
`UNIQUE REFERENCES node_fts(rowid)`-style (populated at write time as
`sha256(uuid) & (2**62 - 1)`), and `search_keyword` becomes
`SELECT n.* FROM node_fts f JOIN nodes n ON n.fts_rowid = f.rowid WHERE f
MATCH ? ORDER BY bm25(f) LIMIT ?`; `remove_node` resolves
`sha256(node_id) & (2**62-1)` and issues `INSERT INTO node_fts(node_fts,
rowid, title, notes) VALUES('delete', <rowid>, …)` with the original text
supplied by the caller — contentless deletes require the original values as
arguments, which §B.3 already does implicitly (`remove_node(node_id)` does not
supply them; this is a second, smaller defect in the same place).

**The simpler, more robust alternative is option (a): drop `content=''` and use
`fts5(title, notes)`** — a regular FTS5 table. It duplicates `title`/`notes`
from `nodes`, but then `search_keyword` needs no join at all, `remove_node` is a
plain `DELETE`, `reindex_node` needs no old text, and the uuid problem
disappears entirely. Cost is duplicated text per node (bounded, small) and one
consistency obligation (index on write, which §B.6 already mandates and
`decisions.md` already rules best-effort).

**Which is correct:** if the §6 SHA-256 rowid scheme is real and load-bearing
elsewhere, keep `content=''` and adopt (b). If nothing else depends on it,
**option (a) is correct** — it is the only one of the two that satisfies
§D.6, §B.3 and §B.6 with no extra machinery, and it removes rather than adds a
failure mode. Recommend (a) unless a confirmed reader of §6 requires (b).

---

## 3. Console script entry point names a file that does not exist

**Severity: MAJOR**

**Disagreeing docs:** `phase-6-deploy.md` §D.4 vs `phase-4-interfaces.md` §B.11

**Statement A — `phase-6-deploy.md` §D.4 "entry points":**

> `[project.scripts]`
> `chronos = "chronos.cli.main:main"`

and §D.5 repeats the path:

> `# chronos/cli/main.py`

**Statement B — `phase-4-interfaces.md` §B.11:**

> the CLI layout is `cli/__init__.py` + `cli/__main__.py` + `cli/commands.py`
> — no `main.py`.
> (`UNVERIFIED-SIDE` — phase-4 not re-read in this pass.)

**Why it breaks:** `pip install -e .` succeeds either way, but the console
script wrapper imports `chronos.cli.main` at first invocation. If phase 4's
layout is what was built, every `chronos …` invocation — `serve`, `db-upgrade`,
`export`, and therefore `scripts/smoke.sh`, the Docker `ENTRYPOINT ["chronos"]`
(§A.5), `docker-compose.yml` (§B.5 step 4) and both CI workflows (§E.2, §E.3)
— dies at import with `ModuleNotFoundError`. Nothing else in the system starts
if `chronos serve` does not.

**Recommendation:** decide the module layout first, then make the entry point a
one-line re-export so the two docs stop disagreeing. Keep
`chronos/cli/main.py` as a **shim** containing only
`from .commands import main  # noqa: F401` plus `if __name__ == "__main__":
main()`, and have `chronos/cli/__main__.py` do the same. Both names then resolve,
`chronos` works, `python -m chronos.cli` works, and phase 4's three-file layout
is preserved. A shim costs one file and removes the conflict entirely, which is
cheaper than editing either frozen proposal.

---

## 4. `node_links` has no DDL anywhere in the frozen set

**Severity: MAJOR**

**Disagreeing docs:** `Chronos.md` §4.1 + `phase-1-contracts.md` §C.4 vs
`phase-1-contracts.md` §F

**Statement A — `phase-1-contracts.md` §C.4 `link_nodes`:**

> | `source_id` | `string` | yes | Source node |
> | `target_id` | `string` | yes | Target node |
> **Returns:** `{ "link_id": string }`

**Statement B — `phase-1-contracts.md` §A.1 `Node` notes:**

> "A task may be linked to others with no structural meaning via `node_links`
> (§4.1). **This is a separate table not in the DDL**; the model does not carry
> links."

**Statement C — `phase-1-contracts.md` §H summary:**

> "**13 DDL tables** + 2 virtual tables"

§F defines exactly 13 tables (F.1 `nodes`, F.2 `tags`, F.3 `node_tags`, F.4
`events`, F.5 `buckets`, F.6 `review_series`, F.7 `schedules`, F.8 `reminders`,
F.9 `timer_sessions`, F.10 `settings`, F.11 `audit`, F.12 `node_fts`,
F.13 `node_vec`). `node_links` is not among them. §A.1 says so explicitly.
`decisions.md` Phase 0 ruling 1 says:

> "**Ruling: add the table.** `(source_id, target_id, PRIMARY KEY
> (source_id, target_id))` with FKs to `nodes(id)` ON DELETE CASCADE. The
> `link_nodes` tool (§5.5) requires it."

**A ruling of "add the table" that no frozen proposal contains the DDL for.**
The ruling also leaves `link_id` (§C.4's return field) undefined: with
`PRIMARY KEY (source_id, target_id)` there is no single `link_id` column to
return, and the ruling is silent about whether the pair *is* the link id.
(`UNVERIFIED-SIDE`: `Chronos.md` §4.1 itself was not re-read.)

**Why it breaks:** the `link_nodes` tool has no table to write to. Two
implementations diverge — one raises `sqlite3.OperationalError: no such table`,
one invents the DDL locally. `decisions.md` also warns: "Two agents
independently flagging a major fault means the proposal is wrong."

**Recommendation: add the DDL to the frozen contracts as an announced,
numbered amendment to §F** (not a silent local invention), exactly as
`phase-5-features.md` §H.10 does for its ten additions. Write it as:

```sql
CREATE TABLE node_links (
    source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, target_id)
);
```

and resolve `link_id` explicitly: **return `f"{source_id}:{target_id}"`** (a
derived, stable string), rather than adding a surrogate key column — the ruling
specified a composite PK precisely so links are not first-class entities. Also
decide directionality now: the ruling has no `CHECK (source_id <> target_id)`;
add one, or state that self-links are legal. `phase-1-contracts.md` §H's "13
DDL tables" count becomes 14.

---

## 5. `SettingsRepo` is imported from contracts but is not a frozen protocol

**Severity: MAJOR**

**Disagreeing docs:** `phase-3-server.md` §A.6 vs `phase-1-contracts.md` §D.1

**Statement A — `phase-3-server.md` §A.6:**

> imports `SettingsRepo` from `chronos.contracts`
> (`UNVERIFIED-SIDE` — phase-3 not re-read in this pass.)

**Statement B — `phase-1-contracts.md` §D.1 "`Repo` protocols" + §E.1 exports:**

> §D.1 enumerates `NodeRepo`, `TagRepo`, `NodeTagRepo`, `EventRepo`,
> `BucketRepo`, `ReviewSeriesRepo`, `ScheduleRepo`, `ReminderRepo`,
> `TimerSessionRepo`, `AuditRepo` — ten protocols.

> §E.1 "Exports — From `protocols`: `NodeRepo`, `TagRepo`, `NodeTagRepo`,
> `EventRepo`, `BucketRepo`, `ReviewSeriesRepo`, `ScheduleRepo`,
> `ReminderRepo`, `TimerSessionRepo`, `AuditRepo`, `Clock`, `IdGen`,
> `Embedder`, `Notifier`, `SearchBackend`"

`SettingsRepo` appears in neither list, and §H's count agrees: "**16 protocols**
(10 repo + 6 infrastructure)". The `settings` **table** does exist (§F.10) and
is used by `phase-5-features.md` §D.4 `ClarificationBudget`, but with a raw
`DbConnection`, not a repo: `def __init__(self, db: DbConnection, clock: Clock)`.

**Why it breaks:** `from chronos.contracts import SettingsRepo` raises
`ImportError` at startup, and it does so in phase 3, which owns `create_app` —
so the server does not boot. The same hole lets two access paths exist for the
same table (a `SettingsRepo` in the server, a raw-connection reader in
`ClarificationBudget`), which is how merge-vs-replace drift enters
`PUT /api/settings`.

**Recommendation: add `SettingsRepo` to the frozen contracts as the 11th repo
protocol**, in the same §F/§E.1 amendment style as conflict 4, with the minimal
surface the two consumers need:

```python
class SettingsRepo(Protocol):
    def get(self, key: str) -> Optional[str]: ...
    def get_all(self) -> dict[str, str]: ...
    def set(self, key: str, value: str) -> None: ...
    def merge(self, values: dict[str, str]) -> None: ...   # PUT /api/settings semantics
    def delete(self, key: str) -> bool: ...
```

`merge` is not optional scope-creep: `decisions.md` Phase 3 ruling 5 already
ruled "Merge semantics, not replace", and a `get_all`/`set` pair cannot express
that safely. Then change `ClarificationBudget` (§D.4) to take a `SettingsRepo`
rather than a `DbConnection`, so one persistence path serves both.

---

## 6. `mount_hud` signature

**Severity: MINOR**

**Disagreeing docs:** `phase-4-interfaces.md` §B.4 vs §F.1 (both within
phase 4)

**Statement A — `phase-4-interfaces.md` §B.4:**

> calls `mount_hud(app)`

**Statement B — `phase-4-interfaces.md` §F.1:**

> declares `mount_hud(app, db_path)`

(`UNVERIFIED-SIDE` — phase-4 not re-read in this pass.)

**Why it matters:** a `TypeError` at mount time — the HUD fails to mount and
`chronos serve --no-web` (i.e. the API-only mode, `phase-6-deploy.md` §A.3
`CHRONOS_WEB=0`) may be the only thing that still works. Low blast radius: no
data loss, and the server still boots if mount is wrapped.

**Recommendation: adopt `mount_hud(app, db_path)` — §F.1 wins.** Reasoning:
§B.4 is a *call site*, §F.1 is the *declaration*. Where a doc disagrees with
itself, the declaration is the normative one; the call site is what gets fixed.
If the built code already has `mount_hud(app)`, make `db_path` an optional
second parameter (`db_path: str | Path | None = None`) rather than editing §F.1 —
one optional parameter satisfies both §F.1's arity and §B.4's call.

---

## 7. Two different `smoke.sh` specifications — which one is the gate?

**Severity: MAJOR**

**Disagreeing docs:** `phase-3-server.md` §F vs `phase-6-deploy.md` §F.2

**Statement A — `phase-3-server.md` §F:**

> gives an 8-check `smoke.sh`
> (`UNVERIFIED-SIDE` — phase-3 not re-read in this pass.)

**Statement B — `phase-6-deploy.md` §F.2 "`scripts/smoke.sh`":**

> `./scripts/smoke.sh 8099`
> 1. Starts `chronos serve --port 8099` in the background.
> 2. Waits for `/api/health` to answer.
> 3. Prints the health response.
> 4. Stops the server.

and §G.5:

> "**Purpose:** Start the server on a given port and verify `/api/health`.
> **Exports:** A health check that exits 0 on success, non-zero on failure."

**Why it breaks:** a gate that is only "did the server answer `/api/health`"
passes on a server with no working search, no working timer, and a broken CLI
entry point (conflict 3). A build gated on the 4-step version ships a green
check on a broken system. This is the same failure mode `decisions.md` warns
about for the v1 FTS bug: "search silently returned nothing because a bare
`except Exception` swallowed an argument error."

**Recommendation: the 8-check version (phase 3 §F) is the gate; phase 6 §F.2
describes a `smoke.sh` that does not exist.** Reasoning: a smoke test whose
entire content is "the process started" cannot distinguish a working server
from an importable one, and phase 6's own §0 principle 5 says "`/api/health` is
the readiness probe" — readiness is necessary, not sufficient. The two are not
actually in conflict once named: **`smoke.sh` = the 8-check gate; the phase-6
4-step procedure is `scripts/health-check.sh` (or a `--quick` flag on
`smoke.sh`).** Reconcile by making phase 6 §F.2 point at phase 3 §F and marking
the phase 6 sequence as the `--quick` mode, so CI can keep a cheap readiness
loop (§E.3 already does exactly this inline) while the real gate stays 8 checks.

---

## 8. `/api/health` payload mismatch

**Severity: MINOR**

**Disagreeing docs:** `phase-6-deploy.md` §B.6 vs `phase-3-server.md` §C.2.20

**Statement A — `phase-6-deploy.md` §B.6 "Verification":**

> `curl -fsS http://127.0.0.1:8080/api/health`
> `# → {"status":"ok","version":"2.0.0","db":"ok"}`

**Statement B — `phase-3-server.md` §C.2.20:**

> `HealthResponse` as `(status, version, db_path, uptime_seconds)`
> (`UNVERIFIED-SIDE` — phase-3 not re-read in this pass.)

`decisions.md` Phase 3 ruling 8 backs form B:

> "**`/api/health` response** — status, version, db_path, uptime_seconds.
> **Ruling: approved.**"

**Why it matters:** three of four fields differ (`db` vs `db_path`, missing
`uptime_seconds`, plus the `db` field's *value* being a bare `"ok"` rather than
a path). Not fatal — `/api/health` is the Docker `HEALTHCHECK`
(`phase-6-deploy.md` §A.6) and the phase-6 §E.3 CI loop, both of which test
only for HTTP 200, not body shape. But a client that reads `db_path` to show
"which database am I talking to" (§11 — a client must show a clear "server is
down" state, implying it also shows *which* server) sees `undefined`.

**Recommendation: form B (`decisions.md` ruling 8) is normative; §B.6's example
body is wrong and must be corrected.** Reasoning: a ruling outranks an example,
and §B.6's line is a comment showing sample output, not a schema. Note that B
also improves A — a `db_path` lets the client detect it is pointed at the wrong
database file, which `"db":"ok"` cannot. Also decide deliberately whether
`db_path` is exposed to an unauthenticated route (§A.6 calls `/api/health` "the
only unauthenticated route"); leaking a filesystem path is minor but it is a
path, so log the basename and return `db_path` only when
`local_only`/`CHRONOS_WEB` conditions allow. That decision belongs to the user.

---

## 9. Docker base image pin disagrees with itself and with `docker.md`

**Severity: MAJOR**

**Disagreeing docs:** `phase-6-deploy.md` §A.1 (internally) and
`/root/docs/server/docker.md`

**Statement A — `phase-6-deploy.md` §A.1 "Base image":**

> | Base image | `python:3.14-slim` | §8.1 — Python + FastAPI; phase doc — "pin the base image version" |
> | Pinned tag | `python:3.14.7-slim-bookworm` | Phase doc — "pin the base image version" |

Two adjacent rows, one loose and one pinned, in the table that exists
*specifically* to pin the version. `decisions.md` Phase 6 ruling 1 resolves it
in favour of the pinned tag:

> "**Base image patch version** — Pin to `python:3.14.7-slim-bookworm`.
> **Ruling: approved.**"

**Statement B — `/root/docs/server/docker.md`:**

> the Dockerfile pins `python:3.14.2-slim-bookworm`
> (`UNVERIFIED-SIDE` — `docker.md` not re-read in this pass.)

**Why it breaks:** §A.2's build stages both `FROM python:3.14.7-slim-bookworm`
verbatim, so a Dockerfile written to the loose `python:3.14-slim` row is not a
pin at all — `3.14-slim` floats to whatever the newest 3.14.x is, so two builds
a week apart produce different images and "reproducible" (§A.1 rationale) is
false. With `3.14.2` vs `3.14.7` the runtime differs by five patch releases;
if any of them changed a `sqlite3`/CVE fix, the user's documented image and the
CI-built image are different programs. The host runs
`/usr/bin/python3` = 3.14.7 (see `environment-corrections.md`), so 3.14.7 is
the version actually validated here — which is the tiebreaker if the user has no
preference.

**Recommendation: `python:3.14.7-slim-bookworm` everywhere.** Amend §A.1's first
row from `python:3.14-slim` to `python:3.14.7-slim-bookworm` (matching §A.2's
two `FROM` lines, which are the operative text), and correct `docker.md` to the
same tag. Reasoning: `decisions.md` already ruled it, §A.2 already implements
it, and the host's validated interpreter is 3.14.7. If `docker.md` genuinely
must say 3.14.2 (e.g. that is the tag the user actually pulled and ran), then
the *decision* is what changes — pin 3.14.2 and re-verify on 3.14.2 — because a
documented-but-unbuilt tag is worse than a built-but-undocumented one.

---

## 10. Missing indexes on two hot paths

**Severity: MINOR**

**Disagreeing docs:** `phase-1-contracts.md` §F.5/§F.9 vs §D.1.5/§D.1.9

**Statement A — `phase-1-contracts.md` §F.5 `buckets`:**

> `CREATE TABLE buckets (` … `start_ms  INTEGER NOT NULL,` `end_ms    INTEGER NOT NULL,`
> `seq       INTEGER NOT NULL` `);`

No `CREATE INDEX` at all in §F.5 — §F.5's "Indexes" line is absent, while
§F.1, §F.4, §F.8 each end with an explicit `CREATE INDEX` and an "**Indexes:**"
line.

**Statement B — `phase-1-contracts.md` §D.1.5 `BucketRepo`:**

> `def get_by_level_and_date(self, level: BucketLevel, date_ms: int) -> Optional[Bucket]: ...`

**Statement C — `phase-1-contracts.md` §D.1.9 `TimerSessionRepo`:**

> `def get_running(self) -> Optional[TimerSession]: ...`

§F.9 `timer_sessions` likewise has no index, and the query this serves —
`SELECT … WHERE ended_at IS NULL` — is issued on **every** `GET /api/timer`,
every `chronos` CLI invocation, and every `/api/say` turn. §A.9 notes state the
constraint it serves:

> "One timer runs at a time, across all three modes (§4.7, phase doc)."

so the result set is 0 or 1 rows and SQLite cannot know that.

**Why it matters:** both are full table scans. `timer_sessions` is the worst:
it is the highest-growth table in the schema (one row per work session, never
pruned — §E.6 prunes *audit* and *logs*, not timers), and it is scanned on the
hot read path of every request that reports timer state. On a multi-year
database this turns each `GET /api/timer` into a scan of the entire history.
`buckets` is ~4303 rows (§F.14) so its scan is bounded and cheap — which is why
this is MINOR and not MAJOR.

**Recommendation: add two indexes as an announced amendment to §F**, in the same
style as conflict 4:

```sql
CREATE INDEX ix_buckets_level_start ON buckets(level, start_ms);
CREATE INDEX ix_timer_sessions_running ON timer_sessions(ended_at) WHERE ended_at IS NULL;
```

Reasoning: `ix_buckets_level_start` matches `get_by_level_and_date`'s predicate
exactly. The `timer_sessions` one is a **partial** index on the invariant from
§A.9 — it stays ~1 row forever regardless of table size, which is the correct
shape for "one running timer" and also makes the "refuse to start a second
timer" ruling (`decisions.md`, "Timer, start while one is running. *Ruling:
refuse*") enforceable as a `UNIQUE` constraint on a constant column if the user
wants the guarantee pushed into the schema. Do **not** add these silently in the
repo layer — they belong in the frozen §F so migrations and tests agree.

---

## 11. Phase 2 file layout divergence from the built tree

**Severity: MAJOR**

**Disagreeing docs:** `phase-2-ai.md` §H vs the built `chronos/ai/` tree

**Statement — `phase-2-ai.md` §H "File layout" (verified exact):**

> `chronos/ai/`
> `  __init__.py              — re-exports public names`
> `  providers/`
> `    __init__.py            — re-exports provider names`
> `    adapter.py             — Adapter, ChatResponse, TokenUsage, ProviderError types, build_adapters_from_env`
> `    chain.py               — Chain, ChainRequest, ChainResult, retry constants`
> `    worker.py              — RetryWorker, RetryJob, WorkerStatus`
> `    stt.py                 — transcribe_audio, STT configuration`
> `  pipeline/`
> `    __init__.py            — re-exports pipeline names`
> `    packer.py              — Packer, TurnContext, PackedContext, CutRecord`
> `    intent.py              — IntentParser, IntentResult, needs_second_turn`
> `    verify.py              — Verifier, VerifiedResult, Correction`
> `    tools.py               — ToolDispatcher, all 27 tool implementations`
> `  cost.py                  — CostTracker, DailyCost`
> `  prices.py                — PriceTable, DEFAULT_PRICES`
> `  cost_hook.py             — cost_hook, CostHook`

§H.15 adds the DAG for the same paths, and §H.1–H.14 give each file's imports
and exports individually. §J summarises: "**14 files** in `chronos/ai/` with a
DAG import graph".

**Built tree:** AI code is flat in `chronos/ai/`; neither `providers/` nor
`pipeline/` exists, and there is no `prices.py` and no `cost_hook.py`. §H.13 and
§H.14 (`prices.py`, `cost_hook.py`) are therefore missing outright.

**Why it breaks:** the missing files are load-bearing, not cosmetic.
`PriceTable`/`DEFAULT_PRICES` (§G.4, §G.5) is what makes `cost_usd` a real
number instead of `None` forever; `cost_hook` (§G.6) is what makes cost
recording automatic. §G.7's note — "`cost_usd` is `NULL` when the price is
unknown — never `0.0`" — degenerates into "`cost_usd` is *always* NULL" with no
`prices.py`, which then makes `export_cost` (§G.2) write an empty cost column
for every row forever. Meanwhile the flat tree violates §0 principle 1
("Every module imports from `chronos/contracts/` and nothing else from its
siblings") by co-locating modules that §H.15 deliberately separated to keep the
import graph acyclic.

**Recommendation: reconcile by amending §H to the flat layout, and restore the
two missing modules under their §H names.** Reasoning: moving 10 files into two
subpackages to match a doc, when the flat layout already imports cleanly and has
tests green, is churn with no behavioural gain — but *deleting* `prices.py` and
`cost_hook.py` is a real functional loss and must not be ratified by rewriting
the doc to match the tree. Concretely: amend §H/§J to the actual flat file list;
add `chronos/ai/prices.py` (exports `PriceTable`, `DEFAULT_PRICES` per §H.13)
and `chronos/ai/cost_hook.py` (exports `cost_hook`, `CostHook` per §H.14); and
amend §H.15's DAG to the flat import graph, keeping the one invariant that
mattered — `prices.py` stays a leaf with no imports from `ai/`, so the graph is
still acyclic. Only if the user prefers the §H layout should the files be moved
instead; that is a real choice and it is theirs.

---

## 12. Phase 5 public functions do not exist under the frozen names

**Severity: MAJOR**

**Disagreeing docs:** `phase-5-features.md` §B.3/§D.3/§E.5/§F.3/§G.2 vs the
built modules

**Frozen declarations (verified exact):**

- §B.3 — "def search_with_scores(self, query: str, limit: int = 10) -> list[SearchResult]:"
- §D.3 — "def generate(self, date: str) -> Briefing:"
- §E.5 — "def get_stats(self, days: int = 7) -> dict:" (on `StatsCollector`)
- §F.3 — "def list_entries(self, filter: AuditFilter | None = None) -> list[AuditEntry]:" (on `AuditViewer`)
- §G.2 — "def export_events(self, start_ms: int, end_ms: int) -> str:" (on `CSVExporter`)

§H.4–H.8 then re-state the module locations: `NodeSearch` in
`chronos/db/search.py`, `AuditViewer` in `chronos/db/audit.py`,
`BriefingGenerator` in `chronos/ai/briefings.py`, `StatsCollector` in
`chronos/ai/stats.py`, `CSVExporter` in `chronos/ai/export.py`. §C.2 depends on
the first: "The `check_conflict` tool handler … calls
`NodeSearch.search_with_scores()`".

**Built code exposes module-level functions instead:**
`search_nodes`, `check_conflict`, `generate_briefing`, `get_stats`,
`get_audit_log`, `export_events_csv`.

**Why it breaks:** this is not a rename, it is a **shape** change. Every one of
the five frozen names is a *method on a class that takes injected
dependencies*; every built name is a *module-level function that reaches for its
own dependencies*. `StatsCollector.get_stats(self, days)` was handed
`db, node_repo, event_repo, timer_repo, audit_repo, clock` at construction
(§E.5); a module-level `get_stats` has no construction point, so it either
opens its own connection (defeating the DbConnection abstraction §B.4 and the
dual Session/Connection support that §B.4 exists to fix) or is a thin wrapper
that re-reads globals. `BriefingGenerator.generate(self, date)` likewise loses
its injected `ClarificationBudget` — which §D.4 requires to be
*restart-persistent*: "A fresh `ClarificationBudget` built from the same database
sees the day as spent". If the budget is re-derived per call, that ruling
silently regresses to the exact v1 failure the phase doc quotes: "'counter is in
memory, not persisted'". Downstream, `check_conflict`'s contract change (§C.2,
`semantic_candidates: array[SearchResult]`) depends on `search_with_scores`
existing; `check_conflict` as a module-level function has no `NodeSearch` to ask.

**Recommendation: the frozen class-based surface wins — it is the only one of
the two that satisfies the persistence and injection requirements the same
proposal makes.** Keep the class methods exactly as §B.3/§D.3/§E.5/§F.3/§G.2
declare them. If the built module-level functions are already covered by passing
tests, they stay — but as **thin delegating wrappers** that construct the class
with injected deps and forward, not as the primary implementation. Then add
import-time aliases so both call styles resolve. Explicitly do *not* ratify the
flat-function shape by amending the proposal: doing so would amend away §D.4's
persistence guarantee and §B.4's dual-connection fix in the same stroke.

---

## 13. `mcp` is a required package but not a declared dependency

**Severity: MINOR**

**Disagreeing docs:** `phase-4-interfaces.md` §C vs
`phase-6-deploy.md` §D.2/§D.3

**Statement A — `phase-4-interfaces.md` §C:**

> requires `chronos/mcp/`
> (`UNVERIFIED-SIDE` — phase-4 not re-read in this pass.)

`phase-6-deploy.md` §D.6 confirms the package is expected to exist:

> "This includes `chronos/` and all subpackages (`chronos/contracts/`,
> `chronos/db/`, `chronos/core/`, `chronos/ai/`, `chronos/api/`,
> `chronos/realtime/`, `chronos/notify/`, `chronos/mcp/`, `chronos/cli/`,
> `chronos/web/`)."

**Statement B — `phase-6-deploy.md` §D.2 `dependencies`:**

> `dependencies = [`
> `    "fastapi>=0.115",` `    "uvicorn>=0.30",` `    "sqlalchemy>=2.0",`
> `    "alembic>=1.13",` `    "argon2-cffi>=23.1",` `    "sqlite-vec>=0.1.6",`
> `    "python-multipart>=0.0.9",` `    "httpx>=0.27",`
> `]`

**§D.3 `optional-dependencies`** adds only `dev = ["pytest>=8.0", "ruff>=0.6"]`.
No MCP package appears in either list. `decisions.md` Phase 4 ruling 4 does
confirm the feature is in scope: "**MCP transport** — HTTP with `/mcp` endpoint.
*Ruling: approved.*"

**Why it matters:** MINOR because a standards-compliant MCP server can be
implemented over plain HTTP/FastAPI with no SDK — which is likely what was
built, and is defensible. But the docs say `chronos/mcp/` is a package, which
reads as "an MCP client library is used here", and a reader will assume the
dependency is declared. If the SDK *is* imported, `pip install -e .` from a
clean checkout (§D.7, "Verification") fails on `ModuleNotFoundError` in a fresh
environment — and CI's clean-checkout job (§E.2) would catch it, which is the
only reason this is not MAJOR.

**Recommendation: resolve by clarifying which it is, then make the docs say so.**
If `chronos/mcp/` is a hand-rolled FastAPI router implementing the `/mcp`
endpoint per ruling 4, **amend §D.6 to drop `chronos/mcp/` from the "SDK-backed"
implication** — better: state in §D.6 that the MCP endpoint is implemented with
no third-party SDK, and nothing changes in `pyproject.toml`. If an SDK *is*
imported, **add it to §D.2** — and if the SDK's own transitive deps would break
the pinned `python:3.14.7-slim-bookworm` image (§A.2, and conflict 9), it
belongs in an `[project.optional-dependencies]` extra with a documented
degrade-when-absent path, matching `phase-5-features.md` §0 principle 7 ("No
module raises on a missing optional dependency"). Do not leave the two docs
implying different things.

---

## Summary

| # | Conflict | Severity | Docs | Recommendation in one line |
|---|---|---|---|---|
| 1 | `token_cost` vs `token_costs` | BLOCKER | p2 §G.7 / p5 §E.2.1 | One table: `token_costs`, amend §G.7 |
| 2 | contentless `node_fts` | BLOCKER | p1 §F.12 / §D.6 / p5 §B.3 | Prefer dropping `content=''`; else join on a §6 rowid column |
| 3 | `chronos.cli.main:main` | MAJOR | p6 §D.4 / p4 §B.11 | Add a one-line shim; both names resolve |
| 4 | `node_links` has no DDL | MAJOR | p1 §C.4, §F / Chronos §4.1 | Add DDL to §F; `link_id` = `src:tgt` |
| 5 | `SettingsRepo` not frozen | MAJOR | p3 §A.6 / p1 §D.1 | Add as 11th repo protocol, incl. `merge` |
| 6 | `mount_hud` arity | MINOR | p4 §B.4 / §F.1 | §F.1 wins; make `db_path` optional |
| 7 | two `smoke.sh` specs | MAJOR | p3 §F / p6 §F.2 | 8-check is the gate; phase-6 becomes `--quick` |
| 8 | `/api/health` body | MINOR | p6 §B.6 / p3 §C.2.20 | Ruling 8 wins; fix §B.6's example |
| 9 | base image pin | MAJOR | p6 §A.1 / `docker.md` | `python:3.14.7-slim-bookworm` everywhere |
| 10 | missing hot-path indexes | MINOR | p1 §F.5, §F.9 / §D.1.5, §D.1.9 | Add `ix_buckets_level_start` + partial running index |
| 11 | phase-2 file layout | MAJOR | p2 §H / built tree | Amend §H to flat; **restore `prices.py`, `cost_hook.py`** |
| 12 | phase-5 public functions | MAJOR | p5 §B.3/§D.3/§E.5/§F.3/§G.2 / built | Class surface wins; flat functions become wrappers |
| 13 | `mcp` dependency | MINOR | p4 §C / p6 §D.2, §D.3 | Declare it, or state the endpoint is SDK-free |

**2 BLOCKER, 7 MAJOR, 4 MINOR.**

## How to rule

Each entry is self-contained: read the two quoted statements, then the "Why it
breaks", then the recommendation. Where an entry says the *recommendation* is to
amend a frozen proposal, that amendment should be appended to
`decisions.md` in its existing format (**date — what was disputed — ruling —
why.**) so the next session does not relitigate it — and the amendment should
also be reflected in the proposal file, since `phase-5-features.md` §0 principle
6 already establishes the precedent of announcing deliberate changes to the
frozen contracts.

Entries marked `UNVERIFIED-SIDE` need their counterpart quote re-read
(phase-3-server.md, phase-4-interfaces.md, `docker.md`,
`contract-and-interfaces.md` §6, Chronos.md §4.1) before the ruling is recorded.
See also `environment-corrections.md` for three host facts that contradict the
docs and must not be re-derived.