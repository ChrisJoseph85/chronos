# Chronos — real code state vs phase plans

Investigated 2026-10-03. All claims below are backed by commands actually run.

## 0. HEADLINE: the code is NOT at /root/Chronos

- `/root/Chronos` is an **empty directory**. The `.git` at `/root/.git` has
  **zero commits, zero refs, zero objects** (`git count-objects -v` → all 0).
  There is no branch, no tag, no reflog, no stash. `git log` on any ref fails.
- The claimed tags `v1.0-foundation` and `v1.0-leaves` **do not exist**. Nothing
  in /root/docs or elsewhere references them either — they appear to be invented.
- A **complete working copy of the project survives at**
  `/root/.hermes/cache/scratch/chronos_head` (≈11.9k LOC of `chronos/`,
  8.2k LOC of tests, Dockerfile, compose, CI, scripts, web HUD).
  It is **not a git repo** — it is an unversioned scratch copy. Its
  `.venv` symlink pointed at `/root/Chronos/.venv`, which no longer exists, so
  its environment is broken.
- Runtime residue confirms the server *did* run at some point:
  `/root/.chronos/chronos.db` (+ WAL, 655 KB), and ~10 `chronos-smoke.*` dirs
  in scratch plus `/tmp/chronos_smoke_*.log`. One log shows a live uvicorn on
  :8097 with correct behaviour — `/api/health` unauthenticated, 10 other routes
  401ing without a key, then 200 after `POST /api/say`, and the key already
  redacted in the logged URL (`GET /api/nodes?key=***`). Auth + redaction worked.

**Conclusion: no work is lost, but nothing is committed and the tags are fiction.**
The build is one `rm -rf` away from being lost, and git has no record of it.

## 1. What the code actually is

Package `chronos` v2.0.0, requires-python >=3.14, deps fastapi/uvicorn/
sqlalchemy/alembic/argon2-cffi/sqlite-vec/python-multipart/httpx.
**`mcp` is NOT a declared dependency** (see phase 4).

| Area | LOC | Files |
|---|---|---|
| ai | 3645 | adapter, chain, retry, setup, cost, packer, intent, verify, dispatcher, briefings, stats, export |
| db | 2652 | engine, repos, search, seed, audit, migrations |
| api | 1859 | app, auth, routes, voice |
| contracts | 1401 | models, enums, ddl, tool_schemas, protocols, constants |
| cli | 534 | `__main__.py`, commands |
| mcp | 446 | server, tools, auth |
| core | 779 | scheduling, time_utils |
| realtime | 329 | hub, protocol |
| notify | 190 | ntfy, scheduler |
| web | 34 + static | `index.html`, `app.js`, `styles.css` |

Tests: 6 spec files, one per phase, 8173 LOC.

## 2. Reproducible verification

Environment had to be rebuilt (`/root/Chronos/.venv` gone):
```
uv venv --python 3.14 .venv && uv pip install -e ".[dev]"
```

### Results
```
ruff check .      → 157 errors (54 E501, 31 F401, 21 I001, 13 F841,
                     4 F821 undefined-name, 3 F402, 58 auto-fixable)
pytest -q         → 212 failed, 405 passed, 2 skipped, 70 errors
```

Per phase:

| Phase | Result | Verdict |
|---|---|---|
| 1 core | 5 failed, 210 passed | ~97% done, real defects |
| 2 ai | **118 failed, 9 passed** | largely not delivered |
| 3 server | 20 failed, 18 passed, 70 errors | broken end-to-end |
| 4 interfaces | 7 failed, 105 passed | mostly there |
| 5 features | **54 failed, 1 passed** | largely not delivered |
| 6 deploy | 8 failed, 62 passed, 2 skipped | mostly there, packaging broken |

## 3. Confirmed real defects

### a) `migrations.py` never loads sqlite-vec → **the server cannot start**
`chronos/db/migrations.py:27` opens a raw `sqlite3.connect` and runs
`DDL_STATEMENTS`, which include `CREATE VIRTUAL TABLE node_vec USING vec0(...)`
(`contracts/ddl.py:127`). `engine.py` *does* load the extension
(`enable_load_extension`/`sqlite_vec.load`, lines 46-48) — `migrations.py` does
not. Result: `sqlite3.OperationalError: no such module: vec0`, which cascades
into 70 phase-3 setup errors. This is precisely the failure mode phase 4's doc
warns about ("the migration must load the sqlite-vec extension").
I applied the 4-line fix in the scratch copy and confirmed `vec0` errors clear;
the remaining phase-3 failures are separate (see b).

### b) Bucket seed violates its own FK at the year boundary — **app startup crashes**
`seed_buckets` inserts Y→M→W→D in one ordered pass with
`PRAGMA foreign_keys=ON`, but ISO week 1 of a year can start in December of the
previous year. Traced precisely: `W:2026-W01` gets parent `M:2025-12`, which
does not exist because seeding starts at the current year. Also cascades to its
days. Exactly **5 of 4312** rows fail — and one of them aborts the whole
`create_app` (`api/app.py:113` → `seed.py:185`), so every phase-3 app test
errors. Fix must generate the preceding December (or the ISO year, not the
calendar year) before seeding. Phase 1's doc demands the W→M nesting be exact,
so this is a spec violation, not a tolerance.

