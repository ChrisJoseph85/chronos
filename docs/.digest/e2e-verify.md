# Chronos — independent end-to-end verification

Verifier: independent subagent, no prior context, no status document trusted.
All evidence below is my own observation, produced from a **fresh GitHub clone**.

---

## 1. Environment facts (observed)

| Fact | Observed value |
|---|---|
| Kernel | `Linux localhost 6.17.0-PRoot-Distro #1 SMP PREEMPT_DYNAMIC Fri, 10 Oct 2025 aarch64` |
| Arch | `aarch64` |
| OS | `Fedora Linux 44 (Container Image)`, `ID=fedora`, `VERSION_ID=44` |
| libc | `ldd (GNU libc) 2.43` |
| Python | `3.14.7` (single system python, `/usr/bin/python3`) |
| `uv` | present, `uv 0.12.19 (aarch64-unknown-linux-gnu)` |
| `docker` | **absent** (`which`/`command -v` exit 127 — no binary at all) |
| `proot-distro` | **absent** |
| `/data/data/com.termux` | does not exist — not Termux, not Android |

All guidance I was given about this container checked out. `which` itself is not
installed (coreutils `which` absent); I used `command -v` / direct invocation.
`.venv/bin/python -m pip` is the working invocation, as stated.

## 2. Clean clone

```
git clone https://github.com/ChrisJoseph85/chronos.git
→ /root/.hermes/cache/scratch/chronos-clean
HEAD = c7327624b4c26f81bf89b606fdc378168d3bedb9
       "Replace the Termux installers with one Termux-side script"
date = 2026-10-04 14:12:50 +0000
```

`diff -rq` against the existing `/root/Chronos` working tree (excluding `.git`,
`.venv`, caches, egg-info) reported **no differences**. There is no local drift;
the working tree equals what is published.

## 3. Fresh venv + install — SUCCEEDED

`python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'`

Exit 0. No dependency failures. Real tail of the successful install:

```
Successfully built chronos
Installing collected packages: sqlite-vec, websockets, typing-extensions, truststore,
ruff, rpds-py, python-multipart, pyjwt, pygments, pycparser, pluggy, packaging,
MarkupSafe, iniconfig, idna, h11, click, certifi, attrs, annotated-types,
annotated-doc, uvicorn, typing-inspection, sqlalchemy, referencing, pytest,
pydantic-core, opentelemetry-api, Mako, httpcore2, httpcore, cffi, anyio, starlette,
pytest-asyncio, pydantic, jsonschema-specifications, httpx2, httpx, cryptography,
argon2-cffi-bindings, alembic, sse-starlette, mcp-types, jsonschema, fastapi,
argon2-cffi, mcp, chronos

Successfully installed ... fastapi-0.142.2 uvicorn-0.54.0 sqlalchemy-2.1.3
alembic-1.20.0 argon2-cffi-25.1.0 httpx-0.28.1 python-multipart-0.0.32
websockets-17.2 mcp-2.3.0 sqlite-vec-0.1.9 chronos-2.0.0 pytest-9.1.1
pytest-asyncio-1.4.0 ruff-0.16.10
```

`sqlite-vec-0.1.9` installed from the manylinux aarch64 wheel — the
platform claim in `requirements-lock.txt` holds on this host.
`chronos --version` → `chronos 2.0.0`; `chronos.__version__` → `2.0.0`
(single-sourced, consistent with `pyproject.toml`).

## 4. Real server, real HTTP — CLAIMS VERIFIED

Booted from the clean clone:

```
CHRONOS_DB=/root/.hermes/cache/scratch/clean.db .venv/bin/chronos serve --port 8099 --host 127.0.0.1
```

```
INFO:     Started server process [30612]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8099
sqlite-vec version: v0.1.9
Instance key: 537bc81e4bdd60db2c358d23a93c5f17953a3a8d05325d1bf2069d4dbe2e1d91
WARNING: This key will not be shown again. Store it securely.
```

**Minor observation:** the key line is written by `print()` to stdout from inside
the ASGI startup hook while uvicorn's own logs go to stderr. It does appear, but
it is **block-buffered when stdout is a pipe/file** — it only became visible
after later requests flushed the buffer. Under `docker compose up -d` the key can
therefore be delayed or, if the process is killed before any flush, lost. Not a
functional break, but a real first-run UX hazard worth fixing with `flush=True`.

### 4a. `GET /api/health` — no key required. **VERIFIED**
```
$ curl -s http://127.0.0.1:8099/api/health
{"status":"ok","version":"2.0.0","db_path":"/root/.hermes/cache/scratch/clean.db","uptime_seconds":11.909700632095337}
HTTP=200
```
`status` is `ok`, sent with **no** `X-Chronos-Key` header. Health is the only
open route; every other route I probed returned 401.

