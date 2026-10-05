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
