# Chronos — build architecture (v2)

**This document defines how the project is built. `docs/Chronos.md` defines what
is built.** Read both before starting. If they conflict, `Chronos.md` wins on
*product* and this file wins on *process*.

---

## 1. What changed from v1

v1 was built phase-by-phase, sequentially: foundation, then leaves, then
integration, then AI, then clients, then ops. That serialised the work — nothing
could start until the phase before it landed — and it hid defects behind a green
suite (see §7).

v2 builds **all six phases in parallel**, against an interface that is frozen
before any phase begins. The cost is that the interface must be right up front.
The benefit is that the whole project moves at once, and every phase is
independently testable from the day it starts.

---

## 2. Phase 0 — the interface freeze (must complete first)

Parallelism is only safe if everyone builds against the same frozen surface.
Before any phase starts, this must exist and be committed:

- `chronos/contracts/` — every model, enum, Protocol and tool schema. This is the
  **only** shared surface. Changing it later is a deliberate, announced act that
  lands on every caller.
- The database schema (DDL for every table in `Chronos.md` §4) plus the bucket
  seed.
- `docs/phases/phase-*.md` — every phase's spec, already written (they are).

**Phase 0 is owned by the Manager and the Phase-1 Proposer together.** It is
small and must not take long. When `contracts/` is committed and tagged, Phase 0
is done and all six phases start.

> If a phase later discovers the frozen interface is wrong, it does **not** change
> it silently. It raises a conflict (§5) and the Manager rules.

---

## 3. The six phases (all parallel)

| Phase | Owns | Doc |
|---|---|---|
| 1 | contracts, db, core scheduling | `phases/phase-1-core.md` |
| 2 | ai providers, pipeline, intent, verify, packer | `phases/phase-2-ai.md` |
| 3 | api, realtime, auth | `phases/phase-3-server.md` |
| 4 | cli, mcp (web removed 2026-10-05) | `phases/phase-4-interfaces.md` |
| 5 | notify, briefings, stats, search, audit, export | `phases/phase-5-features.md` |
| 6 | deployment: Termux, Docker, packaging, CI | `phases/phase-6-deploy.md` |

Each phase is subdivided into **parts**. A part is the unit of work: one part is
one file or one tightly-related file group, owned by exactly one code agent.
Phase docs list their parts explicitly.

**Android is not a phase.** It lives in `docs/experimental/android.md` and is
excluded from the build. Do not build it, do not test it, do not schedule agents
for it.

---

## 4. The agent hierarchy

Five roles. **No agent ever holds two roles.**

```
                          ┌─────────────┐
                          │   MANAGER   │  ← one, for the whole project
                          └──────┬──────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
        ┌─────▼─────┐      ┌─────▼─────┐      ┌─────▼─────┐
        │ PROPOSER  │      │ PROPOSER  │  ... │ PROPOSER  │  ← one per phase
        │  phase 1  │      │  phase 2  │      │  phase 6  │
        └─────┬─────┘      └─────┬─────┘      └─────┬─────┘
              │                  │                  │
        ┌─────┴─────┐      ┌─────┴─────┐      ┌─────┴─────┐
        │           │      │           │      │           │
   ┌────▼───┐  ┌────▼───┐  ...                    ...
   │ TEST   │  │ CODE   │
   │ agent  │  │ agent  │
   └────────┘  └────────┘
                    ↑
              ┌─────┴──────┐
              │  MEDIATOR  │  ← one per phase, called only on conflict
              └────────────┘
```

### Manager (one for the whole project)

Reads `docs/manager.md` and this file. Owns the schedule, not the code.

- Keeps **at most 4 agents running at any moment** (§6). This is a hard limit.
- Dispatches each phase's Proposer and hands it its phase doc.
- Receives escalations from Proposers and Mediators (§5).
- Decides every escalated conflict: resolve it, or forward it to the user.
- Verifies every claimed result with real command output before accepting it
  (§7). Never accepts a subagent's report as fact.
