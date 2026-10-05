# Phase 2 — Interface Proposal: `chronos/ai/`

**Status:** FROZEN — Phase 2 proposal approved
**Manager review:** All 10 ambiguities ruled on and approved. See `docs/decisions.md`.  
**Author:** Phase-2 Proposer  
**Date:** 2026-10-03  
**Spec source:** `docs/Chronos.md` §5 (AI layer), §6 (semantic duplicate check), §4.7 (cost), §4.8 (search)  
**Phase doc:** `docs/phases/phase-2-ai.md`  
**Frozen contracts:** `docs/proposals/phase-1-contracts.md`

---

## 0. Scope and principles

This document proposes the complete interface surface for Phase 2 — the AI
layer. It covers:

- **A.** Provider adapter — one OpenAI-compatible adapter for text, speech, embeddings (§5.1)
- **B.** Provider chain — failover, retry, background worker (§5.2)
- **C.** Speech/STT — audio in, transcript out (§5.1)
- **D.** Context packer — budgeted context assembly (§5.6)
- **E.** Intent + verify — structured intent parsing and audit (§5.3, §5.5)
- **F.** Tool dispatcher — all 27 tools (§5.5)
- **G.** Cost + prices — cost tracker, price table, cost hook (§5.2, §4.7)
- **H.** File layout — every file in `chronos/ai/` with purpose and exports

**Principles:**

1. Every module imports from `chronos/contracts/` and nothing else from its
   siblings (§2.1). The import graph must be a DAG with no cycles.
2. All times are UTC epoch **milliseconds** (`INTEGER`) in the database (§4).
   ISO-8601 with offset at every API boundary (§7.3).
3. One instance timezone governs all rendering and date maths (§7.1).
4. The calendar grid is **1 minute** (§7.2).
5. **Failover never raises to the caller** (§5.2, phase doc). This is absolute.
6. **Every attempt — success and failure — lands in the token-cost table** (§5.2, phase doc).
7. **An unknown price yields `None`, never a fake `0.0`** (§5.2, phase doc).
8. No estimates, no placeholders. If a number is not real, say so (phase doc).
9. Dates in tool arguments are absolute ISO-8601 in the instance timezone.
   The model never emits a bare "day 8" (§5.5).
10. A series is **one tool call, never N** (§5.5, phase doc).
11. There is **no AI-callable move tool** (§5.5, phase doc).
12. Hard blocks and overlaps are resolved in **code**, never by the model (§5.5, phase doc).

---

## A. Provider adapter (§5.1)

### A.1 Overview

One OpenAI-compatible adapter serves all three provider groups — text, speech,
and embeddings. Only the base URL, model name, and API key differ between
configurations. There are no provider-specific code paths (§5.1, phase doc).

The adapter speaks three OpenAI-compatible shapes:

| Group | HTTP endpoint | Input | Output |
|---|---|---|---|
| Text (chat) | `POST {base_url}/chat/completions` | messages, tools?, temperature | content, tool_calls, usage |
| Speech (STT) | `POST {base_url}/audio/transcriptions` | audio file, model | transcript text |
| Embeddings | `POST {base_url}/embeddings` | model, input texts | embedding vectors |

### A.2 Configuration

Configuration comes from environment variables (§5.1) or the interactive
`chronos setup` script. The adapter constructor takes explicit values; a factory
function reads env vars and constructs configured adapter instances.

**Interactive setup** (`chronos setup`): On first run, the server walks the
user through provider configuration:
1. STT provider — endpoint, model, number of keys, then each key.
2. Text providers — how many, then for each: name, base URL, model, number of
   keys, then each key. **The order entered is the failover order.**
3. Embeddings — endpoint and model.

Multiple keys per endpoint are tried round-robin before falling through to the
next provider. The setup writes to `.env`.

**Environment variables (§5.1):**

| Variable | Default | Used by |
|---|---|---|
| `TEXT_PROVIDERS` | `groq,nim` | chain — failover order |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | text adapter (Groq) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | text adapter (Groq) |
| `GROQ_API_KEY` | — | text adapter (Groq) |
| `NIM_BASE_URL` | `https://integrate.api.nvidia.com/v1` | text adapter (NIM) |
| `NIM_MODEL` | `nvidia/nemotron-3-super-120b-a12b` | text adapter (NIM) |
| `NIM_API_KEY` | — | text adapter (NIM) |
| `STT_BASE_URL` | `https://api.groq.com/openai/v1` | STT adapter |
| `STT_MODEL` | `whisper-large-v3-turbo` | STT adapter |
| `STT_API_KEY` | — | STT adapter |
| `EMBED_BASE_URL` | `http://localhost:8000/v1` | embeddings adapter |
| `EMBED_MODEL` | `llama-embedding` | embeddings adapter |
| `EMBED_API_KEY` | — | embeddings adapter (if remote) |

**Notes:**
- NIM is used **only** as the free cloud endpoint
  `https://integrate.api.nvidia.com/v1`. It is not self-hosted (§5.1, §0.25).
- NIM returns HTTP 410 for `openai/gpt-oss-120b`, so the NIM leg **must** use
  `nvidia/nemotron-3-super-120b-a12b` — never name a model the provider will
  reject (§5.1, phase doc).
- Speech and embeddings are separate models with different jobs and **cannot
  use the text model** (§5.1, phase doc).
- Embeddings default to local `llama-embedding` (§5.1). The local endpoint
  serves `/v1/embeddings` (§2 architecture diagram).

### A.3 `Adapter` class

The single adapter class. One instance per provider configuration.

```python
class Adapter:
    def __init__(
        self,
        name: str,           # "groq", "nim", "stt", "embed"
        base_url: str,       # e.g. "https://api.groq.com/openai/v1"
        model: str,          # e.g. "openai/gpt-oss-120b"
        api_key: str,        # secret; never logged
        timeout: float = 30.0,
    ) -> None: ...
```

**Properties:**

| Property | Type | Description |
|---|---|---|
| `name` | `str` | Provider label for logging and cost tracking |
| `base_url` | `str` | Base URL for API calls |
| `model` | `str` | Model name for this adapter |
| `timeout` | `float` | Request timeout in seconds |

**Methods:**

#### `chat` — text completion

```python
def chat(
    self,
    messages: list[dict],           # OpenAI message format
    tools: list[dict] | None = None, # OpenAI tool format
    temperature: float = 0.0,
) -> ChatResponse: ...
```

**Returns:** `ChatResponse`

**Raises:** `ProviderError` subclasses (see A.5)

**Behavior:**
- Sends `POST {base_url}/chat/completions` with `{model, messages, tools?, temperature}`.
- Authentication: `Authorization: Bearer {api_key}` header.
- Parses the response into a `ChatResponse`.
- On HTTP error, raises the appropriate `ProviderError` subclass.

#### `transcribe` — speech-to-text

```python
def transcribe(
    self,
    audio: bytes,           # raw audio data
    filename: str = "audio.wav",
) -> str: ...
```

