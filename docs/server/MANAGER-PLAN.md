# Manager plan — backend-only, test-first, 4-cap (2026-10-05)

> Amended 2026-10-05 (phases combined, old phase docs superseded by phases/phase-1-foundation.md).

Read order for manager agent: `START-HERE.md` → `API.md` (frozen) → `Chronos.md` → `decisions.md` → this file.

Max **4 agents at once** for future work. Never exceed. Queue the rest.

## 0. Ownership — no two agents on the same file, ever

Each part = one file group, one owner. Dispatch prompt must contain: exact files owned, forbidden files, spec section, `API.md` section, verification command. Copy-paste this line into every dispatch:

> You own ONLY these files: <LIST>. Do NOT read/write any other part's files. Do NOT edit any test you did not write. If blocked, stop and report — do not touch another owner's files.

Single-phase reality: one suite `tests/phase_1/*` — prefixes `test_*` core, `test_ai_*`, `test_srv_*`, `test_if_*`, `test_feat_*`, `test_ops_*`, plus fixers' `test_*_fixes_spec.py`. Test-author≠implementer: code agents may NEVER edit any test file.

Code ownership per directory:

| Code files | Owner |
|---|---|
| `chronos/contracts/`, `chronos/db/`, `chronos/core/` | foundation-data |
| `chronos/ai/` except `briefings.py`, `stats.py`, `export.py` | foundation-ai |
| `chronos/api/`, `chronos/realtime/`, `scripts/smoke.sh` | server |
| `chronos/cli/`, `chronos/mcp/` | interfaces |
| `chronos/notify/`, `chronos/db/search.py`, `chronos/db/audit.py`, `chronos/ai/briefings.py`, `stats.py`, `export.py` | features |
| `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `scripts/`, `.github/` | deploy |

## 1. Tests first, then code (single phase)

Tests from spec/API.md text ONLY. Never read implementation. Cite spec § per test. No `or True`, no `any()`-of-one, no substring greps, no MagicMock for persistence, no `if result:` guards. Tests must be able to fail. Code never starts until its tests are written and stopped.

Code agents: implement ONLY owned files to make owned tests pass. May NOT edit any test file. If test vs spec disagree, STOP and file ticket — do not fix the test.

## 2. Fix loop — never reuse failed agents

For each red area:
1. Dispatch ONE fresh `analysis` agent (read-only): failing assertion verbatim, real output, file:line, spec citation, root cause (code wrong / test wrong / spec ambiguous). Max 300 lines report. Stop it.
2. Manager forwards ONLY that report (not full log) to ONE fresh `fix` agent owning the same files. Fix agent patches code OR (only with manager ruling) test.
3. Dispatch ONE fresh `verify` agent: runs that suite + imports. Pass → stop all three. Fail → repeat once, then escalate to user.

Never call back the original test/code agent for fixes. Never dump full logs into manager context — report only.

## 3. Integrate

Full suite + `./scripts/smoke.sh 8099` (venv path, throwaway DB) is the smoke gate. `ruff check` on touched files is the lint gate. Red = bug in the touched area or a seam. Fix via §2 loop, do not proceed while red.

## 4. Done

Done = full suite green + smoke green + `ruff check chronos tests` = 0.
