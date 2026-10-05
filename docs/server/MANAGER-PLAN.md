# Manager plan — backend-only, test-first, 4-cap (2026-10-05)

Read order for manager agent: `START-HERE.md` → `API.md` (frozen) → `Chronos.md` → `decisions.md` → this file.

Max **4 agents at once**. Never exceed. Queue the rest.

## 0. Ownership — no two agents on the same file, ever

Each part = one file group, one owner. Dispatch prompt must contain: exact files owned, forbidden files, spec section, `API.md` section, verification command. Copy-paste this line into every dispatch:

> You own ONLY these files: <LIST>. Do NOT read/write any other part's files. Do NOT edit any test you did not write. If blocked, stop and report — do not touch another owner's files.

| Phase | Test owner files | Code owner files |
|---|---|---|
| 1 core | `tests/phase_1/*` | `chronos/contracts/`, `chronos/db/`, `chronos/core/` |
| 2 ai | `tests/phase_2/*` | `chronos/ai/` (no `cost.py` prices/cost_hook — removed) |
| 3 server | `tests/phase_3/*` | `chronos/api/`, `chronos/realtime/`, `scripts/smoke.sh` |
| 4 cli+mcp | `tests/phase_4/*` | `chronos/cli/`, `chronos/mcp/` (no `chronos/web/` — deleted) |
| 5 features | `tests/phase_5/*` | `chronos/notify/`, `chronos/db/search.py`, `chronos/db/audit.py`, `chronos/ai/briefings.py`, `stats.py`, `export.py` (no token-cost) |
| 6 deploy | `tests/phase_6/*` | `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `scripts/`, `.github/` |

## 1. Batch 1 — tests only (keep 4 busy, rolling queue)

Start [1,2,3,4]. The moment any test agent finishes + is stopped, immediately start next queued (5, then 6). Then the moment test capacity frees, start code agents for finished phases (e.g. 1,2) while tests 5,6 still run — never exceed 4 running. Keep 4 busy at all times; queue the rest. Code never touches a phase whose tests are not yet written.

> Write failing tests from spec/API.md text ONLY. Never read implementation. Cite spec § per test. No `or True`, no `any()`-of-one, no substring greps, no MagicMock for persistence, no `if result:` guards. Tests must be able to fail. When done, STOP. You will be stopped.

Gate: all 6 test suites exist. Do NOT start code until Batch 1 is stopped.

## 2. Batch 2 — code only (keep 4 busy, rolling queue)

Same rolling rule: as soon as a slot frees, start the next code agent [1,2,3,4,5,6] whose tests are done. Each code agent prompt includes ownership line +:

> Implement ONLY your files to make your phase tests pass. May NOT edit any test file. If test vs spec disagree, STOP and file ticket — do not fix the test.

Gate per phase: its own tests pass + `ruff check` on its files clean. Stop code agents when done.

## 3. Fix loop — never reuse failed agents

For each red phase:
1. Dispatch ONE fresh `analysis` agent (read-only): failing assertion verbatim, real output, file:line, spec citation, root cause (code wrong / test wrong / spec ambiguous). Max 300 lines report. Stop it.
2. Manager forwards ONLY that report (not full log) to ONE fresh `fix` agent owning the same files. Fix agent patches code OR (only with manager ruling) test.
3. Dispatch ONE fresh `verify` agent: runs that phase suite + imports. Pass → stop all three. Fail → repeat once, then escalate to user.

Never call back the original test/code agent for fixes. Never dump full logs into manager context — report only.

## 4. Incremental integrate (one phase at a time)

Only after each phase is green alone:
1. `1` alone → `1+2` → `1+2+3` → `+4` → `+5` → `+6`.
2. At each step: full suite + `./scripts/smoke.sh 8099` (venv path, throwaway DB).
3. Red at step N = bug in N or seam N-1/N. Fix via §3 loop, do not proceed.

## 5. Done

Phase done = own tests green + full suite green at its integrate step + smoke green. Project done = all 6 integrated + smoke green + `ruff check chronos tests` = 0.