**Returns:** `str` — the transcript text.

**Raises:** `ProviderError` subclasses

**Behavior:**
- Sends `POST {base_url}/audio/transcriptions` as multipart form with
  `file` (audio bytes) and `model`.
- Authentication: `Authorization: Bearer {api_key}` header.
- Returns the `text` field from the response.

#### `embed` — embeddings

```python
def embed(
    self,
    texts: list[str],
) -> list[list[float]]: ...
```

**Returns:** `list[list[float]]` — one 768-dim vector per input text.

**Raises:** `ProviderError` subclasses

**Behavior:**
- Sends `POST {base_url}/embeddings` with `{model, input: texts}`.
- Authentication: `Authorization: Bearer {api_key}` header.
- Returns the `embedding` field from each item in the response `data` array.
- The local `llama-embedding` endpoint serves the same shape (§2).

#### `is_available` — health check

```python
def is_available(self) -> bool: ...
```

**Returns:** `True` if the provider responds to a minimal request, `False`
otherwise. Used by the chain to skip dead providers.

### A.4 Return types

#### `ChatResponse`

```python
@dataclass
class ChatResponse:
    content: str                              # assistant message text
    tool_calls: list[dict] | None = None     # OpenAI tool_call format
    usage: TokenUsage | None = None           # token counts, if available
    raw: dict = field(default_factory=dict)   # full response for debugging
```

#### `TokenUsage`

```python
@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
```

### A.5 Error types

All provider errors inherit from `ProviderError`. The retry logic (§B)
keys off these types.

```python
class ProviderError(Exception):
    """Base adapter error."""
    def __init__(self, message: str, provider: str, status_code: int | None = None): ...

class ProviderRateLimit(ProviderError):
    """HTTP 429 — rate limited. Retryable."""

class ProviderServerError(ProviderError):
    """HTTP 5xx — server error. Retryable."""

class ProviderTimeout(ProviderError):
    """Request timed out. Retryable."""

class ProviderAuthError(ProviderError):
    """HTTP 401/403 — auth failure. NOT retryable."""

class ProviderRejected(ProviderError):
    """HTTP 400/410/other — request rejected. NOT retryable."""
```

**Retryable errors:** `ProviderRateLimit`, `ProviderServerError`,
`ProviderTimeout` (§5.2 — "on 429, 5xx and timeout").

**Non-retryable errors:** `ProviderAuthError`, `ProviderRejected`.

### A.6 Factory function

```python
def build_adapters_from_env(env: dict | None = None) -> list[Adapter]: ...
```

**Returns:** A list of `Adapter` instances configured from environment
variables, in the order specified by `TEXT_PROVIDERS`. Used by the chain
constructor.

**Behavior:**
- Reads `TEXT_PROVIDERS` (default `groq,nim`), splits on comma.
- For each provider name, reads the corresponding `*_BASE_URL`, `*_MODEL`,
  `*_API_KEY` and constructs an `Adapter`.
- The STT and embeddings adapters are constructed separately (they are not
  part of the text failover chain).

---

## B. Provider chain (§5.2)

### B.1 Overview

The provider chain holds multiple text adapters in failover order. It tries
them in sequence; on a retryable failure it returns immediately with a queued
result and a background worker handles retries with exponential backoff plus
jitter, cycling through the adapters (§5.2).

**Failover never raises to the caller** (§5.2, phase doc). This is absolute.

### B.2 `Chain` class

```python
class Chain:
    def __init__(
        self,
        adapters: list[Adapter],                # ordered failover list
        cost_tracker: "CostTracker | None" = None,  # records every attempt
        worker: "RetryWorker | None" = None,        # background retry worker
    ) -> None: ...
```

**Properties:**

| Property | Type | Description |
|---|---|---|
| `adapters` | `list[Adapter]` | Ordered failover adapters |
| `cost_tracker` | `CostTracker \| None` | Cost recording hook |
| `worker` | `RetryWorker \| None` | Background retry worker |

**Methods:**

#### `submit` — send a request through the chain

```python
def submit(
    self,
    request: "ChainRequest",
) -> "ChainResult": ...
```

**Returns:** `ChainResult` — immediately, never blocks on retries.

**Behavior:**
1. Try each adapter in order (first attempt only, on the request path).
2. If an adapter succeeds, record the cost and return a `completed` result.
3. If an adapter fails with a **retryable** error, record the cost, enqueue
   a retry job with the worker, and return a `queued` result immediately.
4. If an adapter fails with a **non-retryable** error, record the cost and
   try the next adapter.
5. If all adapters fail with retryable errors, enqueue a retry job and return
   `queued`.
6. If all adapters fail with non-retryable errors, return a `failed` result.
7. **Never raises.** All exceptions are caught and converted to `failed` or
   `queued` results.

#### `next_adapter` — cycle to the next adapter

```python
def next_adapter(self, current: Adapter | None = None) -> Adapter: ...
```

**Returns:** The next adapter in the cycle. If `current` is `None`, returns
the first adapter. Wraps around to the beginning after the last.

**Behavior:**
- Cycles through `self.adapters` in order.
- Used by the worker to select the next provider on each retry.

#### `record_attempt` — record a cost entry

```python
def record_attempt(
    self,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    success: bool,
    error_type: str | None = None,
) -> None: ...
```

**Behavior:**
- Delegates to `self.cost_tracker.record(...)` if a cost tracker is set.
- Called for **every attempt, failed or not** (§5.2, phase doc).

### B.3 `ChainRequest` type

```python
@dataclass
class ChainRequest:
    request_id: str                           # uuid4
    kind: str                                 # "chat" | "transcribe" | "embed"
    messages: list[dict] | None = None        # for chat
    tools: list[dict] | None = None           # for chat
    audio: bytes | None = None                # for transcribe
    filename: str = "audio.wav"               # for transcribe
    texts: list[str] | None = None            # for embed
    submitted_at: int = 0                     # epoch ms
    attempt: int = 0                          # attempt number
    adapter_index: int = 0                    # which adapter to try first
```

### B.4 `ChainResult` type

```python
@dataclass
class ChainResult:
    request_id: str
    status: str                               # "completed" | "queued" | "failed"
    response: "ChatResponse | str | list[list[float]] | None" = None
    error: str | None = None
    provider: str | None = None
    attempts: int = 0
```

### B.5 Retry logic (§5.2)

Retries use **exponential backoff plus jitter** and cycle through adapters
on each attempt.

**Constants:**

| Constant | Default | Description |
|---|---|---|
| `RETRY_SKIP_AFTER_SECONDS` | `120` | After this many seconds, the client is offered a manual skip (§5.2) |
| `RETRY_MAX_INFLIGHT` | `8` | Cap on concurrent retry jobs; excess requests queue (§5.2) |
| `RETRY_BASE_DELAY` | `1.0` | Base delay in seconds |
| `RETRY_MAX_DELAY` | `60.0` | Maximum delay cap in seconds |
| `RETRY_BACKOFF_MULTIPLIER` | `2.0` | Exponential multiplier |
| `RETRY_JITTER_FRACTION` | `0.25` | Jitter as a fraction of the computed delay |

