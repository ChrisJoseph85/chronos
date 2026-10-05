# Cross-Cutting Audit — /root/Chronos
Read-only. `chronos/ai/` excluded (concurrent restructuring; its 4 ruff hits are noise).
All findings verified by execution unless marked "by inspection".

---

## 1. Ruff gate — FAIL (158 errors, must be 0)

`ruff check chronos tests` → **158 errors**, 62 auto-fixable.

| count | code | note |
|---|---|---|
| 54 | E501 | line too long |
| 32 | F401 | unused import |
| 24 | I001 | import block unsorted |
| 13 | F841 | unused local variable |
| 6 | RUF012 | mutable class default |
| 5 | RUF059 | unused unpacked variable |
| 4 | F541 | f-string without placeholders |
| 3 | S603 | subprocess-without-shell-equals-true (the `_run` helpers) |
| 3 | F402 | import shadowed by loop var |
| 2 | S108 | hardcoded temp dir (`/tmp`) |
| 2 | RUF003 | ambiguous unicode in comment |
| 2 | B007 | unused loop variable |

By directory: tests/phase_4 38, phase_2 37, phase_5 29, phase_3 20, phase_1 20, phase_6 10,
chronos/ai 4 (ignored).

Note: CI (`.github/workflows/ci.yml`) runs `ruff check chronos tests` as a **hard step with no
`|| true`** — so CI has been red on lint since the first commit that added a violating file.
Locally `ruff` exit code was masked because output was piped to `tail` (pipefail not set).

---

## 2. Smoke gate — the script exists, is executable, and has NEVER PASSED

`scripts/smoke.sh` exists, mode `-rwxr-xr-x`. What it checks: starts `chronos serve --port $PORT
--db $DB` in the background, polls `http://127.0.0.1:$PORT/api/health` for 30s, prints the health
body, exits 0. On timeout prints "did not become healthy" and exits 1. It traps EXIT to kill the
server and delete the smoke DB.

**Verified execution:**
- Bare `./scripts/smoke.sh 8099` → `chronos: command not found`, real exit code **1**. The script
  invokes bare `chronos`, not `.venv/bin/chronos`, and never puts the venv on PATH.
- With `PATH=.venv/bin:$PATH CHRONOS_DB=<scratch> ./scripts/smoke.sh 8098` → **passes**:
  `healthy` + `{"status":"ok","version":"0.1.0",...}`. So the server does boot.

Two defects, both real:
1. **`smoke.sh` cannot pass as invoked** from a bare shell, which is how the docs and CI invoke it
   (`./scripts/smoke.sh 8099` — docs/phases/phase-3-server.md:108, phase-6-deploy.md:106).
2. **`./data/` does not exist** in the repo and the default `CHRONOS_DB=./data/chronos-smoke.db`
   writes into a missing directory. Passing the PATH alone is not enough; `CHRONOS_DB` must also be
   set or `data/` created.

`pytest tests/phase_3 -k Smoke` → **1 failed, 2 passed**:
`TestSmokeScript::test_smoke_script_boots_server` FAILS (the `pytest.skip("smoke.sh not found")`
guard never trips — the file exists, the script just fails). The "exists" and "is executable" tests
pass and give a false sense of coverage.

**Phase 3's done-criteria is therefore NOT met.** `docs/phases/phase-3-server.md:89` still shows
`[ ]` for "smoke.sh boots the real server and passes every check" — the unchecked box is accurate.

---

## 3. Packaging and entry points

| check | result |
|---|---|
| `.venv/bin/chronos --help` | works — 7 subcommands (serve, key-renew, db-upgrade, token-cost, export, say, get) |
| `.venv/bin/chronos --version` | **DOES NOT EXIST** — `error: unrecognized arguments: --version` |
| `import chronos; chronos.__file__` | **`None`** — namespace package, no `__init__.py` |

**`--version` missing is confirmed, and it is a test failure, not a cosmetic gap:**
- `tests/phase_6/test_deploy_spec.py::TestPackaging::test_chronos_version` — FAIL
- `tests/phase_6/test_deploy_spec.py::TestPackaging::test_version_single_sourced` — FAIL