### 4b. `POST /api/say` — real committed event. **VERIFIED**
```
$ curl -X POST /api/say -H "X-Chronos-Key: $K" -H 'Content-Type: application/json' \
    -d '{"text":"study chemistry tomorrow 4pm for 45 minutes"}'
{"intent":"schedule","tool_calls":[{"tool_name":"create_event","arguments":{"title":"Study Chemistry",
"start_ms":1791216000000,"end_ms":1791218700000}}],"proposal_id":null,"committed":true,
"events":[{"id":"96d31616-ee0d-4958-8307-6b3cffe1584d","title":"Study Chemistry",
"start_ms":1791216000000,"end_ms":1791218700000,"kind":"focus",...}],"message":"Committed 1 change(s)."}
HTTP=200
```
The built-in offline parser (no LLM key configured) correctly resolved
`tomorrow` / `4pm` / `45 minutes`. `committed:true`.

### 4c. Genuinely persisted — read back with stdlib `sqlite3`. **VERIFIED**
Independent script, separate process, direct DB access (no API):

```
row count: 1
{"id":"96d31616-ee0d-4958-8307-6b3cffe1584d","title":"Study Chemistry",
 "start_ms":1791216000000,"end_ms":1791218700000,"kind":"focus","SOFT_DELETED":0,
 "created_at":1791123966759,"node_id":null,"bucket_id":null,...}

Study Chemistry  2026-10-05T16:00:00+00:00 -> 2026-10-05T16:45:00+00:00  (45 min)  kind=focus

timer_sessions: {'id':'2fa9b1c1-...','label':'chem','started_at':1791123994590,
                 'ended_at':None,'mode':'stopwatch','source':'cli'}

PRAGMA integrity_check -> ok
PRAGMA journal_mode  -> wal
```
Title, date (tomorrow = 2026-10-05), 16:00 start, and the **exactly 45-minute**
duration all round-tripped correctly out of band. Durations and calendar math are
right.

### 4d. Timer start, then 409 on a second start. **VERIFIED**
```
$ ... -d '{"label":"chem","mode":"stopwatch","source":"cli"}'
{"id":"2fa9b1c1-9f23-431d-8fff-6427dd5dd932","node_id":null,"label":"chem",
 "started_at":1791123994590,"ended_at":null,"source":"cli","reconciled":false,
 "mode":"stopwatch","target_ms":null,"phase":null,"cycle":"1"}
HTTP=200

$ ... -d '{"label":"second","mode":"stopwatch","source":"cli"}'
{"detail":"A timer is already running. Stop it first."}
HTTP=409
```
Concurrency guard is real, enforced server-side in SQL
(`WHERE ended_at IS NULL`), not client-side. Note `label`, `mode`, `source` are
**required** fields — an empty `{}` body yields 422, not 400.

### 4e. Missing key → 401, invalid key → 401. **VERIFIED**
```
POST /api/say, no header        -> {"detail":"Missing instance key"}   HTTP=401
GET  /api/timer, wrong key      -> {"detail":"Invalid instance key"}   HTTP=401
```
Auth is Argon2id (`time_cost=2, memory_cost=65536, parallelism=1`); the key is
stored only as a hash and the plaintext is unrecoverable from the DB. Log
redaction for `?key=` and `X-Chronos-Key` is installed at the root logger.

**Security note (not a functional failure):** the key is accepted as a `?key=`
query parameter. That is the documented fallback, but query strings land in
proxy logs, browser history, and `Referer` headers. The code's own redaction
covers *its* logs; it cannot cover an intermediary's.

## 5. Clean shutdown — **VERIFIED**
```
server pid from log: 30612
exited after 2s on SIGTERM
--- port probe ---   connection refused / port closed
--- /proc scan ---    no chronos/uvicorn processes remain
INFO:     Shutting down / Application shutdown complete. / Finished server process [30612]
```
Graceful, no orphans, no listener left on 8099.

## 6. Dockerfile coherence — static check only, **build UNVERIFIED**

Every `COPY` source was checked to exist in the clean clone:

| COPY source | exists in clone |
|---|---|
| `pyproject.toml` | yes |
| `README.md` | yes |
| `chronos/` | yes |
| `/usr/local/lib/python3.14/site-packages` (from builder) | produced by `pip install .` |
| `/usr/local/bin/chronos` (from builder) | produced by `pip install .` (console script) |

The Dockerfile is **coherent on this point** — it copies only `pyproject.toml`,
`README.md`, and `chronos/`, all of which are present, and it deliberately
excludes `tests/` and `docs/`. Note `pyproject.toml` has `readme = "README.md"`,
so both files are genuinely required; that requirement is satisfied.

`.dockerignore` excludes `tests/`, `docs/`, `scripts/`, `.github/` — all of which
the Dockerfile does **not** need, so there is no exclusion/requirement conflict.