**Backoff formula:**

```
delay = min(RETRY_BASE_DELAY * (RETRY_BACKOFF_MULTIPLIER ** attempt), RETRY_MAX_DELAY)
jitter = delay * RETRY_JITTER_FRACTION * random_uniform(-1, 1)
actual_delay = delay + jitter
```

**Retryable conditions:** HTTP 429, HTTP 5xx, timeout (§5.2).

**Non-retryable conditions:** HTTP 401/403, HTTP 400/410, parse errors.

**Behavior:**
- The worker cycles through adapters: Cloudflare → Groq → NIM → Cloudflare → …
  (see ambiguity I.1 regarding Cloudflare).
- After `RETRY_SKIP_AFTER_SECONDS` (default 120), the client is offered a
  manual skip so a dead provider can never trap the interface indefinitely (§5.2).
- `RETRY_MAX_INFLIGHT` caps concurrent retry jobs. Excess requests queue.
  Without this cap a dead provider would quietly consume memory (§5.2).
- Retries are **effectively unbounded** — providers cycle until something
  succeeds or the user skips (§5.2).

### B.6 `RetryWorker` class

The background worker that retries failed requests off the request path.

```python
class RetryWorker:
    def __init__(
        self,
        chain: Chain,
        max_inflight: int = RETRY_MAX_INFLIGHT,
    ) -> None: ...
```

**Properties:**

| Property | Type | Description |
|---|---|---|
| `chain` | `Chain` | The provider chain |
| `max_inflight` | `int` | Max concurrent retry jobs |
| `running` | `bool` | Whether the worker is active |

**Methods:**

#### `start` — start the worker

```python
def start(self) -> None: ...
```

**Behavior:**
- Starts the background thread/task that processes the retry queue.
- The worker runs until `stop()` is called.

#### `stop` — stop the worker

```python
def stop(self) -> None: ...
```

**Behavior:**
- Signals the worker to stop after the current job completes.
- Does not cancel in-flight jobs.

#### `enqueue` — add a retry job

```python
def enqueue(self, job: "RetryJob") -> None: ...
```

**Behavior:**
- Adds a job to the retry queue.
- If the number of in-flight jobs is below `max_inflight`, the job starts
  immediately.
- Otherwise, it waits in the queue.

#### `status` — worker status

```python
def status(self) -> "WorkerStatus": ...
```

**Returns:** `WorkerStatus` with queue depth, in-flight count, and running
state.

### B.7 `RetryJob` type

```python
@dataclass
class RetryJob:
    request: ChainRequest
    attempt: int = 0
    first_attempt_at: int = 0     # epoch ms
    next_retry_at: int = 0        # epoch ms
    adapter_index: int = 0
```

### B.8 `WorkerStatus` type

```python
@dataclass
class WorkerStatus:
    running: bool
    queue_depth: int
    inflight: int
    max_inflight: int
    total_retried: int
    total_succeeded: int
    total_failed: int
```

---

## C. Speech/STT (§5.1)

### C.1 Overview

The STT adapter converts audio to text. It is a separate adapter configuration
using the same `Adapter` class (§A) with speech-specific env vars.

### C.2 Configuration

| Variable | Default | Description |
|---|---|---|
| `STT_BASE_URL` | `https://api.groq.com/openai/v1` | STT provider base URL |
| `STT_MODEL` | `whisper-large-v3-turbo` | STT model name |
| `STT_API_KEY` | — | STT provider API key |

**Notes:**
- Speech uses `whisper-large-v3-turbo` (§5.1, phase doc).
- Speech **cannot use the text model** (§5.1, phase doc).
- The STT adapter is constructed via `Adapter(name="stt", base_url=STT_BASE_URL, model=STT_MODEL, api_key=STT_API_KEY)`.

### C.3 STT flow

```python
def transcribe_audio(
    audio: bytes,
    adapter: Adapter | None = None,
) -> str: ...
```

**Parameters:**
- `audio`: Raw audio bytes from the client.
- `adapter`: The STT adapter. If `None`, builds one from env vars.

**Returns:** `str` — the transcript text.

**Behavior:**
1. If no adapter is provided, construct one from `STT_*` env vars.
2. Call `adapter.transcribe(audio)`.
3. Return the transcript text.
4. On failure, the error propagates to the caller (the API layer handles
   retry/failover for STT if needed — see ambiguity I.4).

### C.4 Integration with `/api/voice`

The REST endpoint `POST /api/voice` (§8.2) receives audio and returns a
transcript. The flow:

1. Client POSTs audio to `/api/voice`.
2. The API layer calls `transcribe_audio(audio)`.
3. The transcript is returned to the client.
4. The client **appends** the transcript to the say box (§9.1).

---

## D. Context packer (§5.6)

### D.1 Overview

The context packer assembles the model's context per turn under a token
ceiling. It follows a strict priority order and drops from the lowest
priority upward on overflow. It records what it cut so the UI can say
"checked 30 tasks, showing 8" (§5.6, phase doc).

### D.2 `Packer` class

```python
class Packer:
    def __init__(
        self,
        token_ceiling: int,                    # max tokens per turn
        clock: "Clock",                         # from contracts
        node_repo: "NodeRepo",                  # from contracts
        event_repo: "EventRepo",                # from contracts
        search: "SearchBackend",               # from contracts
        schedule_repo: "ScheduleRepo | None" = None,
    ) -> None: ...
```

**Properties:**

| Property | Type | Description |
|---|---|---|
| `token_ceiling` | `int` | Maximum tokens in the packed context |
| `clock` | `Clock` | Time provider |
| `node_repo` | `NodeRepo` | Node repository |
| `event_repo` | `EventRepo` | Event repository |
| `search` | `SearchBackend` | Search backend |
| `schedule_repo` | `ScheduleRepo \| None` | Schedule repository (for hard blocks) |

**Methods:**

#### `pack` — assemble context for a turn

```python
def pack(
    self,
    turn: "TurnContext",
) -> "PackedContext": ...
```

**Returns:** `PackedContext` — the assembled context with cut records.

**Behavior:**
1. Build the context layers in priority order (§D.3).
2. Estimate tokens for each layer.
3. Add layers from highest to lowest priority until the ceiling is reached.
4. If adding a layer would exceed the ceiling, skip it and record a cut.
5. Return the packed context with all cut records.

#### `estimate_tokens` — estimate token count

```python
def estimate_tokens(self, text: str) -> int: ...
```

**Returns:** `int` — estimated token count.

**Behavior:**
- Uses a deterministic estimation method (see ambiguity I.5).
- Must be fast — no external tokenizer call.

### D.3 Priority order (§5.6)