Both call `_run(["chronos", "--version"])`. They fail on `FileNotFoundError: 'chronos'` (bare name
not on PATH), and would *still* fail on a correctly-invoked CLI because the flag does not exist.
Both tests are legitimate; the CLI is the defect.

**Version drift — three different version numbers in the tree:**
- `pyproject.toml`: `version = "2.0.0"`, and `pip show chronos` → `2.0.0` (consistent)
- `chronos/api/app.py:157` `FastAPI(title="Chronos", version="0.1.0")`
- `chronos/api/app.py:186` health payload `"version": "0.1.0"` ← **what the live server returns**
- `chronos/mcp/server.py:50` `Server("chronos", version="0.1.0")`
- `mcp/server.py:50` `version="0.1.0"` — a *fourth* source, hand-written

So "version is single-sourced" is false in practice. The `2.0.0` in pyproject is never surfaced
anywhere at runtime. Live health response confirmed: `{"status":"ok","version":"0.1.0",...}`.

**`websockets` — CONFIRMED MISSING, and it is the cause of the WebSocket 404 (reproduced live).**

`pip show websockets` → not found. Declared in `pyproject.toml`? No — not in `dependencies`, not in
the `dev` extra. Uvicorn was installed as plain `uvicorn`, not `uvicorn[standard]`.

Live reproduction (server on :8097, real HTTP upgrade request):
```
WARNING:  Unsupported upgrade request.
WARNING:  No supported WebSocket library detected. Please use
          "pip install 'uvicorn[standard]'", or install 'websockets' or 'wsproto' manually.
INFO:     127.0.0.1:45942 - "GET /ws HTTP/1.1" 404 Not Found
```
The route is **registered correctly** — `create_app()` introspection shows
`[] /ws APIWebSocketRoute`. Starlette handles the upgrade, then uvicorn finds no WS implementation,
fails the upgrade, and the request falls through to the HTTP 404 handler. Adding `websockets` to
`dependencies` (or installing `uvicorn[standard]`) is the one-line fix, and the missing dep is
100% the cause — the earlier "missing `websockets`" report is confirmed, not a red herring.
No websocket test catches this: the 8 WS tests are async and never run (see §5).

**`mcp` — declared? No. Used? Yes.** `chronos/mcp/server.py:25` does `from mcp import types` via
`_load_sdk()`. `pip show mcp` → not found. The code documents this deliberately: "The SDK is not a
declared dependency of Chronos (see pyproject.toml), so it is imported lazily ... `create_mcp_server`
must remain importable without it." So `chronos.mcp.server` imports fine, but
**`create_mcp_server()` raises ImportError at runtime in any stock install** — §8.4's MCP server
cannot be constructed. The contract "tools are adapted to an injected executor" is preserved; the
actual server is unstartable. Acceptable as a deliberate optional-SDK design, but it must ship as a
declared optional extra (e.g. `[project.optional-dependencies] mcp = ["mcp>=1.0"]`), otherwise no
user can ever run the feature. No Dockerfile or CI reference to mcp.

---

## 4. Secret and safety invariants — PASS (verified by inspection)

`.gitignore` excludes: `.venv/`, `.env`, `__pycache__/`, `*.pyc`, `*.egg-info/`, `dist/`, `build/`,
`.pytest_cache/`, `.ruff_cache/`, `*.db`, `*.sqlite`, `*.sqlite3`, `*.bundle`, `.DS_Store`.

`.dockerignore` excludes the same secret/state set plus `.git/`, `.github/`, `tests/`, `android/`,
`docs/`, `scripts/`.

- **`.env` excluded from git? YES.** (`.gitignore` line 2)
- **`.env` excluded from docker build context? YES.** (`.dockerignore` line 3)
- **`*.db` gitignored? YES** — `*.db`, `*.sqlite`, `*.sqlite3` all present. No `.db` files exist on
  disk anywhere in the repo tree.
- **Any real key/credential tracked? NO.** `git ls-files` filtered for
  `.env|.db|.pem|.key|secret|credential|.sqlite` returns exactly one hit: **`.env.example`** — and its
  contents are entirely commented-out placeholders (`# CHRONOS_DB=`, `# TEXT_PROVIDER_1_KEYS=key1,key2`).
  No live value. The example file's own header states ".env is never committed" — true.
