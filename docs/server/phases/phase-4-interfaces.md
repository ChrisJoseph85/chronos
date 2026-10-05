# Phase 4 — Interfaces (cli, mcp) — backend-only, no web

**2026-10-05 decision: web HUD removed.** Parts 4.1-4.3 deleted. This phase owns CLI + MCP only, both thin clients of the frozen REST + WS API.

**Runs in parallel with phases 1–3, 5, 6.** Both are clients of the REST and
WebSocket API, so they can be written against the frozen route list in phase 3's
doc before that phase's code exists.

Spec: `docs/Chronos.md` §9.2 (CLI), §8.4 (MCP), §3 (auth).

---

## Parts

| Part | Files | Owner |
|---|---|---|
| 4.4 CLI | `chronos/cli/` | one code agent |
| 4.5 MCP | `chronos/mcp/` | one code agent |

4.4 and 4.5 are independent.

---

## Behaviour the tests must pin

**Web HUD removed 2026-10-05 — no HUD behaviour, no HUD tests.**

**CLI (§9.2)**
```
chronos serve | key-renew | db-upgrade | token-cost | export
echo "schedule DB review tomorrow 4pm for 45 mins" | chronos say -
chronos get day | timer | briefing
```
- Terse output, no prompts, safe to pipe.
- **Every command must actually run.** v1 shipped four of seven that had never
  executed successfully, because the tests only checked that the commands were
  *registered*. Test that each command runs and produces output.
- `serve` must resolve the app factory `chronos.api.create_app` and pass `--db`
  through to it, or the app opens a different file than `--db` names.
- `db-upgrade` must invoke alembic through the current interpreter, not a PATH
  lookup, and the migration must load the sqlite-vec extension (the schema creates
  a `vec0` virtual table) and honour `CHRONOS_DB`.

**MCP (§8.4)**
- Exposes the **same tool set** as the pipeline. Do not reimplement the tools —
  adapt to an injected executor.
- Authenticated with the instance key, header with a query-string fallback.
- Agents can query ("am I free tomorrow evening?") and act ("book me the dentist
  tomorrow") with the same validation the user's voice input receives.
- Every call is audited.

---

## Done means

- [ ] **every CLI command in §9.2 runs and produces real output**
- [ ] `serve` finds the factory and forwards `--db`
- [ ] `db-upgrade` completes and creates the schema in the `CHRONOS_DB` file
- [ ] the MCP tool list matches the contracts exactly; no tool stubbed
- [ ] unauthenticated MCP calls are rejected; every call is audited
- [ ] full suite green
- [ ] per-part scratch tests and probe scripts deleted; the phase's spec tests kept
      (`manager.md` §10)

---

## Verification

```bash
.venv/bin/python -m pytest tests/phase_4 -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check chronos tests

# run the commands, do not just import them
.venv/bin/python -m chronos.cli --help
CHRONOS_DB=/tmp/cli.db .venv/bin/python -m chronos.cli key-renew
CHRONOS_DB=/tmp/cli.db .venv/bin/python -m chronos.cli token-cost
CHRONOS_DB=/tmp/cli.db .venv/bin/python -m chronos.cli get timer
```