The packer assembles context in this exact order. Overflow drops from the
**lowest** priority upward (§5.6, phase doc).

| Priority | Layer | Content | Source |
|---|---|---|---|
| 1 (highest) | Identity + hard blocks + preferences | User identity, hard blocks (schedules), instance preferences, **current time** | settings, schedules |
| 2 | Ancestor chain | The target node's ancestor chain (project → task → subtask) | `node_repo` |
| 3 | Search results | Semantic and keyword results, capped at top N with titles and relative dates | `search` |
| 4 | ±1 day events | Events within ±1 day of the target date for conflict checking | `event_repo` |
| 5 (lowest) | User utterance | The user's utterance **verbatim, last** | `turn.user_text` |

**Notes:**
- **The current time must be in the prefix** (priority 1), or the model
  cannot resolve "tomorrow" (§5.6, phase doc).
- The prefix (priority 1) is a **stable prefix placed first** so provider
  prompt caching applies (§5.6).
- Search results (priority 3) are capped at top N with **titles and relative
  dates** rather than full bodies (§5.6).
- The user's utterance (priority 5) is placed **verbatim, last** (§5.6).

### D.4 `TurnContext` type

```python
@dataclass
class TurnContext:
    user_text: str                            # the user's utterance
    target_node_id: str | None = None         # the node being discussed
    target_date_ms: int | None = None         # the date being discussed
    search_query: str | None = None           # extracted search query
    search_limit: int = 10                    # max search results
    event_window_ms: int = 86400000           # ±1 day in ms
```

### D.5 `PackedContext` type

```python
@dataclass
class PackedContext:
    messages: list[dict]                      # OpenAI message format
    token_count: int                          # total estimated tokens
    cuts: list["CutRecord"]                   # what was cut
    layers_included: list[str]                # names of included layers
    layers_excluded: list[str]                # names of excluded layers
```

### D.6 `CutRecord` type

```python
@dataclass
class CutRecord:
    layer: str                                # which layer was cut
    priority: int                             # priority number (1-5)
    items_total: int                          # total items available
    items_included: int                       # items that fit
    items_cut: int                            # items dropped
    reason: str                               # "token_ceiling"
```

**Example:** `CutRecord(layer="search_results", priority=3, items_total=30, items_included=8, items_cut=22, reason="token_ceiling")` — the UI can say "checked 30 tasks, showing 8" (§5.6).

### D.7 Token ceiling configuration

| Variable | Default | Description |
|---|---|---|
| `CONTEXT_TOKEN_CEILING` | `4096` | Maximum tokens per packed context |
| `CONTEXT_SEARCH_LIMIT` | `10` | Max search results in priority 3 |
| `CONTEXT_EVENT_WINDOW_MS` | `86400000` | ±1 day in milliseconds |

---

## E. Intent + verify (§5.3, §5.5)

### E.1 Overview

The intent parser turns user text into structured intent with tool calls.
The verify pass audits proposed tool calls against the user's actual words
and corrects dates, offsets and slots before anything is committed (§5.3).

There is **no separate decision model** (§5.3). The three roles are:

| Role | Job | Model |
|---|---|---|
| Understand | voice or text → structured intent → tool calls | TEXT, primary |
| Verify | audit proposed tool calls against the user's actual words | TEXT, cheap tier |
| Classify | duplicate scoring, tier choice, bucket level | TEXT, cheap tier |

### E.2 `IntentParser` class

```python
class IntentParser:
    def __init__(
        self,
        adapter: Adapter,                  # primary text adapter
        packer: Packer,                    # context packer
    ) -> None: ...
```

**Methods:**

#### `parse` — parse user text into structured intent

```python
def parse(
    self,
    text: str,
    context: "TurnContext",
) -> "IntentResult": ...
```

**Returns:** `IntentResult`

**Behavior:**
1. Pack the context using `self.packer.pack(context)`.
2. Build the system prompt with the packed context and tool schemas.
3. Call `adapter.chat(messages, tools=TOOL_SCHEMAS)`.
4. Parse the response into an `IntentResult`.
5. If the response contains tool calls, validate them against the schemas.
6. If the response is lookup-only (no mutation tools), flag for a second
   turn (§E.5).

### E.3 `IntentResult` type

```python
@dataclass
class IntentResult:
    tool_calls: list["ToolCall"]           # from contracts
    needs_clarification: bool = False
    clarification_question: str | None = None
    is_lookup_only: bool = False           # triggers second turn
    raw_response: "ChatResponse | None" = None
```

### E.4 Date handling (§5.5)

**Dates in tool arguments are absolute ISO-8601 in the instance timezone.**
The model never emits a bare "day 8" (§5.5, phase doc).

**Rules:**
- All dates in tool call arguments must be ISO-8601 with offset, e.g.
  `2026-10-05T16:00:00+02:00`.
- Relative dates ("tomorrow", "next week", "day 8") are resolved to absolute
  dates by the intent parser using the current time from the packer's prefix.
- If a pattern is not computable, the model calls `ask_question` or lists
  explicit dates (§5.5).
- The verify pass (§E.6) audits all dates and corrects them if they don't
  match the user's words.

### E.5 Lookup-only turn — second turn (§5.3, phase doc)

A **lookup-only turn gets a second turn** (phase doc). Without it the model
parses correctly and then declines to act — a silent no-op.

**Detection:** After the first turn, if `IntentResult.is_lookup_only` is
`True` (the model produced only lookup tool calls like `search_nodes`,
`get_day`, `get_briefing`, or no tool calls at all), the system runs a
second turn.

**Second turn behavior:**
1. The system takes the lookup results from the first turn.
2. It builds a new prompt that includes the lookup results and encourages
   the model to act on them.
3. It calls `adapter.chat(...)` again with the augmented context.
4. The second turn's `IntentResult` is used for tool dispatch.

**Interface:**

```python
def needs_second_turn(intent_result: IntentResult) -> bool: ...
```

**Returns:** `True` if the intent result is lookup-only and should trigger
a second turn.

### E.6 `Verifier` class

```python
class Verifier:
    def __init__(
        self,
        adapter: Adapter,                  # cheap text adapter
    ) -> None: ...
```

**Methods:**

#### `audit` — audit proposed tool calls

```python
def audit(
    self,
    intent_result: IntentResult,
    user_text: str,
    context: TurnContext,
) -> "VerifiedResult": ...
```

**Returns:** `VerifiedResult`

**Behavior:**
1. Build a verification prompt with:
   - The user's original words (`user_text`).
   - The proposed tool calls from `intent_result`.
   - The packed context.
2. Call `adapter.chat(messages)` with a narrow verification job.
3. The verifier checks:
   - Do the tool calls match what the user asked for?
   - Are the dates correct?
   - Are the offsets correct?
   - Are the slots correct?
4. The verifier **never invents a call the user did not ask for** (§5.3, phase doc).
5. On a mismatch, it corrects dates, offsets and slots (§5.3).
6. Return the verified result with any corrections.