- Commits and tags at checkpoints. Uses explicit paths — never `git add -a`.
- **Never blocks on the user.** Defers the question to `docs/questions-for-user.md`,
  takes the recommended default, and keeps building (see `manager.md` §8).
- **Kills agents early.** A looping or finished agent is stopped at once — it is
  burning tokens for nothing (see `manager.md` §9).

### Proposer (one per phase)

Reads its phase doc and the frozen `contracts/`. Owns the phase's interface.

- Writes the **interface proposal** for its phase: every file, every public
  function/class name, its signature, and its logic in prose — before any code
  is written. This is the deliverable that unblocks both agents below it.
- Manages its **Test agent** and its **Code agent** directly. They report to the
  Proposer, not to the Manager.
- First line of conflict resolution (§5).
- Reports to the Manager: what changed, the real verification output, what was
  deliberately not done.

### Test agent (one per phase, may be more than one for a large phase)

- Reads the **spec text only** — never the implementation. Writing tests from the
  code tests "does the code do what the code does", which always passes and
  catches nothing.
- Writes `tests/phase_<n>/test_<module>_spec.py` from the spec, and cites the
  spec section in each test.
- Writes **the test first**, then runs it. Failures are expected and are the
  deliverable at this stage.
- Tags every failure: `REAL BUG` / `SPEC AMBIGUITY` / `MY TEST WRONG`.
- **Never** weakens an assertion to make a suite pass.
- Once a part is verified, the per-part scratch tests and probe scripts are
  **deleted** — the phase's spec tests are the permanent record. See
  `manager.md` §10.

### Code agent (one per part, so a phase has as many as it has parts)

- Receives the frozen interface from the Proposer and the spec section.
- Writes the code to satisfy the tests. **May not edit any test file.**
- If a test and the spec disagree, stops and raises a conflict (§5) — it does not
  "fix" the test.
- One part, one owner. Never two agents in one file.

### Mediator (one per phase)

- Called **only** when the Proposer cannot settle a disagreement between the Test
  agent and the Code agent.
- Reads the spec, the failing test and the code, and rules which side is wrong:
  fix the code, or the test asserts a bug and must be corrected.
- **May not weaken an assertion to make a suite pass.**
- If the spec itself is ambiguous, says so and escalates — it does not guess.

---

## 5. Conflict resolution — the ladder

Every disagreement climbs this ladder. It stops at the first rung that resolves it.
**Nothing skips a rung.**

### The escalation discipline (read this twice)

**No agent ever contacts the Manager directly.** Not the Test agent, not the Code
agent, not the Mediator. Every disagreement goes up exactly one level — to the
**Proposer** — and only the Proposer may carry it further.

The Manager's attention is the most expensive resource in the build. It is spent
on scheduling, verification and final rulings, not on questions a Proposer should
have settled. An agent that "just flies over" to the Manager has broken the
process, and the Manager should refuse the escalation and send it back down.

Think of it as a ticket queue, not a chat. A ticket is raised to your direct
superior. Only a superior escalates.

### The ladder

1. **Proposer** tries to resolve it. Most conflicts die here: usually the
   interface proposal was unclear, and clarifying it fixes both sides. The
   Proposer is the first and busiest rung — it should absorb the large majority of
   disagreements without anything reaching the Mediator.

2. **Mediator** is called. It rules: code wrong, or test wrong. Its ruling is
   binding on the Test and Code agents.

3. **Vote** — if the Proposer and Mediator disagree with each other, all four
   agents of that phase (Test, Code, Proposer, Mediator) vote. **A 3:1 majority
   carries.** This exists so one stubborn agent cannot deadlock a phase.

4. **Both agents flag a major fault → the Proposer rethinks.** If the Test agent
   and the Code agent **independently** report that something is majorly wrong —
   they agree with each other, against the plan — that is a strong signal that the
   *proposal itself* is wrong, not the implementation. In that case the Proposer
   must **stop, rethink its own proposal**, and **get confirmation from the
   Manager** before any further work proceeds. This is the one situation where the
   Proposer escalates of its own accord, without a 2:2.