`.dockerignore` also excludes `.env`, so the compose `env_file: .env` is a
host-side runtime input only, which is correct.

`docker-compose.yml` builds `.`, maps 8080, and sets `CHRONOS_DB=/data/chronos.db`
with a `chronos-data` volume — coherent with the image's `VOLUME ["/data"]` and
`ENV CHRONOS_DB=/data/chronos.db`.

> **I could not run `docker build`.** No docker binary exists on this host
> (command not found). So: *the Dockerfile's COPY references are all satisfiable
> and the file is internally consistent, but the build itself is unverified.*
> Specifically unverified: that `python:3.14.7-slim-bookworm` exists and resolves,
> that `sqlite-vec`'s manylinux aarch64/glibc wheel is ABI-compatible against that
> base image, and that the HEALTHCHECK's `/api/health` probe passes inside the
> container. (The probe itself I *did* verify functionally — it answers 200 without
> a key.)

## 7. README quickstart vs. actual code — TWO REAL DEFECTS

The core instructions work. `.venv/bin/python -m venv .venv`,
`.venv/bin/pip install -e .`, `.venv/bin/chronos serve --port 8080`,
`chronos --version` → `2.0.0`, `curl http://127.0.0.1:8080/api/health`, and the
Docker/serve flow all match reality. But:

### DEFECT 1 — README references a script that does not exist (BLOCKER for the Termux path)
README lines 46–47 tell the user to run:
```bash
bash scripts/termux.sh install
bash scripts/termux.sh start
```
**`scripts/termux.sh` does not exist.** The published `scripts/` directory
contains only: `backup.sh`, `install.sh`, `restore.sh`, `smoke.sh`.

This is confirmed by the project's own test suite, which is the loudest
consequence:
```
FAILED tests/phase_6/test_deploy_spec.py::TestTermuxScript::test_termux_sh_exists
E   AssertionError: [REAL BUG] scripts/termux.sh not found
...
19 FAILED in tests/phase_6/test_deploy_spec.py   (all with FileNotFoundError)
```
The HEAD commit `c732762` is literally titled *"Replace the Termux installers
with one Termux-side script"* and folded them into `scripts/install.sh` — but the
README was **not updated**. `git log --oneline -- README.md` shows README's last
touch is the *earlier* commit `1c597cb`. So the README documents a file that the
latest commit deleted. A user following the Termux quickstart gets an immediate
`No such file or directory`.

### DEFECT 2 — `chronos key-renew` cannot recover a lost key (BLOCKER for the documented recovery path)
README: *"If you lose it, `chronos key-renew` issues a new one."*

Observed:
```
$ chronos key-renew
Error: key file not found. Run `chronos serve` first.
key-renew exit=1
```
Root cause: `key_renew` (`chronos/cli/commands.py:88`) gates on
`Path.home()/".chronos"/"key"` existing and returns 1 if not. But
`chronos serve` → `create_app` (`chronos/api/app.py:142-149`) generates the key,
stores only the Argon2 hash in SQLite, and **prints it — it never writes the key
file.** Confirmed: `/root/.chronos/key` does not exist after a full server
lifecycle, and `grep` finds no write to that path anywhere in `app.py`.

So the key file is written *only* by `key-renew`, which itself refuses to run
without it. The documented "if you lose it" recovery path is unreachable. This is
also what fails the packaging tests:
```
FAILED ...::TestPackaging::test_chronos_on_path
FAILED ...::TestPackaging::test_version_single_sourced
```

### Stale README claim
README line 143: **"This repository is docs-only right now."** — false. The repo
ships a complete, installable, running application. That paragraph (and the
Manager/phase-4-agent framing beneath it) describes a build that has since
landed; it should be deleted.

### README dev-gate claim, verified with a caveat
README: *"A green unit suite is not a running app — `smoke.sh` is the gate."*
`./scripts/smoke.sh 8099` exits **0** and prints `healthy` — but **only if
`chronos` is on `PATH`**. Invoked as the README shows (`./scripts/smoke.sh 8099`
after `pip install -e .`), it fails:
```
./scripts/smoke.sh: line 12: chronos: command not found
did not become healthy
SMOKE_EXIT=1
```
With `PATH="$PWD/.venv/bin:$PATH"` it passes. `pip install -e .` puts the console
script in `.venv/bin`, which is not on `PATH` — so the documented invocation of
the documented gate is broken; `smoke.sh` should resolve the venv explicitly.
The same missing-`PATH` issue causes the
`tests/phase_3/...::TestSmokeScript::test_smoke_script_boots_server` failure
(`subprocess.TimeoutExpired` after 30s).

## 8. Test suite on the published HEAD — NOT GREEN