### E.7 `VerifiedResult` type

```python
@dataclass
class VerifiedResult:
    tool_calls: list["ToolCall"]           # corrected tool calls
    approved: bool                         # True if all calls are approved
    corrections: list["Correction"]        # what was corrected
    rejection_reason: str | None = None    # why rejected, if not approved
```

### E.8 `Correction` type

```python
@dataclass
class Correction:
    tool_call_index: int                   # which tool call
    field: str                             # what was corrected
    old_value: str                         # original value
    new_value: str                         # corrected value
    reason: str                            # why corrected
```

---

## F. Tool dispatcher (§5.5)

### F.1 Overview

The tool dispatcher implements all 27 tools from the frozen contracts
(§5.5, phase-1-contracts §C). **None returns "not implemented"** (phase doc).
Each tool dispatches to its implementation and returns a `ToolResult`.

### F.2 `ToolDispatcher` class

```python
class ToolDispatcher:
    def __init__(
        self,
        node_repo: "NodeRepo",
        tag_repo: "TagRepo",
        node_tag_repo: "NodeTagRepo",
        event_repo: "EventRepo",
        bucket_repo: "BucketRepo",
        review_series_repo: "ReviewSeriesRepo",
        schedule_repo: "ScheduleRepo",
        reminder_repo: "ReminderRepo",
        timer_session_repo: "TimerSessionRepo",
        audit_repo: "AuditRepo",
        search: "SearchBackend",
        clock: "Clock",
        id_gen: "IdGen",
        cost_tracker: "CostTracker | None" = None,
    ) -> None: ...
```

**Methods:**

#### `dispatch` — dispatch a single tool call

```python
def dispatch(
    self,
    tool_call: "ToolCall",
) -> "ToolResult": ...
```

**Returns:** `ToolResult` — from contracts.

**Behavior:**
1. Look up the tool implementation by `tool_call.name`.
2. Validate the arguments against the tool's schema.
3. Execute the tool implementation.
4. Return a `ToolResult` with the result or an error.
5. **Never returns "not implemented"** — all 27 tools are implemented.
6. Record the cost via `cost_tracker` if set.

#### `dispatch_all` — dispatch multiple tool calls

```python
def dispatch_all(
    self,
    tool_calls: list["ToolCall"],
) -> list["ToolResult"]: ...
```

**Returns:** `list[ToolResult]` — one per tool call.

**Behavior:**
- Dispatches each tool call in order.
- If one fails, the others still execute (no transaction across tools).
- Each tool's implementation handles its own transactionality.

### F.3 Tool implementations

All 27 tools from §5.5 and phase-1-contracts §C. Each is a method on
`ToolDispatcher` or a helper it calls.

#### F.3.1 Node tools (§5.5, contracts §C.1–C.6)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `create_node` | `_create_node(args)` | `Node` | Creates project/task/subtask. Searches for duplicates first (§5.4). |
| `update_node` | `_update_node(args)` | `Node` | Updates title, notes, status, parent. |
| `delete_node` | `_delete_node(args)` | `{deleted, cascade_count}` | Cascades to children. |
| `link_nodes` | `_link_nodes(args)` | `{link_id}` | Non-structural link (§4.1). |
| `tag_node` | `_tag_node(args)` | `NodeTag` | Tags tasks/subtasks, never projects (§4.1). Reuses existing tags by name (§5.4). |
| `untag_node` | `_untag_node(args)` | `{removed}` | Removes tag from node. |

#### F.3.2 Event tools (§5.5, contracts §C.7–C.9)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `create_event` | `_create_event(args)` | `{event, requested_start_ms, requested_end_ms, actual_start_ms, actual_end_ms, pushed}` | Overlapping events pushed to first free minute (§6). Hard blocks resolved in code. |
| `update_event` | `_update_event(args)` | `{event, pushed}` | Updates event fields. Re-checks conflicts. |
| `delete_event` | `_delete_event(args)` | `{deleted}` | Soft delete. Soft-deleted events are not conflicts (§6). |

**No move tool:** There is **no AI-callable move tool** (§5.5, phase doc).
Moving an event is done via `update_event` (which can change `start_ms` and
`end_ms`) or `delete_event` + `create_event`.

#### F.3.3 Series tools (§5.5, contracts §C.10–C.12)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `schedule_series` | `_schedule_series(args)` | `{series, events}` | **One tool call, never N** (§5.5). Writes all review events in one transaction (§4.4). Must be bounded. |
| `delete_series` | `_delete_series(args)` | `{deleted, event_count}` | Deletes series and all events in one transaction. |
| `reschedule_series` | `_reschedule_series(args)` | `{series, events}` | Bulk-reschedules future review events. |

**Series rules:**
- A series is **one tool call, never N** (§5.5, phase doc).
- A series **must be bounded**: `max_count` and/or `ends_on_ms`, at least one
  (§4.4). An unbounded series is **refused by the dispatcher** (phase doc).
- Creating a series writes all review events in **one transaction** (§4.4).
- Default tiers: hard `[1,2,4,8,16]`, medium `[3,7,15,30]`, easy `[10,30,90]`
  (§4.4, contracts §A.6).
- No geometric/GP formulas. No automatic rewind (§4.4).

#### F.3.4 Search and scheduling tools (§5.5, contracts §C.13–C.16)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `search_nodes` | `_search_nodes(args)` | `list[Node]` | Keyword + semantic search (§4.8). |
| `check_conflict` | `_check_conflict(args)` | `{hard_conflicts, semantic_candidates}` | Hard conflicts + semantic duplicates (§6). Window up to ±7 days. |
| `find_free_slots` | `_find_free_slots(args)` | `list[{start_ms, end_ms}]` | Free slots in a range. |
| `get_free_time` | `_get_free_time(args)` | `{free_minutes, busy_minutes}` | Total free time in a range. |

#### F.3.5 Schedule tools (§5.5, contracts §C.17–C.19)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `create_schedule` | `_create_schedule(args)` | `Schedule` | Creates recurring commitment (§4.5). |
| `update_schedule` | `_update_schedule(args)` | `Schedule` | Updates schedule fields. |
| `pause_schedule` | `_pause_schedule(args)` | `Schedule` | Pauses/unpauses. Paused schedules do not block (§4.5). |

#### F.3.6 Timer tools (§5.5, contracts §C.20–C.22)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `start_timer` | `_start_timer(args)` | `TimerSession` | One timer at a time across all modes (§4.7). |
| `stop_timer` | `_stop_timer(args)` | `TimerSession` | Stops the running timer. |
| `log_time` | `_log_time(args)` | `{node_total_ms, descendant_total_ms, project_total_ms}` | Per-node time reporting (§4.7). |

