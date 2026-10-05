# Scheduling behaviour — buckets, proposals, and when the AI asks

**Written:** 2026-10-03 from the user's description, by the previous Manager.
**Not project-authoritative — `docs/Chronos.md` wins.**

This is the behaviour that was missing, and its absence is why the product felt
broken even though `/api/say` returned a sensible-looking proposal.

---

## 1. The core loop, as described by the user

> The AI puts something in a bucket, and decides **when** to ask the user.
> Suppose it puts it in a **day** bucket. If the user didn't say when it has to
> happen, the AI picks a time for a **clarification** — and the user has to
> click, answer, or ignore. If the user comes back later, it is **the first
> thing they see**: the bar.

So:

1. User says a sentence, typed or spoken.
2. AI parses it into a task and files it into a **time bucket** — Y / M / W / D.
3. AI decides whether the sentence carried enough time information.
   - **Enough** → propose a concrete slot. Commit on accept.
   - **Not enough** → propose a slot **and** ask a clarifying question.
4. The proposal is **never committed silently**. Accept or reject.
5. Anything unconfirmed waits in the **briefing bar**, which is the **first
   thing shown** when the user returns.

**The rule underneath:** the AI never invents a commitment. It may *propose* a
time, but an unconfirmed proposal stays visible and actionable until the user
deals with it. **Silence is not acceptance.**

---

## 2. What is missing today

| Gap | Current behaviour | Required |
|---|---|---|
| Ambiguous sentences | **Guesses a concrete time and treats it as a slot** | Propose **and** ask (§5.5/§5.7 `ask_question`) |
| Clarifying question | Never emitted by `/api/say` | At most **one** per proposal |
| Proposal visibility | No server-side support | Not implemented at all |
| Briefing as entry point | A screen you navigate to | Must be the **landing** view, unconfirmed items first |
| Never commit silently | `committed: false`, but a guessed slot looks accepted | Guessed slots visibly marked **unconfirmed** |

---

## 3. Clarification rules

- **At most one question per proposal** (§5.5/§5.7). Do not interrogate.
- **Only when needed.** A question on an unambiguous sentence is noise.
- **Still show a concrete suggested time**, so the user can accept as-is rather
  than composing an answer.
- **Answerable in one tap** where possible — accept, reject, or pick from options.
- **Queued into the briefing**, per §5.5 — not blocking.
- **Budgeted.** `ClarificationBudget` already exists in
  `chronos/ai/briefings.py` with a per-day budget and day rollover. Respect it;
  do not ask on every sentence.

---

## 4. Startup script must ask for timezone

**Requirement from the user: the first-run setup asks for the timezone.**

```
chronos setup
  → speech-to-text provider(s)
  → text model providers (order = failover order)
  → embeddings
  → TIMEZONE                 <-- currently missing
```

This cannot work alone. The server currently hardcodes `tz = UTC` in its routes,
so `instance.timezone` is **ignored** for every day-boundary computation (§7.1),
and a 4pm task can land at the wrong wall-clock hour. Asking for a timezone the
server then ignores is worse than not asking. **Two changes:**

1. the setup script prompts for timezone;
2. the routes read `app.state.timezone` instead of `tz = UTC`.

**Validation:** must be a real IANA zone (`America/New_York`, `Europe/London`),
reject nonsense with a clear message, and default sensibly — confirm the system
zone where available rather than silently falling back to UTC.

The existing `chronos setup` covers providers and embeddings but **does not ask
for timezone**. It needs extending.

---

## 5. Client responsibilities

The client mirrors this state; it does not compute it. See
[client-build-spec.md](client-build-spec.md) §1.

- The **briefing bar is the landing view** — unconfirmed proposals and pending
  questions first, before anything else.
- A **guessed/uncertain slot must be visibly marked** as unconfirmed, not styled
  identically to a confirmed one.
- An **AI bar on every screen**, per [mobile-hud.md](mobile-hud.md) — asking a
  question should never require navigating to a tab.
- After accept or reject, **re-read** from the server. Never assume.

---

## 6. Acceptance

1. "schedule the review" → proposal **with a question**, not a silently-guessed
   confirmed slot.
2. "DB review tomorrow 4pm for 45 mins" → proposal and **no** question.
3. Nothing is committed without explicit acceptance.
4. An unconfirmed proposal survives a restart and is the first thing shown.
5. Accepting resolves it and removes it from the briefing bar.
6. `chronos setup` asks for timezone; the value is validated and stored.
7. With a non-UTC timezone, a 4pm task reports as 4pm local from `/api/events`
   and `/api/briefing`.
8. The clarification budget is respected — not every sentence produces a question.

**Red tests for this already exist** in
`tests/acceptance/test_say_flow_acceptance.py` — written before the wiring, and
several remain red. Treat those as the specification of record.