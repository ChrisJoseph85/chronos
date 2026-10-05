# Phase 2 — AI layer

**Runs in parallel with phases 1, 3–6.** Depends only on the frozen
`chronos/contracts/` and, for the pipeline's tool implementations, on the repo
interface from phase 1 (which is frozen in Phase 0).

Spec: `docs/Chronos.md` §5 (AI layer), §6 (semantic duplicate check),
§4.8 (vector + full-text search).

---

## Parts

| Part | Files | Owner |
|---|---|---|
| 2.1 provider adapter | `chronos/ai/providers/adapter.py` | one code agent |
| 2.2 provider chain | `chronos/ai/providers/chain.py` | one code agent |
| 2.3 retry worker | `chronos/ai/providers/worker.py` | one code agent |
| 2.4 speech (STT) | `chronos/ai/providers/stt.py` | one code agent |
| 2.5 context packer | `chronos/ai/pipeline/packer.py` | one code agent |
| 2.6 intent + verify | `chronos/ai/pipeline/intent.py`, `verify.py` | one code agent |
| 2.7 tool dispatcher | `chronos/ai/pipeline/tools.py` | one code agent |
| 2.8 cost + prices | `chronos/ai/cost.py`, `prices.py`, `cost_hook.py` | one code agent |

Parts 2.1–2.4 are independent of 2.5–2.8; all eight can be worked in the four-agent
ceiling once the interface proposal is frozen.

---

## Behaviour the tests must pin

**Providers (§5.1)**
- **One** OpenAI-compatible adapter serves all three groups — text, speech,
  embeddings. Only base URL and model name differ.
- NIM is used **only** as the free cloud endpoint
  `https://integrate.api.nvidia.com/v1`. It is not self-hosted.
- Default text model `openai/gpt-oss-120b` on Groq. NIM returns HTTP 410 for that
  model, so **the NIM leg must use `nvidia/nemotron-3-super-120b-a12b`** — never
  name a model the provider will reject.
- Speech is `whisper-large-v3-turbo`; embeddings default to local
  `llama-embedding`. Speech and embeddings cannot use the text model.
- **Interactive setup** (`chronos setup`): asks for STT endpoint first, then
  text providers in failover order (name, URL, model, keys), then embeddings.
  Multiple keys per endpoint are tried round-robin before falling through.

**Retry and failover (§5.2)**
- **Failover never raises to the caller.** This is absolute.
- Retries are effectively unbounded but **never on the request path**: a `say` or
  tool request returns immediately with a queued result.
- A background worker retries with **exponential backoff plus jitter**, cycling
  Cloudflare → Groq → NIM, on 429, 5xx and timeout. Never a tight loop.
- After `RETRY_SKIP_AFTER_SECONDS` (default 120) the client is offered a manual
  skip.
- `RETRY_MAX_INFLIGHT` caps concurrent retry jobs; excess queue.
- **Every attempt, failed or not, is written to the daily token-cost table.**

**Roles (§5.3)**
- Understand (primary text), Verify (cheap text), Classify (cheap text). No
  separate decision model.

**Context packer (§5.6)**
- Assembled per turn under a token ceiling. Priority order: (1) identity, hard
  blocks and instance preferences as a **stable prefix placed first**; (2) the
  target node's ancestor chain; (3) semantic and keyword results capped at top N
  with titles and relative dates; (4) ±1 day of events; (5) the user's utterance
  **verbatim, last**.
- Overflow drops from the **lowest** priority upward.
- The packer records what it cut, so the UI can say "checked 30 tasks, showing 8".
- **The current time must be in the prefix**, or the model cannot resolve
  "tomorrow".

**Intent and verify (§5.3, §5.5)**
- Dates in tool arguments are absolute ISO-8601 in the instance timezone. The
  model never emits a bare "day 8". If a pattern is not computable it calls
  `ask_question` or lists explicit dates.
- The verify pass audits proposed calls against the user's actual words and
  corrects dates, offsets and slots before anything is committed. It **never
  invents a call the user did not ask for**.
- A **lookup-only turn gets a second turn.** Without it the model parses correctly
  and then declines to act — a silent no-op.

**Tool dispatcher (§5.5)**
- All 27 tools implemented. **None returns "not implemented".**
- A series is **one tool call, never N**.
- There is **no AI-callable move tool** — only `create_event` (which may report a
  pushed-back slot) and `delete_event`.
- Hard blocks and overlaps are resolved in **code**, never by the model.

**Cost (§5.2, §4.7)**
- `cost_usd` comes from a **real price table**. If it reads `0.0`, the price table
  is missing.
- An unknown price yields `None` — **never a fake `0.0`**.
- No estimates, no placeholders. If a number is not real, say so.

---

## Done means

- [ ] one adapter, three configurations; no provider-specific code paths
- [ ] failover never raises, with backoff and jitter, verified against fakes
- [ ] every attempt — success and failure — lands in the token-cost table
- [ ] the packer respects its ceiling, drops lowest-priority first, records cuts
- [ ] the current time is in the prefix
- [ ] a lookup-only turn triggers a second turn
- [ ] all 27 tools dispatch; none stubbed; no move tool exists
- [ ] an unbounded series is refused by the dispatcher
- [ ] `cost_usd` is `None`, not `0.0`, when the price is unknown
- [ ] full suite green
- [ ] per-part scratch tests and probe scripts deleted; the phase's spec tests kept
      (`manager.md` §10)

---

## Verification

```bash
.venv/bin/python -m pytest tests/phase_2 -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check chronos tests
```

No test may touch the network. Inject fake providers.