#### F.3.7 Query tools (§5.5, contracts §C.23–C.26)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `get_day` | `_get_day(args)` | `{date, events, buckets, timer}` | Day view. |
| `get_week` | `_get_week(args)` | `{week_start, week_end, events, buckets}` | Week view. |
| `get_month` | `_get_month(args)` | `{month_start, month_end, events, buckets}` | Month view. |
| `get_briefing` | `_get_briefing(args)` | `{date, unallocated_tasks, rollover, due_reviews, question}` | Daily briefing (§5.7). |

#### F.3.8 Clarification tool (§5.5, contracts §C.27)

| Tool | Method | Returns | Notes |
|---|---|---|---|
| `ask_question` | `_ask_question(args)` | `{question_id, queued}` | One proactive question per day (§5.7). |

### F.4 Hard blocks and overlaps (§5.5, §6)

**Hard blocks and overlaps are resolved in code, never by the model** (§5.5,
phase doc).

**Hard slot conflict resolution (§6):**
- At commit, an event overlapping an existing non-deleted event is pushed to
  the first free minute that satisfies duration, hard blocks and day bounds.
- Deterministic, plain SQL, no model involved.
- The response carries both the requested and the actual slot.

**Hard blocks (§6, §4.5):**
- Schedules are hard blocks. Nothing is auto-placed inside one.
- An explicit override is permitted and audited.
- Paused schedules do not block. Non-`hard_block` schedules do not block.

**Semantic duplicate check (§6):**
- Before a create, FTS5 plus sqlite-vec search over ±1 day surfaces
  candidates that look like the same work.
- This warns and proposes; it never moves anything.
- The model returns a confidence and the user decides.
- The window may be widened through `check_conflict`, up to ±7 days.

### F.5 Unbounded series refusal (phase doc)

The dispatcher **refuses an unbounded series** — a series with neither
`max_count` nor `ends_on_ms`. This is enforced at the dispatcher level,
not by the model.

```python
def _validate_series_bounds(args: dict) -> None: ...
```

**Raises:** `ValueError` with a clear message if the series is unbounded.

---

## G. Cost + prices (§5.2, §4.7)

### G.1 Overview

The cost tracker records every provider attempt — success or failure — to a
daily token-cost table (§5.2, phase doc). The price table maps models to
real prices. An unknown price yields `None`, never a fake `0.0` (§5.2,
phase doc).

### G.2 `CostTracker` class

```python
class CostTracker:
    def __init__(
        self,
        db_connection: "sqlite3.Connection",   # or a cost repo protocol
    ) -> None: ...
```

**Methods:**

#### `record` — record a cost entry

```python
def record(
    self,
    provider: str,                  # "groq", "nim", etc.
    model: str,                     # model name
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    success: bool,                  # True if the attempt succeeded
    error_type: str | None = None,  # "429", "5xx", "timeout", etc.
    cost_usd: float | None = None,  # None if price unknown
) -> None: ...
```

**Behavior:**
- Writes a row to the token-cost table.
- Called for **every attempt, failed or not** (§5.2, phase doc).
- If `cost_usd` is `None`, the price was unknown — this is recorded as
  `NULL`, never as `0.0`.

#### `get_daily_cost` — get cost for a day

```python
def get_daily_cost(
    self,
    date_ms: int,                   # epoch ms for the day
) -> "DailyCost": ...
```

**Returns:** `DailyCost` with total tokens and cost for the day.

#### `get_cost_range` — get cost for a range

```python
def get_cost_range(
    self,
    start_ms: int,
    end_ms: int,
) -> list["DailyCost"]: ...
```

**Returns:** List of `DailyCost` for each day in the range.

### G.3 `DailyCost` type

```python
@dataclass
class DailyCost:
    date_ms: int                    # epoch ms for the day start
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None          # None if any price was unknown
    attempts: int
    failures: int
```

### G.4 `PriceTable` class

```python
class PriceTable:
    def __init__(self, prices: dict[str, dict[str, float]] | None = None) -> None: ...
```

**Methods:**

#### `get_price` — get price for a model

```python
def get_price(
    self,
    provider: str,
    model: str,
    token_type: str,                # "input" | "output"
) -> float | None: ...
```

**Returns:** Price per 1M tokens in USD, or `None` if the price is unknown.

**Behavior:**
- Looks up the price for the given provider/model/token_type.
- If the price is not in the table, returns `None` — **never `0.0`**
  (§5.2, phase doc).
- Prices are real, published prices. No estimates, no placeholders.

#### `compute_cost` — compute cost for a request

```python
def compute_cost(
    self,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None: ...
```

**Returns:** Cost in USD, or `None` if any price is unknown.

**Behavior:**
- Looks up input and output prices.
- If either is `None`, returns `None`.
- Otherwise: `(prompt_tokens / 1_000_000) * input_price + (completion_tokens / 1_000_000) * output_price`.

### G.5 Default price table

The default price table contains real published prices for known models.
Unknown models are simply absent from the table, yielding `None`.

```python
DEFAULT_PRICES: dict[str, dict[str, dict[str, float]]] = {
    "groq": {
        "openai/gpt-oss-120b": {
            "input": 0.25,   # per 1M tokens
            "output": 0.50,  # per 1M tokens
        },
    },
    "nim": {
        "nvidia/nemotron-3-super-120b-a12b": {
            "input": 0.0,
            "output": 0.0,
        },
    },
    # ... other known models
}
```

**Notes:**
- NIM is a free cloud endpoint, so its price is `0.0` (it is known to be
  free, not unknown).
- If a model is not in the table, `get_price` returns `None`.
- Prices are updated manually when providers change them.

### G.6 `cost_hook.py` — cost hook for provider chain

The cost hook intercepts every provider attempt and records it to the cost
table. It hooks into the provider chain.

```python
def cost_hook(
    chain: Chain,
    cost_tracker: CostTracker,
    price_table: PriceTable,
) -> None: ...
```

**Behavior:**
- Wraps the chain's `record_attempt` method to automatically compute and
  record costs.
- For each attempt, looks up the price and computes the cost.
- If the price is unknown, records `cost_usd=None`.
- Hooks into the chain so every attempt is recorded without explicit calls.

**Alternative interface (if a hook function is not sufficient):**

```python
class CostHook:
    def __init__(self, cost_tracker: CostTracker, price_table: PriceTable) -> None: ...
    def on_attempt(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int, success: bool, error_type: str | None) -> None: ...
```

**Behavior:**
- The chain calls `cost_hook.on_attempt(...)` after every attempt.
- The hook computes the cost and records it via `cost_tracker.record(...)`.

### G.7 Token-cost table schema

The daily token-cost table is a SQLite table (see ambiguity I.9):

```sql
CREATE TABLE token_cost (
    id              INTEGER PRIMARY KEY,
    at              INTEGER NOT NULL,           -- epoch ms
    provider        TEXT NOT NULL,              -- "groq", "nim", etc.
    model           TEXT NOT NULL,              -- model name
    prompt_tokens   INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens    INTEGER NOT NULL,
    cost_usd        REAL,                       -- NULL if price unknown
    success         INTEGER NOT NULL,           -- 1 = success, 0 = failure
    error_type      TEXT                        -- "429", "5xx", "timeout", etc.
);
CREATE INDEX ix_token_cost_day ON token_cost(at);
CREATE INDEX ix_token_cost_provider ON token_cost(provider);
```