- Instance keys are generated at runtime into `~/.chronos/key` (outside the repo) and only their
  argon2 hash is stored in the DB. The smoke run printed a fresh key to the log as designed, and
  smoke.sh's DB is deleted by its EXIT trap.

No secret or safety finding. This section is genuinely clean.

---

## 5. Dead / vacuous tests

**Permanently-true assertions — 3, all in phase 1, all the same defect:**
`tests/phase_1/test_contracts_spec.py:1662, 1667, 1672`
```python
assert "1, 2, 4, 8, 16" in spec_str or "1,2,4,8,16" in spec_str.replace(" ","") or True  # Placeholder
assert "3, 7, 15, 30" in ... or True  # Placeholder
assert "10, 30, 90" in ... or True  # Placeholder
```
The trailing `or True` makes each a no-op. These are the interval-preset ladder checks; the
comment says "implementation must expose these" — they verify nothing about the implementation.

**xfail: none.** Zero `@pytest.mark.xfail` in the suite, so no stale-xfail/XPASS red flags. The 4
ruff `F401` "unused import" hits in tests are the usual xfail-adjacent smell but are not xfails.

**skip: exactly 1** — `tests/phase_3/test_server_spec.py:1054`, `pytest.skip("smoke.sh not found")`.
It never fires and masks nothing today, but it would silently hide a deleted smoke script.

**`pytest-asyncio` IS MISSING — 8 async tests never ran, and all 8 FAIL.**
- Declared? No — not in `dependencies`, not in the `dev` extra. `pip list` confirms absent.
- 8 `@pytest.mark.asyncio` + 8 `async def test_`, **all in `tests/phase_3/test_server_spec.py`**.
- No `tests/conftest.py` exists anywhere in the repo, and no `asyncio_mode` in `[tool.pytest.ini_options]`.
- Verified run: `pytest tests/phase_3 -k asyncio` → **8 failed, 100 deselected**, each with
  `PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?`.

This is the highest-severity test finding. The silent-`async def` collection is the classic trap:
pytest 9 collects them, sees a coroutine object instead of a result, and fails. The 5 affected
tests include the entire **WebSocket auth** surface — `TestRequireKeyWebSocket::
test_require_key_ws_success`, `..._missing_returns_4001`, `..._wrong_key_returns_4001`, plus
`TestRequireKey::test_require_key_no_hash_returns_503` and
`test_require_key_query_string_fallback`. So the WS auth path that §5 of phase 3 exists to certify
has **zero executed coverage**, and `dev = ["pytest>=8.0", "ruff>=0.6"]` will not install a working
async plugin for any contributor. Note also `pytest>=8.0` is very loose while the lock has 9.1.1.

**Test counts per phase file** (`def test_` counts; 689 collected total, so 39 are parametrized
expansions or non-`test_`-named):

| file | def test_ |
|---|---|
| phase_1/test_contracts_spec.py | 215 |
| phase_2/test_ai_spec.py | 127 |
| phase_3/test_server_spec.py | 108 |
| phase_4/test_interfaces_spec.py | 73 |
| phase_6/test_deploy_spec.py | 72 |
| phase_5/test_features_spec.py | 55 |
| **total** | **650** |

`_spec_assert` in phase 6 is a **real** assert (raises `AssertionError(f"[{tag}] {message}")`) and is
used 79 times, with 0 bare `assert` in that file — no vacuity there. `S603` on the `_run` helper is
correct lint, not a bug.

---

## 6. Git hygiene

- **6 commits.** HEAD `141082c` "Phase 1 done (215 passed); fix 27 real AI-layer bugs…".
- **Working tree: 15 modified/untracked entries** — all in `chronos/ai/` (the concurrent
  restructuring) plus `chronos/api/voice.py`. `chronos/api/voice.py` being modified is worth noting
  as it is *outside* the ai/ tree the restructuring agent owns. Nothing else dirty.
- **Largest commit: `d4bd9f0` "Salvage of Chronos v1 tree" — 96 files, 32,428 insertions in one
  commit.** This is the initial import: all source + all tests + docs landed as a single blob with
  no incremental history. Not corrupt, but there is no usable bisect history.