`pytest tests -q` from the clean clone:
```
38 failed, 708 passed, 2 skipped, 281 warnings in 180.69s
```
Grouped by file:

| File | Failures | Cause |
|---|---|---|
| `tests/phase_6/test_deploy_spec.py` | 19 | `scripts/termux.sh` missing (Defect 1); `chronos` not on PATH |
| `tests/phase_3/test_server_spec.py` | 10 | mostly test-harness bugs, see below |
| `tests/phase_4/test_interfaces_spec.py` | 7 | — |
| `tests/phase_1/test_contracts_spec.py` | 2 | real product bugs, see below |

**Two of these are real product defects, not test noise:**

1. **Week buckets overrun their parent month.** 103 of 4295 seeded buckets fall
   outside their parent's `[start_ms, end_ms]`:
   ```
   AssertionError: 103 of 4295 buckets fall outside their parent's window;
   e.g. ['W:2026-W05','W:2026-W09','W:2026-W14','W:2026-W18','W:2026-W27'].
   The week end is computed as week_start + 6 days, which is the following
   Monday 00:00 rather than Sunday 23:59:59.999.
   ```
   Confirmed by the test's own diagnosis. Off-by-one/week boundary bug in
   `BUCKET_SEED_SPEC` week generation.

2. **Bucket seed counts wrong by 2.**
   ```
   {'year': 10, 'month': 120, 'week': 523, 'day': 3652, 'total': 4305}
   != {'year': 10, 'month': 120, 'week': 522, 'day': 3653, 'total': 4303}
   ```
   2026 is not a leap year, so `day` should be 365, not 3653 — the expected-count
   constant and the actual generator disagree, and the week/day split is
   transposed by one.

**The other 10 in `phase_3` are test-harness defects, not product bugs.** The
product behaves correctly — my live HTTP probes prove the 401/409/200 paths work.
The tests fail because the harness, not the code, is wrong:
- `argon2.exceptions.InvalidHashError` escaping as `AttributeError:
  'InvalidHashError' object has no attribute 'status_code'` — tests install a
  non-Argon2 stub hash, and `require_key` only catches `VerifyMismatchError`, not
  `InvalidHash`. Arguably worth hardening in `verify_instance_key`, but no live
  request is affected.
- `_IncludedRouter` object has no attribute `path` — a FastAPI introspection
  helper that breaks on newer Starlette.
- `test_voice_no_audio_returns_400` — `assert 422 == 400`; the route returns 422
  from pydantic validation rather than 400. Arguably correct FastAPI behaviour;
  the test asserts a stricter contract.

`ruff check chronos tests` → **176 errors** (79 auto-fixable). Lint is not clean.

## 9. Verdict

**The application genuinely works.** I did not take anyone's word for it: I
cloned fresh, installed into a fresh venv, booted the real server, exercised the
real API over HTTP with the real printed key, and read the committed row back out
of SQLite with a separate process. All six API claims in the task are confirmed
with verbatim responses. Scheduling, auth, timer-exclusivity, persistence, and
graceful shutdown all work correctly, offline (no LLM key needed), on
aarch64/Fedora/glibc.

**But the repository is not release-ready.** Two documented user paths are
broken: the Termux quickstart names a deleted script, and the documented key
recovery command can never run. The README also still calls the repo docs-only.
The test suite is red (38) with two genuine bucket/calendar bugs, and lint has
176 errors. The Dockerfile is coherent on inspection but its build is unverified
here.

## 10. Claims I could NOT verify

| Claim | Why not |
|---|---|
| `docker build` succeeds | No docker binary on this host — not installed at all |
| `docker compose up --build -d` works | Same |
| HEALTHCHECK passes *inside* the container | No container runtime |
| Image base `python:3.14.7-slim-bookworm` resolves | Cannot pull images without a daemon |
| sqlite-vec wheel ABI-compat against slim-bookworm | No container; verified only against this host's glibc 2.43 |
| Any Termux / Android / proot-distro path | Not Termux, no proot-distro binary, no `/data/data/com.termux` |
| The HUD web UI at `http://localhost:8080` renders | `chronos.web.mount_hud` was mounted during my boot but I only exercised JSON routes over HTTP; no browser/visual check |
| LLM-provider paths (Groq/NIM), STT, MCP server, ntfy notifications | No provider API keys configured; only the offline parser path was exercised |
| `scripts/install.sh` end-to-end | Would mutate this host and needs proot-distro, which is absent |
| Windows / macOS targets | Wrong platform |
| Whether remote HEAD has moved past `c732762` | I verified `c732762` at clone time; the other agent is pushing, so the remote may advance |

I did **not** run any git push/add/commit/checkout/reset, and made no edits
inside `/root/Chronos`. All work was confined to
`/root/.hermes/cache/scratch/`.