**Notes:**
- `cost_usd` is `NULL` when the price is unknown — never `0.0` (§5.2).
- The `chronos token-cost [--days 7]` CLI command (§8.1) queries this table.
- The `GET /api/stats` endpoint (§8.2) includes "token spend by day" from
  this table.

---

## H. File layout

Every file in `chronos/ai/` with its purpose and exports. The import graph
is a DAG with no cycles.

```
chronos/ai/
  __init__.py              — re-exports public names
  providers/
    __init__.py            — re-exports provider names
    adapter.py             — Adapter, ChatResponse, TokenUsage, ProviderError types, build_adapters_from_env
    chain.py               — Chain, ChainRequest, ChainResult, retry constants
    worker.py              — RetryWorker, RetryJob, WorkerStatus
    stt.py                 — transcribe_audio, STT configuration
  pipeline/
    __init__.py            — re-exports pipeline names
    packer.py              — Packer, TurnContext, PackedContext, CutRecord
    intent.py              — IntentParser, IntentResult, needs_second_turn
    verify.py              — Verifier, VerifiedResult, Correction
    tools.py               — ToolDispatcher, all 27 tool implementations
  cost.py                  — CostTracker, DailyCost
  prices.py                — PriceTable, DEFAULT_PRICES
  cost_hook.py             — cost_hook, CostHook
```

### H.1 `chronos/ai/__init__.py`

**Purpose:** Re-exports all public names from the submodules.

**Exports:**
- From `providers`: `Adapter`, `Chain`, `RetryWorker`, `ChatResponse`, `TokenUsage`, `ProviderError`, `ProviderRateLimit`, `ProviderServerError`, `ProviderTimeout`, `ProviderAuthError`, `ProviderRejected`, `ChainRequest`, `ChainResult`, `RetryJob`, `WorkerStatus`, `build_adapters_from_env`, `transcribe_audio`
- From `pipeline`: `Packer`, `IntentParser`, `Verifier`, `ToolDispatcher`, `TurnContext`, `PackedContext`, `CutRecord`, `IntentResult`, `VerifiedResult`, `Correction`, `needs_second_turn`
- From `cost`: `CostTracker`, `DailyCost`
- From `prices`: `PriceTable`, `DEFAULT_PRICES`
- From `cost_hook`: `cost_hook`, `CostHook`

### H.2 `chronos/ai/providers/__init__.py`

**Purpose:** Re-exports provider names.

**Exports:** `Adapter`, `Chain`, `RetryWorker`, `ChatResponse`, `TokenUsage`, `ProviderError`, `ProviderRateLimit`, `ProviderServerError`, `ProviderTimeout`, `ProviderAuthError`, `ProviderRejected`, `ChainRequest`, `ChainResult`, `RetryJob`, `WorkerStatus`, `build_adapters_from_env`, `transcribe_audio`

### H.3 `chronos/ai/providers/adapter.py`

**Purpose:** The single OpenAI-compatible adapter for all three provider
groups. Imports from `chronos/contracts/` for type hints.

**Imports:** `chronos.contracts` (for type hints), `httpx` or `requests` (HTTP client)

**Exports:** `Adapter`, `ChatResponse`, `TokenUsage`, `ProviderError`, `ProviderRateLimit`, `ProviderServerError`, `ProviderTimeout`, `ProviderAuthError`, `ProviderRejected`, `build_adapters_from_env`

### H.4 `chronos/ai/providers/chain.py`

**Purpose:** The provider chain with failover. Imports from `adapter.py`.

**Imports:** `adapter` (Adapter, ProviderError types), `cost` (CostTracker — optional)

**Exports:** `Chain`, `ChainRequest`, `ChainResult`, `RETRY_SKIP_AFTER_SECONDS`, `RETRY_MAX_INFLIGHT`, `RETRY_BASE_DELAY`, `RETRY_MAX_DELAY`, `RETRY_BACKOFF_MULTIPLIER`, `RETRY_JITTER_FRACTION`

### H.5 `chronos/ai/providers/worker.py`

**Purpose:** The background retry worker. Imports from `chain.py`.

**Imports:** `chain` (Chain, ChainRequest, retry constants)

**Exports:** `RetryWorker`, `RetryJob`, `WorkerStatus`

### H.6 `chronos/ai/providers/stt.py`

**Purpose:** Speech-to-text adapter configuration and flow. Imports from
`adapter.py`.

**Imports:** `adapter` (Adapter, build_adapters_from_env)

**Exports:** `transcribe_audio`

### H.7 `chronos/ai/pipeline/__init__.py`

**Purpose:** Re-exports pipeline names.

**Exports:** `Packer`, `IntentParser`, `Verifier`, `ToolDispatcher`, `TurnContext`, `PackedContext`, `CutRecord`, `IntentResult`, `VerifiedResult`, `Correction`, `needs_second_turn`

### H.8 `chronos/ai/pipeline/packer.py`

**Purpose:** The budgeted context packer. Imports from `chronos/contracts/`.

**Imports:** `chronos.contracts` (Clock, NodeRepo, EventRepo, SearchBackend, ScheduleRepo)

**Exports:** `Packer`, `TurnContext`, `PackedContext`, `CutRecord`, `CONTEXT_TOKEN_CEILING`, `CONTEXT_SEARCH_LIMIT`, `CONTEXT_EVENT_WINDOW_MS`

### H.9 `chronos/ai/pipeline/intent.py`

**Purpose:** The intent parser. Imports from `packer.py` and `adapter.py`.

**Imports:** `packer` (Packer, TurnContext), `adapter` (Adapter), `chronos.contracts` (ToolCall, TOOL_SCHEMAS)

**Exports:** `IntentParser`, `IntentResult`, `needs_second_turn`

### H.10 `chronos/ai/pipeline/verify.py`

**Purpose:** The verify pass. Imports from `adapter.py`.

**Imports:** `adapter` (Adapter), `chronos.contracts` (ToolCall)

**Exports:** `Verifier`, `VerifiedResult`, `Correction`

### H.11 `chronos/ai/pipeline/tools.py`

**Purpose:** The tool dispatcher with all 27 tool implementations. Imports
from `chronos/contracts/`.

**Imports:** `chronos.contracts` (all repos, Clock, IdGen, SearchBackend, ToolCall, ToolResult, TOOL_SCHEMAS, all models, all enums), `cost` (CostTracker — optional)

**Exports:** `ToolDispatcher`

### H.12 `chronos/ai/cost.py`

**Purpose:** The cost tracker. Imports from `chronos/contracts/` for
AuditEntry.

**Imports:** `chronos.contracts` (AuditEntry)

**Exports:** `CostTracker`, `DailyCost`