- **No junk committed.** 98 tracked files: 57 `.py`, 25 `.md`, 4 `.sh`, 3 `.yml`, 1 each
  `.toml/.js/.html/.gitignore`. Largest tracked file is 86 KB (`tests/phase_2/test_ai_spec.py`).
  No binaries, no `.db`, no caches, no `node_modules`, no stray archives.
- **`chronos/__init__.py` is NOT tracked and does not exist on disk** (only subpackage
  `__init__.py` files are tracked: ai, api, cli, contracts, core…). The installed package resolves
  as an implicit **namespace package** via the editable install's finder
  (`.venv/lib/python3.14/site-packages/__editable___chronos_2_0_0_finder.py` +
  `__editable__.chronos-2.0.0.pth` are present), which is why `import chronos` succeeds with
  `__file__ is None`. Fragile: namespace packages do not export anything and break `importlib`
  metadata lookups, and `pyproject.toml`'s `[tool.setuptools.packages.find] include = ["chronos*"]`
  will not package the top-level `chronos` namespace in a **non-editable** `pip install` — so
  `docker build` (which does a real install, not `-e`) is the exposure. A real
  `chronos/__init__.py` is needed.

---

## 7. CI reality check

`.github/workflows/ci.yml` has three jobs behind a `guard` that skips cleanly if `chronos/` has no
`.py`. It runs, in order: `pip install -e ".[dev]"` → `ruff check chronos tests` → `pytest tests -q`,
then a `docker` job that builds and health-checks. Two observations:
- The lint step is unconditionally strict, so with 158 ruff errors **CI has never been green**.
- **Neither `ci.yml` nor `docker.yml` ever runs `scripts/smoke.sh`.** The workflow re-implements the
  health check inline against the Docker image. The project's own doctrine names `smoke.sh` as *the*
  gate, yet the gate is absent from the gate-runner. Its `/ws` 404 and its broken bare-`chronos`
  invocation are therefore invisible to CI.
- The Docker job's health check only hits `/api/health`, so the missing `websockets` dep — which
  breaks every WebSocket upgrade in the shipped image — passes CI cleanly.

---

## Summary by severity

**BLOCKER (4)**
1. `websockets` undeclared + uvicorn not `[standard]` → every `/ws` upgrade 404s in the real server. Reproduced live; route is registered, dep is the sole cause.
2. `pytest-asyncio` undeclared and no conftest → all 8 async tests in phase 3 fail; the entire WebSocket-auth surface has zero executed coverage.
3. `chronos --version` does not exist; version is 4-way divergent (pyproject 2.0.0 vs runtime 0.1.0). 2 phase-6 tests fail on it.
4. `scripts/smoke.sh` has never passed as invoked (`chronos: command not found`, plus missing `./data/`). Phase 3's done-criteria is unmet; its own test fails.

**HIGH (2)**
5. Ruff = 158 errors, hard gate at 0, and CI's lint step is strict — CI has never been green.
6. `mcp` used but undeclared → `create_mcp_server()` always ImportError in a stock install; not shipped as an optional extra.

**MEDIUM (3)**
7. 3 permanently-true `or True` assertions in phase 1 (lines 1662/1667/1672) — placeholder tests that verify nothing.
8. `chronos/__init__.py` missing → namespace package; `__file__ is None`, and non-editable installs (Docker) may not package it.
9. CI never runs `scripts/smoke.sh`; the Docker health check can't detect #1.

**LOW (3)**
10. Single 32k-insertion initial commit — no bisect history.
11. `pytest>=8.0` floor vs 9.1.1 in use; loose.
12. `pytest.skip("smoke.sh not found")` is a dead guard that would mask a deleted script.

**CLEAN**
- Secrets & safety (§4): `.env` and `*.db` excluded from both git and docker context; no real credential tracked; only `.env.example`, fully commented placeholders.
- No xfails anywhere → no stale-XPASS risk.
- Phase 6's `_spec_assert` is genuine; no vacuous-assert pattern there.
- Git tree contains no junk or large binaries.

**Verdict: the project's central claim — "a green unit suite is not a running app" — is
currently true in the worst way. The unit suite is NOT green, the smoke gate has never passed, and
the running app's WebSocket endpoint 404s every upgrade. Do not treat any phase as done.**