5. **Manager** — if there is no 3:1 majority (i.e. 2:2), or a rethink fails to
   produce agreement, the Proposer escalates to the Manager. The Manager either:
   - **resolves it** and rules, or
   - **forwards it to the user** when it turns on product intent rather than
     correctness — anything a reasonable person could want either way.

The Manager's decision is final. Record every escalated conflict, its ruling and
the reasoning in `docs/decisions.md`, so the next session does not relitigate it.

### How a ticket is written

Every escalation, at every rung, carries the same four things:

1. **What is disputed** — one sentence, not a narrative.
2. **The two positions** — what the Test agent asserts and what the Code agent
   asserts, each with its spec citation.
3. **What has already been tried** — which rungs below were climbed and why they
   did not settle it. A ticket with no "already tried" is sent straight back down.
4. **The evidence** — the failing assertion, the real output, the file and line.

A ticket missing any of these is not a conflict yet; it is an unfinished attempt
at resolution. The full template is in `docs/tickets.md` — copy it, fill every
field, raise it one rung at a time.

---

## 6. Scheduling — the 4-agent limit

**At most four agents run at any moment.** This is a hard ceiling, not a target.

The Manager schedules. Concretely:

- One slot is normally the Manager's own work (verification, commits).
- A phase in its *proposal* stage needs 1 agent (its Proposer).
- A phase in its *build* stage needs 2 agents (its Test agent and its Code agent),
  plus the Mediator if called.
- Therefore roughly **two phases build at once**, or more if some are still in
  their proposal stage.

Priority when slots are scarce, highest first:

1. A **blocked** phase — one whose agents cannot proceed without a ruling.
2. A phase that is **finishing** — landing a part costs one slot and frees the
   work permanently.
3. A phase in its **proposal** stage — cheap, and unblocks two agents later.
4. A phase that is **starting fresh** — lowest priority, because nothing depends
   on it yet.

Never exceed four. If four are running and a fifth task is ready, it waits. A
scheduler that overruns the limit is slower in the end, because the Manager
cannot verify what it cannot track.

---

## 7. Verification — the Manager's non-delegable duty

**A subagent reporting success is a claim, not a fact.** In v1 this rule caught a
regression reported as "pre-existing", a "21 passed" that failed when re-run, and
tests quietly edited to match a buggy stub. Four defects reached merged commits
in v1 because a test asserted the bug as correct.

Before accepting any result, the Manager:

1. **Reads the actual diff.** Not the summary.
2. **Runs the tests itself**, and pastes the real output into its report.
3. **Runs the full suite**, not just the phase's tests — a fix that breaks another
   phase is not a fix.
4. **Checks whether any test asserts a surprising value.** That may be the bug,
   written down as correct. If it looks wrong, say so — do not adjust the test to
   match the code.
5. **Runs the smoke test** (`scripts/smoke.sh`) once the server can boot. A green
   unit suite is not a running app.

A partial part that is honestly described is useful. A part reported as complete
that is not sends the next agent to the wrong place.

---

## 8. Definition of done

A **part** is done when its tests pass, the full suite passes, and the Manager has
seen the real output.

A **phase** is done when every part is done and its public surface matches its
phase doc.

The **project** is done when all six phases are done, `scripts/smoke.sh` passes on
a real boot, and `docs/Chronos.md` §13's coverage list is satisfied.

---

## 9. Rules that do not bend

- `chronos/contracts/` is the only shared surface. Modules import from it and
  nothing else. It is frozen after Phase 0.
- `chronos/core/` is pure: no db, no framework, no sibling imports.
- One part, one owner. Never two agents in one file.
- `git add` explicit paths. Never `git add -a` — it has already stolen a parallel
  agent's untracked work once.
- Never commit a secret. `.env` is never committed.
- No agent writes both the code and its tests.
- No agent weakens an assertion to make a suite pass.
- At most four agents at a time.
- A test that fails is information. Fix the code or explain the test — never
  silently edit the expectation.
