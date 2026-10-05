# Escalation tickets — the format

Every disagreement between a Test agent and a Code agent travels up **one rung at
a time**, as a written ticket. Nothing skips a rung. **No agent contacts the
Manager directly except a Proposer.**

Copy this template. Fill every field. A ticket with a blank field is not a
conflict yet — it is an unfinished attempt at resolution, and it gets sent back.

---

```
TICKET — phase <n>, part <n.m>
Rung: <proposer | mediator | vote | manager>

1. DISPUTED (one sentence)
   <what the disagreement is, in a single sentence — not a narrative>

2. POSITIONS
   Test agent asserts: <claim>   [spec: §<n>]
   Code agent asserts: <claim>   [spec: §<n>]

3. ALREADY TRIED
   <which rungs below were climbed, what was said, why it did not settle it>
   A ticket with nothing here is sent straight back down.

4. EVIDENCE
   Failing assertion: <the exact assertion, verbatim>
   Real output:       <the actual command output — not a summary>
   Location:          <file>:<line>

5. MY READING
   <the raiser's own view, and why — the receiver is allowed to disagree>
```

---

## What happens at each rung

**Rung 1 — Proposer.** The default destination for every ticket. Most are settled
here by clarifying the interface proposal. The Proposer is expected to absorb the
large majority of disagreements.

**Rung 2 — Mediator.** Only if the Proposer cannot settle it. The Mediator rules
code-wrong or test-wrong. Its ruling is **binding** on both agents.

**Rung 3 — Vote.** Only if the Proposer and Mediator disagree with each other. All
four agents of the phase vote. **3:1 carries.**

**Rung 4 — Proposer rethinks.** Special case: if the Test agent and the Code agent
**independently** agree that something is majorly wrong, the fault is likely in the
*proposal itself*. The Proposer stops, rethinks, and **gets confirmation from the
Manager** before work continues. This is the only time a Proposer escalates without
a 2:2.

**Rung 5 — Manager.** On a 2:2, or a failed rethink. The Manager resolves it, or
forwards it to the user when it turns on product intent rather than correctness.

---

## Rules

- **One rung at a time.** A ticket raised two levels up is refused and sent back.
- **No agent weakens an assertion** to make a suite pass. Not at any rung.
- **No agent edits a test** it did not write, except under a Mediator ruling.
- **The Manager's ruling is final.** Record it in `docs/decisions.md`.
- If the **spec itself is ambiguous**, say so explicitly and escalate — do not
  guess, and do not let a majority vote invent product intent. That goes to the
  user.

---

```
TICKET — phase 2, part 5.3
Rung: proposer

1. DISPUTED (one sentence)
   tests/phase_2/test_intent_verify_spec.py pins NOW_MS = 1785288000000 with comment "2026-08-04T12:00:00Z", but that number decodes to 2026-07-29T01:20:00Z, so test_verify_pass_corrects_dates_offsets_slots expects "tomorrow" = 2026-08-05, six days after the now_ms it passes in.

2. POSITIONS
   Test agent asserts: verify_calls("Schedule math review tomorrow at 4pm for 45 minutes", proposed start 2026-08-06, now_ms=1785288000000) must return start "2026-08-05T16:00:00+00:00", end "2026-08-05T16:45:00+00:00"   [spec: §5.3]
   Code agent asserts: "tomorrow" resolved against the passed now_ms (2026-07-29T01:20Z) is 2026-07-30, so the expected 2026-08-05 is unreachable under any correct reading of §5.3; the test's numeric NOW_MS contradicts its own comment and expectation   [spec: §5.3]

3. ALREADY TRIED
   Rung 0 (self-check): verified decode with `datetime.fromtimestamp(1785288000000/1000, tz=utc)` → 2026-07-29T01:20:00+00:00; 2026-08-04T12:00:00Z would be 1785844800000. Code produces exactly the expected output when now_ms is the commented date (Aug 4 → tomorrow Aug 5 16:00 + 45 min). No code-side fix exists that is both spec-correct and passes: hardcoding 2026-08-05 would violate §5.3 ("audits against the user's actual words"). Cannot edit the test (not my file).

4. EVIDENCE
   Failing assertion: `assert args["start"] == "2026-08-05T16:00:00+00:00"`
   Real output: `AssertionError: ... wrong date must be corrected, got '2026-07-30T16:00:00+00:00'`
   Location: tests/phase_2/test_intent_verify_spec.py:164

5. MY READING
   Test-wrong: single wrong constant. Test author's comment and expected values agree with each other (now = Aug 4, tomorrow = Aug 5); only the numeric NOW_MS is off by ~6.4 days. Request Mediator ruling to correct NOW_MS to 1785844800000 (or correct the expectation to 2026-07-30). Code implementation is spec-correct as-is; 67/68 phase-2 tests pass.
```