### c) `chronos` console script is broken — **CLI does not run at all**
`pyproject.toml` declares `chronos = "chronos.cli.main:main"`, but there is no
`chronos/cli/main.py`; the module is `chronos/cli/__main__.py`. Running the
installed entry point:
```
ModuleNotFoundError: No module named 'chronos.cli.main'
```
This is phase 4's stated rule ("Every command must actually run") and phase 6
packaging, both broken at the entry-point level. Fix: point pyproject at
`chronos.cli.__main__:main` (or add a `main.py` shim).

### d) Phase 2 package layout does not match its own plan
Plan: `chronos/ai/providers/{adapter,chain,worker,stt}.py`,
`chronos/ai/pipeline/{packer,intent,verify,tools}.py`, `ai/prices.py`,
`ai/cost_hook.py`.
Actual: flat `chronos/ai/*.py` — no `providers/` or `pipeline/` subpackages,
no `prices.py`, no `cost_hook.py`. Test imports (`chronos.ai.pipeline`,
`chronos.ai.providers`) fail 230 times. Also absent anywhere: `chronos/db/orm.py`,
`bootstrap.py`, `buckets.py`, `repo.py` (folded into `repos.py`/`seed.py`), and
the whole `alembic/` directory that phase 1 part 1.6 requires.
Note the tests encode the *plan's* paths, so this is a real spec/implementation
divergence, not a test artifact.

### e) Phase 5 exports nothing the tests (or callers) expect
`db/search.py` exports only `NodeSearch`, `find_semantic_candidates` — missing
`search_nodes`, `index_node`, `check_conflict`. `ai/briefings.py` has
`ClarificationBudget`, `BriefingGenerator` but no `generate_briefing`.
`ai/stats.py` has `StatsCollector` not `get_stats`; `db/audit.py` no
`get_audit_log`; `ai/export.py` no `export_events_csv`/`export_cost_csv`.
Implementation exists as classes; the function-level API the tests and phase-3
routes expect is absent. 54/55 phase-5 tests fail.

### f) `mcp` is not a dependency
12 phase-4 failures are `ModuleNotFoundError: No module named 'mcp'`. `mcp/`
code is written but the package is undeclared in pyproject, so a clean install
cannot import it.

### g) Lint is far from clean
157 ruff errors including **4 F821 undefined-name** — genuine runtime NameError
risks, not style. One phase-3 test also fails on
`Protocols cannot be instantiated` and phase-1 fails `test_event_repo_exists`
(`name 'EventRepo' is not defined`) — the repo Protocol named in the frozen
contracts surface is missing. Also a test-only issue: `pytest` reports
"async def functions are not natively supported" for a WebSocket test —
`pytest-asyncio`/`anyio` is not configured, so async tests cannot pass.

### h) Phase 6 failures that are *test* bugs, not code bugs
Two are false alarms and should be fixed in the tests:
- `test_install_pip_install` asserts the literal `"pip install"` and `"-e ."`;
  `termux.sh:26` uses `"$HOME/.chronos/venv/bin/pip" install -e .` — the
  substring never matches an absolute-path invocation.
- `test_start_nohup_serve` asserts `"chronos serve"` as a literal substring;
  `termux.sh:36` calls the absolute `"$HOME/.chronos/venv/bin/chronos" serve`.
Also `pip install -e .` in-script fails in a uv venv ("No module named pip"),
and `test_version_single_sourced` fails (version 2.0.0 is hardcoded in
pyproject while `__init__.py` presumably has its own).
Genuinely missing: no code announces the embedding download
(`[SPEC AMBIGUITY]` marker, phase 6's §11 requirement).

## 4. Phase-by-phase verdict

| Phase | Done? | Evidence |
|---|---|---|
| **1 core** | **~yes, with bugs** | 210/215 pass. Contracts, DDL, scheduling, seed all present. Fails: missing `EventRepo` Protocol, audit `ID INTEGER PRIMARY KEY` DDL, review_series check constraint. Defects (a)/(b) live at its boundary. |
| **2 ai** | **no** | 9/127 pass. All 14 files exist and are substantial (3.6k LOC), but layout diverges from the plan so nearly every import fails. Layering untested/unverified. |
| **3 server** | **broken** | Cannot even start: (a) vec0, then (b) FK. Auth/realtime/routes exist and the historical smoke log proves auth+redaction worked at runtime once. |
| **4 interfaces** | **mostly** | 105/112 pass. Web HUD assets present, CLI present, MCP code present but undeclared dep + entry point broken. |
| **5 features** | **no** | 1/55 pass. Modules exist but the expected function-level API is missing throughout (e). |
| **6 deploy** | **mostly** | 62/70 pass. Dockerfile, compose, both CI workflows, backup/restore/smoke scripts all exist. Broken: console entry point, version sourcing, embedding download notice; 3 of the 5 remaining failures are test-assertion bugs. |

## 5. Bottom line

The **shape** of the whole product is built and the design work is real —
contracts, schema, scheduling, AI layer, server, HUD, CLI, MCP, deploy all
exist as substantial code. But it is **not in a shippable state**:

- 212 failed / 70 errored tests.
- Two hard startup blockers (vec0 extension, bucket FK) mean **`create_app` has
  not successfully run in the current tree**.
- The `chronos` CLI entry point is broken outright.
- No git history exists; the only copy is an unversioned scratch dir.

Priority fixes: (1) commit the scratch copy to /root/Chronos immediately;
(2) `migrations.py` vec0 load; (3) bucket year-boundary parent; (4) pyproject
entry point; (5) decide flat-vs-subpackage AI layout and align tests or code.