### H.13 `chronos/ai/prices.py`

**Purpose:** The price table with real published prices.

**Imports:** none (standalone data)

**Exports:** `PriceTable`, `DEFAULT_PRICES`

### H.14 `chronos/ai/cost_hook.py`

**Purpose:** The cost hook that intercepts provider attempts and records
costs. Imports from `cost.py` and `prices.py`.

**Imports:** `cost` (CostTracker), `prices` (PriceTable)

**Exports:** `cost_hook`, `CostHook`

### H.15 Import graph (DAG)

```
adapter.py  (imports contracts)
  ↑
chain.py  (imports adapter, cost)
  ↑
worker.py  (imports chain)

stt.py  (imports adapter)

packer.py  (imports contracts)
  ↑
intent.py  (imports packer, adapter, contracts)
  ↑
verify.py  (imports adapter, contracts)

tools.py  (imports contracts, cost)

cost.py  (imports contracts)
  ↑
cost_hook.py  (imports cost, prices)

prices.py  (no imports from ai/)

__init__.py  (imports all)
```

No cycles. `prices.py` is a leaf. `adapter.py` and `packer.py` depend only
on `contracts/`. `chain.py` depends on `adapter.py`. `worker.py` depends on
`chain.py`. `cost_hook.py` depends on `cost.py` and `prices.py`.

---

## I. Spec ambiguities and open questions

### I.1 Cloudflare in the retry order (§5.2)

**Ambiguity:** §5.2 says "cycling Cloudflare → Groq → NIM" but §5.1 only
mentions `groq,nim` in `TEXT_PROVIDERS`. Cloudflare is not mentioned as a
configured provider anywhere else in the spec.

**Proposal:** The retry order is the order of adapters in the chain, which
comes from `TEXT_PROVIDERS` (default `groq,nim`). The "Cloudflare" mention
in §5.2 is either a leftover from an earlier draft or refers to Groq's
Cloudflare front. The chain cycles through whatever adapters are configured,
in order. Confirm with Manager.

### I.2 STT failover (§5.1, §5.2)

**Ambiguity:** The spec describes failover for text providers but does not
mention STT failover. If the STT provider is down, what happens?

**Proposal:** STT uses a single adapter (no failover). If it fails, the
error propagates to the API layer, which returns an error to the client.
STT is not on the critical path for text-based interaction. Confirm with
Manager.

### I.3 Embeddings failover (§5.1)

**Ambiguity:** The spec says "embeddings default to local `llama-embedding`,
remote as fallback." It is unclear what the remote fallback is or how
failover between local and remote embeddings works.

**Proposal:** The embeddings adapter is configured via `EMBED_*` env vars.
If the local endpoint is unavailable, the adapter raises an error. There is
no automatic failover for embeddings in Phase 2. Confirm with Manager.

### I.4 First attempt on the request path (§5.2)

**Ambiguity:** The spec says retries are "never on the request path" but
also says "A `say` or tool request returns immediately with a queued result."
It is unclear whether the first attempt is synchronous (on the request path)
or whether all attempts including the first are handled by the worker.

**Proposal:** The first attempt is synchronous (the chain tries the first
adapter immediately). If it fails with a retryable error, the chain returns
a queued result and the worker handles subsequent retries. This gives fast
responses when the first provider is up. Confirm with Manager.

### I.5 Token counting method (§5.6)

**Ambiguity:** The spec mentions a "token ceiling" but does not specify how
tokens are counted. Options: tiktoken, character-based estimate, or
provider-returned token counts.

**Proposal:** Use a deterministic character-based estimate
(`len(text) // 4`) for packing decisions. Use provider-returned token counts
for cost tracking. The estimate must be fast and consistent. Confirm with
Manager.

### I.6 Lookup-only detection heuristic (§5.3)

**Ambiguity:** The spec says "A lookup-only turn gets a second turn" but does
not specify how a lookup-only turn is detected. What counts as "lookup-only"?

**Proposal:** A turn is lookup-only if the intent result contains no
mutation tool calls (only `search_nodes`, `get_day`, `get_week`, `get_month`,
`get_briefing`, `find_free_slots`, `get_free_time`, `check_conflict`, or
`ask_question`). Confirm with Manager.

### I.7 Verify pass model selection (§5.3)

**Ambiguity:** The spec says the verify pass uses "the cheapest configured
text model." It is unclear how the cheapest model is selected from the
configured providers.

**Proposal:** The verifier uses the last adapter in the chain (the cheapest
one, typically NIM which is free). If only one adapter is configured, it
uses that one. Confirm with Manager.

### I.8 Cost table location (§5.2, §4.7)

**Ambiguity:** The spec mentions a "daily token-cost table" but does not
specify whether it is a SQLite table, a separate file, or an in-memory
structure.

**Proposal:** It is a SQLite table (`token_cost`) in the main database file,
as described in §G.7. This allows the `chronos token-cost` CLI and
`GET /api/stats` to query it. Confirm with Manager.

### I.9 Similarity threshold for duplicate detection (§5.4)

**Ambiguity:** The spec says "Above a similarity threshold the existing one
is reused rather than duplicated" but does not specify the threshold value.

**Proposal:** The threshold is configurable via a setting
(`ai.duplicate_threshold`, default `0.85`). The search backend returns
cosine similarities, and the threshold is applied to those. Confirm with
Manager.

### I.10 Reminder offset confirmation (§5.4)

**Ambiguity:** The spec says "the AI proposes its reminder offsets alongside
the slot, and the user confirms both before commit." It is unclear how this
confirmation works in the tool dispatch flow — is it a separate step or part
of the proposal/accept flow?

**Proposal:** The reminder offsets are included in the `create_event` tool
call. The user confirms them when accepting the proposal (§6 — "Proposals
render as a before/after diff and commit on acceptance"). There is no
separate confirmation step. Confirm with Manager.

---

## J. Summary

This proposal covers the complete interface surface for Phase 2:

- **A.** One `Adapter` class for text, speech, and embeddings — three
  configurations, no provider-specific code paths
- **B.** `Chain` with failover, `RetryWorker` with exponential backoff and
  jitter, `RETRY_SKIP_AFTER_SECONDS` (120), `RETRY_MAX_INFLIGHT` (8)
- **C.** STT via `transcribe_audio` using `whisper-large-v3-turbo`
- **D.** `Packer` with 5-layer priority order, token ceiling, cut records
- **E.** `IntentParser` and `Verifier` with ISO-8601 dates, lookup-only
  second turn
- **F.** `ToolDispatcher` with all 27 tools, no move tool, unbounded series
  refused
- **G.** `CostTracker`, `PriceTable` with `None` for unknown prices,
  `cost_hook.py` hooking into the chain
- **H.** 14 files in `chronos/ai/` with a DAG import graph

The proposal is detailed enough that a code agent can implement it without
re-reading the spec. All decisions are cited to the spec section. 10
ambiguities are flagged for Manager review.
