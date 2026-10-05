# Phase 3 — Interface Proposal: `chronos/api/` and `chronos/realtime/`

**Status:** FROZEN — Phase 3 proposal approved
**Manager review:** All 8 ambiguities ruled on and approved. See `docs/decisions.md`.  
**Author:** Phase-3 Proposer  
**Date:** 2026-10-03  
**Spec source:** `docs/Chronos.md` §3 (auth), §8 (server), §6 (conflict rules at commit)  
**Phase doc:** `docs/phases/phase-3-server.md`  
**Frozen contracts:** `docs/proposals/phase-1-contracts.md` (models, enums, tool schemas, protocols)

---

## 0. Scope and principles

This document proposes the complete interface surface for Phase 3. It covers:

- **A.** Auth — instance key generation, storage, verification, renewal, and the redaction guarantee.
- **B.** App factory — `create_app(db_path=None) -> FastAPI`, the load-bearing entry point.
- **C.** REST routes — all 18 routes from §8.2 with request/response models and auth requirements.
- **D.** Voice route — audio upload, STT processing, transcript return.
- **E.** Realtime hub — WebSocket endpoint `/ws`, message types, fan-out semantics.
- **F.** Smoke script — `scripts/smoke.sh` boots the real server over HTTP and runs checks.
- **G.** File layout — every file in `chronos/api/` and `chronos/realtime/` with purpose and exports.

**Principles:**

1. `chronos/contracts/` is the frozen shared surface (§2.1). Phase 3 imports from it and nothing else from its siblings.
2. `create_app(db_path=None)` is load-bearing (§8.2, phase doc). The CLI, the smoke script and the tests all call it. Do not change the signature.
3. All times are UTC epoch **milliseconds** (`INTEGER`) in the database (§4). ISO-8601 with offset at every API boundary (§7.3).
4. One instance timezone governs all bucket maths and rendering (§7.1).
5. The calendar grid is **1 minute** (§7.2).
6. Every route is a real implementation. A stub that shadows a later module's route is a bug (phase doc).
7. Single user. No roles, no registration, no multi-tenancy (§3).

---

## A. Auth (§3)

### A.1 Instance key

One **instance key**, generated on first run, printed once, stored **Argon2-hashed** (§3).

**Generation:**
- On first run (no key in settings), generate a cryptographically random key of at least 32 bytes, hex-encoded (64 chars).
- Print the key to stdout exactly once, with a warning that it will not be shown again.
- Store only the Argon2 hash in the `settings` table under the key `auth.instance_key_hash`.
- The plaintext key is never written to disk, never logged, never returned by any API after generation.

**Storage:**
- The hash is stored in `settings` table: `key = "auth.instance_key_hash"`, `value = <argon2_hash>`.
- Argon2id with default parameters (time_cost=2, memory_cost=65536, parallelism=1).
- The hash string includes the algorithm parameters and salt (standard Argon2 encoded format).

### A.2 Key verification

Every REST request, WebSocket upgrade, MCP call and CLI command requires the key (§3).

**Header:** `X-Chronos-Key: <key>`

**Query-string fallback:** `?key=<key>` — for MCP clients that cannot set headers (§3).

**Verification flow:**
1. Extract key from `X-Chronos-Key` header. If absent, extract from `?key` query parameter.
2. If no key found → 401 Unauthorized.
3. Look up `auth.instance_key_hash` from settings.
4. If no hash found (first run, key not yet generated) → 503 Service Unavailable with message "Instance key not yet generated. Run `chronos serve` first."
5. Argon2-verify the presented key against the stored hash.
6. If verification fails → 401 Unauthorized.
7. If verification succeeds → request proceeds.

### A.3 Unauthenticated routes

**`/api/health` is the only unauthenticated route** (§3, phase doc). Everything else returns 401 without a valid key.

### A.4 Query-string key redaction

**A key in a query string is never written to a log** (§3, phase doc).

This is easy to get wrong: an HTTP client logging the full URL will leak it. Redact at **record-creation time**, not with a logger-attached filter (filters do not run for descendant loggers like `httpx._client`).

**Implementation approach:**
- A custom `logging.LogRecord` factory or a `logging.Filter` attached at the root logger that scrubs the `key` parameter from any log record's `msg` or `args` before it reaches any handler.
- The redaction replaces `?key=<value>` and `&key=<value>` with `key=***` in any string that looks like a URL.
- Additionally, the `X-Chronos-Key` header value is never logged. Any middleware or exception handler that logs request headers must redact this header.
- The redaction function is applied at the point where a log record is created (in a custom `LoggerAdapter` or by overriding `Logger.makeRecord`), ensuring it runs for all descendant loggers.

### A.5 Key renewal

`chronos key-renew` rotates the key and disconnects every client (§3, phase doc).

**CLI command:** `chronos key-renew`
- Generates a new key.
- Prints the new key once.
- Updates `auth.instance_key_hash` in settings.
- Disconnects every connected WebSocket client (sends a close frame with code 4001 "key rotated").

**REST endpoint:** `POST /api/keys/renew` (§8.2)
- Authenticated (requires current key).
- Generates a new key, updates the hash, disconnects all WebSocket clients.
- Returns the new key in the response body (one time only).

### A.6 Auth module interface

**File:** `chronos/api/auth.py`

```python
# chronos/api/auth.py

import logging
import secrets
from typing import Optional

from fastapi import Request, HTTPException, WebSocket
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Re-export for convenience
from chronos.contracts import SettingsRepo, Clock

# --- Key generation ---

def generate_instance_key() -> str:
    """Generate a new cryptographically random instance key (64 hex chars)."""
    ...

# --- Key storage ---

def get_stored_hash(settings_repo: SettingsRepo) -> Optional[str]:
    """Return the stored Argon2 hash, or None if not yet generated."""
    ...

def store_instance_key(settings_repo: SettingsRepo, key: str) -> None:
    """Hash and store the instance key. Called once on first run."""
    ...

def rotate_instance_key(settings_repo: SettingsRepo) -> str:
    """Generate a new key, store its hash, return the plaintext (shown once)."""
    ...

# --- Key verification ---

def verify_instance_key(settings_repo: SettingsRepo, presented_key: str) -> bool:
    """Verify a presented key against the stored Argon2 hash."""
    ...

# --- Request extraction ---

def extract_key_from_request(request: Request) -> Optional[str]:
    """Extract the instance key from X-Chronos-Key header or ?key query param."""
    ...

def extract_key_from_websocket(websocket: WebSocket) -> Optional[str]:
    """Extract the instance key from WebSocket headers or ?key query param."""
    ...

# --- FastAPI dependencies ---

async def require_key(request: Request) -> str:
    """
    FastAPI dependency that enforces instance-key auth.
    Returns the verified key on success.
    Raises 401 if missing/invalid, 503 if key not yet generated.
    """
    ...

async def require_key_ws(websocket: WebSocket) -> str:
    """
    WebSocket auth dependency. Same logic as require_key but for WS upgrade.
    Raises WebSocketException(4001) on failure.
    """
    ...

# --- Log redaction ---

def redact_key_from_url(url: str) -> str:
    """Replace ?key=<value> and &key=<value> with key=*** in a URL string."""
    ...

class KeyRedactingLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that redacts ?key=... from all log messages.
    Applied at the root logger to cover all descendant loggers.
    """
    ...

def install_key_redaction() -> None:
    """Install the key-redacting logger adapter at the root logger."""
    ...

# --- Health (unauthenticated) ---

async def health_unauthenticated() -> dict:
    """Health check — no auth required. Returns basic server status."""
    ...
```

**Return types summary:**

| Function | Returns | Raises |
|---|---|---|
| `generate_instance_key()` | `str` (64 hex chars) | — |
| `get_stored_hash(repo)` | `Optional[str]` | — |
| `store_instance_key(repo, key)` | `None` | — |
| `rotate_instance_key(repo)` | `str` (new plaintext key) | — |
| `verify_instance_key(repo, key)` | `bool` | — |
| `extract_key_from_request(req)` | `Optional[str]` | — |
| `extract_key_from_websocket(ws)` | `Optional[str]` | — |
| `require_key(req)` | `str` (verified key) | `HTTPException(401)`, `HTTPException(503)` |
| `require_key_ws(ws)` | `str` (verified key) | `WebSocketException(4001)` |
| `redact_key_from_url(url)` | `str` | — |
| `install_key_redaction()` | `None` | — |
| `health_unauthenticated()` | `dict` | — |

---

## B. App factory (§8.2)

### B.1 `create_app` signature

**File:** `chronos/api/app.py`

```python
# chronos/api/app.py

from typing import Optional
from fastapi import FastAPI

def create_app(db_path: Optional[str] = None) -> FastAPI:
    """
    Create and configure the Chronos FastAPI application.
    
    Args:
        db_path: Path to the SQLite database file. If None, uses the default
                 path from CHRONOS_DB env var or ~/.chronos/chronos.db.
    
    Returns:
        A fully configured FastAPI app with all routes registered.
    
    This signature is load-bearing — the CLI, the smoke script and the tests
    all call it. Do not change it.
    """
    ...
```

### B.2 What `create_app` does

1. **Resolve the database path:**
   - If `db_path` is provided, use it.
   - Else check `CHRONOS_DB` environment variable.
   - Else default to `~/.chronos/chronos.db`.
   - Create parent directories if they don't exist.

2. **Open the database:**
   - Initialize the SQLAlchemy engine and session factory.
   - Run migrations (Alembic) if the schema is not current.
   - Seed buckets if the database is fresh (10 years forward, §4.3).
   - Load the instance timezone from settings.
   - Reconcile any running timer sessions (flag `reconciled = 1`, §4.7).

3. **Initialize the auth module:**
   - Install key redaction logging.
   - Check if instance key exists; if not, generate and print it.

4. **Initialize the realtime hub:**
   - Create the `RealtimeHub` instance.
   - Store it on `app.state.hub`.

5. **Register all routes:**
   - Import and include all route routers.
   - Apply the `require_key` dependency to all routes except `/api/health`.

6. **Register exception handlers:**
   - 401 for auth failures.
   - 409 for timer conflicts.
   - 422 for validation errors.
   - 500 for unexpected errors (with redaction).

7. **Register startup/shutdown events:**
   - On startup: start the realtime hub's background tasks (reminder scheduler, timer tick).
   - On shutdown: disconnect all WebSocket clients, stop background tasks.

8. **Return the FastAPI app.**

### B.3 App state

The following objects are stored on `app.state` for access by route handlers:

| Attribute | Type | Purpose |
|---|---|---|
| `app.state.db_path` | `str` | Resolved database file path |
| `app.state.engine` | `sqlalchemy.engine.Engine` | SQLAlchemy engine |
| `app.state.session_factory` | `sessionmaker` | Session factory |
| `app.state.settings_repo` | `SettingsRepo` | Settings repository |
| `app.state.clock` | `Clock` | Clock instance |
| `app.state.hub` | `RealtimeHub` | Realtime hub instance |
| `app.state.timezone` | `str` | Instance timezone (IANA name) |
| `app.state.api_key_hash` | `Optional[str]` | Current instance key hash |

---

## C. REST routes (§8.2)

All 18 routes from the spec. Every route except `/api/health` requires authentication via the `require_key` dependency.

### C.1 Route summary table

| # | Method | Path | Auth | Request | Response |
|---|---|---|---|---|---|
| 1 | POST | `/api/voice` | yes | `multipart/form-data` (audio file) | `VoiceResponse` |
| 2 | POST | `/api/say` | yes | `SayRequest` | `SayResponse` |
| 3 | POST | `/api/commands` | yes | `CommandRequest` | `CommandResponse` |
| 4 | GET | `/api/events` | yes | query: `from`, `to` | `list[Event]` |
| 5 | GET | `/api/nodes` | yes | query: `parent`, `tag` | `list[Node]` |
| 6 | GET | `/api/buckets` | yes | query: `level`, `date` | `list[Bucket]` |
| 7 | GET | `/api/briefing` | yes | query: `date` | `BriefingResponse` |
| 8 | GET | `/api/search` | yes | query: `q`, `limit` | `list[Node]` |
| 9 | GET | `/api/reminders` | yes | — | `list[Reminder]` |
| 10 | POST | `/api/timer/start` | yes | `TimerStartRequest` | `TimerSession` |
| 11 | POST | `/api/timer/stop` | yes | `TimerStopRequest` | `TimerSession` |
| 12 | GET | `/api/timer` | yes | query: `node_id` | `TimerSession \| null` |
| 13 | GET | `/api/timer/summary` | yes | query: `node_id` | `TimerSummary` |
| 14 | GET | `/api/timer/presets` | yes | — | `list[PomodoroPreset]` |
| 15 | POST | `/api/timer/presets` | yes | `PomodoroPreset` | `PomodoroPreset` |
| 16 | GET | `/api/stats` | yes | — | `StatsResponse` |
| 17 | GET | `/api/settings` | yes | — | `dict[str, str]` |
| 18 | PUT | `/api/settings` | yes | `dict[str, str]` | `dict[str, str]` |
| 19 | POST | `/api/keys/renew` | yes | — | `KeyRenewResponse` |
| 20 | GET | `/api/health` | **no** | — | `HealthResponse` |

### C.2 Route details

#### C.2.1 `POST /api/voice` — Audio to transcript

**Spec:** §8.2, §9.1 (mic button streams to `/api/voice`)

**Request:** `multipart/form-data`
- `audio`: binary audio file (required). Supported formats: `webm/opus`, `mp3`, `wav`, `ogg`.
- `language`: string (optional, BCP-47 language code). Default: auto-detect.

**Response:** `VoiceResponse`
```python
class VoiceResponse(BaseModel):
    transcript: str
    confidence: Optional[float] = None
    language: Optional[str] = None
```

**Behavior:**
- Accepts audio upload.
- Sends to STT provider (Groq Whisper `whisper-large-v3-turbo`, §5.1).
- Returns the transcript text.
- The client appends the transcript to the input box (§9.1).

**Errors:**
- 400 if no audio file provided.
- 415 if audio format not supported.
- 502 if STT provider fails.

#### C.2.2 `POST /api/say` — Text to intent to proposal to commit

**Spec:** §8.2, §5.3 (Understand → Verify → Commit), §6 (conflict rules)

**Request:** `SayRequest`
```python
class SayRequest(BaseModel):
    text: str
    device_id: Optional[str] = None
```

**Response:** `SayResponse`
```python
class SayResponse(BaseModel):
    intent: str                          # classified intent
    tool_calls: list[ToolCall]           # proposed tool calls
    proposal_id: Optional[str] = None    # set if proposal needs acceptance
    committed: bool                      # True if auto-committed, False if pending
    events: list[Event] = []             # created/updated events
    message: Optional[str] = None        # human-readable summary
```

**Behavior:**
1. Run the intent pipeline (§5.3): Understand → Verify → tool calls.
2. If the tool calls are lookup-only (no mutations), execute and return results.
3. If the tool calls propose mutations:
   - Run conflict checks (§6): hard slot conflict, semantic duplicate check.
   - If no conflicts: commit immediately, return `committed=True`.
   - If conflicts or ambiguous: create a proposal, return `committed=False` with `proposal_id`.
4. The proposal is broadcast to all WebSocket clients (§8.3).

**Errors:**
- 400 if text is empty.
- 502 if AI provider fails.

#### C.2.3 `POST /api/commands` — Raw tool call

**Spec:** §8.2, §5.5 (tool set)

**Request:** `CommandRequest`
```python
class CommandRequest(BaseModel):
    tool: str                           # one of the 27 tool names
    arguments: dict[str, Any] = {}
    device_id: Optional[str] = None
```

**Response:** `CommandResponse`
```python
class CommandResponse(BaseModel):
    tool: str
    result: ToolResult
    events: list[Event] = []
    proposal_id: Optional[str] = None
```

**Behavior:**
- Dispatches a single tool call from the 27-tool set (§5.5).
- Runs the same validation as `/api/say`.
- Returns the tool result.
- If the tool creates events, they are included in the response.

**Errors:**
- 400 if tool name is unknown.
- 422 if arguments fail schema validation.
- 502 if execution fails.

#### C.2.4 `GET /api/events` — Range query

**Spec:** §8.2, §4.2

**Query parameters:**
- `from`: ISO-8601 datetime (required). Start of range.
- `to`: ISO-8601 datetime (required). End of range.

**Response:** `list[Event]` — all non-soft-deleted events in the range.

**Behavior:**
- Converts ISO-8601 to epoch ms using the instance timezone (§7.1).
- Returns events where `start_ms < to_ms AND end_ms > from_ms`.
- Soft-deleted events are excluded.

#### C.2.5 `GET /api/nodes` — Tree query

**Spec:** §8.2, §4.1

**Query parameters:**
- `parent`: string (optional). Parent node id. If omitted, returns root nodes.
- `tag`: string (optional). Tag name filter.

**Response:** `list[Node]` — child nodes matching the filter.

**Behavior:**
- If `parent` is provided, returns direct children of that node.
- If `parent` is omitted, returns root nodes (parent_id IS NULL).
- If `tag` is provided, filters to nodes that have that tag.
- Tags apply to tasks and subtasks, never projects (§4.1).

#### C.2.6 `GET /api/buckets` — Bucket contents

**Spec:** §8.2, §4.3

**Query parameters:**
- `level`: `BucketLevel` (required). One of `Y`, `M`, `W`, `D`.
- `date`: ISO-8601 date (optional). If provided, returns the bucket containing that date and its children.

**Response:** `list[Bucket]`

**Behavior:**
- If `date` is provided, resolves the bucket at `level` that contains that date, then returns its children.
- If `date` is omitted, returns all buckets at `level`.

#### C.2.7 `GET /api/briefing` — Daily briefing

**Spec:** §8.2, §9.1, §5.7

**Query parameters:**
- `date`: ISO-8601 date (optional). Default: today in instance timezone.

**Response:** `BriefingResponse`
```python
class BriefingResponse(BaseModel):
    date: str
    unallocated_tasks: list[Node]
    rollover: list[Node]
    due_reviews: list[Event]
    question: Optional[str] = None
```

**Behavior:**
- Returns the daily briefing: unallocated tasks for today, unallocated tasks for this week, rollover, due reviews, and at most one question (§5.7).
- The clarification budget is one question per day (§5.7).

#### C.2.8 `GET /api/search` — Keyword + semantic

**Spec:** §8.2, §4.8, §6

**Query parameters:**
- `q`: string (required). Search query.
- `limit`: integer (optional, default 10, max 50).

**Response:** `list[Node]` — search results with scores.

**Behavior:**
- Three-stage search (§4.8): FTS5 narrows candidates, sqlite-vec ranks by cosine similarity, model judges duplicates.
- Degrade gracefully: missing vec table means keywords only, never raise (decisions.md).
- Scores are absolute, not normalized (phase-5 doc).

#### C.2.9 `GET /api/reminders` — Pending reminders

**Spec:** §8.2, §4.6

**Response:** `list[Reminder]` — all reminders with state `pending`.

**Behavior:**
- Returns pending reminders ordered by `fire_at_ms`.

#### C.2.10 `POST /api/timer/start` — Start timer

**Spec:** §8.2, §4.7, decisions.md (refuse if one running)

**Request:** `TimerStartRequest`
```python
class TimerStartRequest(BaseModel):
    node_id: Optional[str] = None
    label: str
    mode: TimerMode                    # stopwatch | timer | pomodoro
    target_ms: Optional[int] = None    # ignored for stopwatch
    source: str                        # device id
```

**Response:** `TimerSession`

**Behavior:**
- If a timer is already running → **409 Conflict** with message "A timer is already running. Stop it first." (decisions.md, phase doc).
- A stopwatch ignores `target_ms` — it must not become a countdown (§4.7, phase doc).
- Creates a new `TimerSession` row.
- Broadcasts `timer` message to all WebSocket clients.

#### C.2.11 `POST /api/timer/stop` — Stop timer

**Spec:** §8.2, §4.7

**Request:** `TimerStopRequest`
```python
class TimerStopRequest(BaseModel):
    source: str                        # device id
```

**Response:** `TimerSession`

**Behavior:**
- Stops the running timer (sets `ended_at`).
- If no timer is running → 409 Conflict.
- Broadcasts `timer` message to all WebSocket clients.

#### C.2.12 `GET /api/timer` — Running timer

**Spec:** §8.2, §4.7

**Query parameters:**
- `node_id`: string (optional). If provided, returns the running timer for that node.

**Response:** `TimerSession | null`

**Behavior:**
- Returns the currently running timer, or null if none.
- If `node_id` is provided, filters to that node.

#### C.2.13 `GET /api/timer/summary` — Logged time + project rollup

**Spec:** §8.2, §4.7

**Query parameters:**
- `node_id`: string (required).

**Response:** `TimerSummary`
```python
class TimerSummary(BaseModel):
    node_total_ms: int
    descendant_total_ms: int
    project_total_ms: int
```

**Behavior:**
- Reports per node: the node's own total, the total including descendants, and the project total for a tagged task (§4.7).
- The project is resolved by walking `parent_id` up to the nearest ancestor project.
- Pomodoro breaks are excluded from work totals (§4.7).

#### C.2.14 `GET /api/timer/presets` — List pomodoro presets

**Spec:** §8.2, §4.7

**Response:** `list[PomodoroPreset]`
```python
class PomodoroPreset(BaseModel):
    name: str
    focus_minutes: int
    break_minutes: int
    cycles: int
```

**Behavior:**
- Returns custom pomodoro presets from the `timer.pomodoro_presets` setting.
- Always includes the default 25/5 × 4 preset.
- An unreadable stored value falls back to the default (§4.7).

#### C.2.15 `POST /api/timer/presets` — Add pomodoro preset

**Spec:** §8.2, §4.7

**Request:** `PomodoroPreset`

**Response:** `PomodoroPreset` — the created preset.

**Behavior:**
- Adds a custom pomodoro preset to the `timer.pomodoro_presets` setting.
- Presets are stored as a JSON list under the setting key.

#### C.2.16 `GET /api/stats` — Counts, streaks, token spend

**Spec:** §8.2, §4.7

**Response:** `StatsResponse`
```python
class StatsResponse(BaseModel):
    total_nodes: int
    active_nodes: int
    done_nodes: int
    total_events: int
    events_today: int
    current_streak_days: int
    longest_streak_days: int
    token_spend_by_day: list[TokenSpendEntry]

class TokenSpendEntry(BaseModel):
    date: str          # ISO-8601 date
    total_cost_usd: Optional[float]
    total_tokens: int
    request_count: int
```

**Behavior:**
- Returns counts, streaks, and token spend by day.
- `cost_usd` is `None` when the price is unknown — never a fake `0.0` (§5.2, phase-2 doc).

#### C.2.17 `GET /api/settings` — Get all settings

**Spec:** §8.2

**Response:** `dict[str, str]` — all settings key-value pairs.

**Behavior:**
- Returns all settings except `auth.instance_key_hash` (never exposed).

#### C.2.18 `PUT /api/settings` — Update settings

**Spec:** §8.2

**Request:** `dict[str, str]` — settings to update.

**Response:** `dict[str, str]` — all settings after update.

**Behavior:**
- Updates the provided settings.
- Rejects updates to `auth.instance_key_hash` (use `/api/keys/renew` instead).
- Changing the timezone re-buckets existing events and is audited (§7.1).

#### C.2.19 `POST /api/keys/renew` — Rotate instance key

**Spec:** §8.2, §3

**Response:** `KeyRenewResponse`
```python
class KeyRenewResponse(BaseModel):
    new_key: str
    message: str = "Instance key rotated. All clients disconnected."
```

**Behavior:**
- Generates a new instance key.
- Updates the stored hash.
- Disconnects all WebSocket clients (close code 4001).
- Returns the new key (one time only).

#### C.2.20 `GET /api/health` — Health check (unauthenticated)

**Spec:** §8.2, §11

**Response:** `HealthResponse`
```python
class HealthResponse(BaseModel):
    status: str              # "ok"
    version: str
    db_path: str
    uptime_seconds: float
```

**Behavior:**
- The only unauthenticated route (§3).
- Returns basic server status for clients to show "server is down" vs "spinner" (§11).

---

## D. Voice route (§8.2)

### D.1 Audio upload

The voice route accepts audio via `multipart/form-data` POST to `/api/voice`.

**Supported formats:** `webm/opus` (default from browser `MediaRecorder`), `mp3`, `wav`, `ogg`.

**Size limit:** 25 MB (configurable via `MAX_AUDIO_SIZE_MB` env var).

### D.2 STT processing

1. Receive the audio file.
2. Determine the content type from the `Content-Type` header.
3. Send to the STT provider (Groq Whisper `whisper-large-v3-turbo`, §5.1).
4. The STT provider returns the transcript text.
5. Return the transcript in the `VoiceResponse`.

### D.3 Transcript return

The response is a `VoiceResponse` with the transcript text. The client (web HUD, Android app) appends the transcript to the input box after existing content (§9.1).

### D.4 Error handling

- 400 if no audio file provided.
- 415 if audio format not supported.
- 413 if audio file exceeds size limit.
- 502 if STT provider fails (with retry/failover per §5.2).

---

## E. Realtime hub (§8.3)

### E.1 WebSocket endpoint

**Path:** `/ws`

**Connection:** One connection per client, authenticated on upgrade (§8.3).

**Authentication:** The client must provide the instance key either:
- In the `X-Chronos-Key` header during the WebSocket handshake, or
- As a `?key=<key>` query parameter in the WebSocket URL.

If authentication fails, the server rejects the upgrade with close code 4001.

### E.2 Server → client messages

All messages are JSON objects with a `type` field.

#### E.2.1 `state` — Full snapshot on connect

Sent immediately after authentication succeeds.

```json
{
  "type": "state",
  "nodes": [...],
  "events_today": [...],
  "running_timer": {...} | null,
  "pending_proposals": [...],
  "pending_questions": [...]
}
```

#### E.2.2 `patch` — Incremental change

Sent when a mutation occurs.

```json
{
  "type": "patch",
  "ops": [
    {"op": "insert", "table": "events", "row": {...}},
    {"op": "update", "table": "events", "id": "...", "changes": {...}},
    {"op": "delete", "table": "events", "id": "..."}
  ]
}
```

#### E.2.3 `proposal` — Awaiting accept

Sent when a proposal is created that needs user acceptance.

```json
{
  "type": "proposal",
  "proposal_id": "...",
  "tool_calls": [...],
  "diff": {...},
  "conflicts": [...]
}
```

#### E.2.4 `question` — Clarification

Sent when the AI asks a clarification question.

```json
{
  "type": "question",
  "question_id": "...",
  "question": "...",
  "context": "..."
}
```

#### E.2.5 `timer` — Tick, start, stop

Sent on timer state changes and periodic ticks.

```json
{
  "type": "timer",
  "action": "start" | "stop" | "tick",
  "session": {...},
  "elapsed_ms": 12345
}
```

#### E.2.6 `queued` — Retry job accepted

Sent when a retry job is accepted and work is in progress.

```json
{
  "type": "queued",
  "id": "...",
  "provider": "groq"
}
```

#### E.2.7 `retrying` — Retry attempt

Sent on each retry attempt.

```json
{
  "type": "retrying",
  "attempt": 2,
  "provider": "nim",
  "error": "429 Too Many Requests"
}
```

### E.3 Client → server messages

#### E.3.1 `hello` — Client identification

Sent by the client after connecting.

```json
{
  "type": "hello",
  "key": "<instance_key>",
  "device": "<device_id>"
}
```

The `key` field is used for authentication if not provided in headers/query. The `device` field identifies the client device.

#### E.3.2 `say` — Text input

```json
{
  "type": "say",
  "text": "schedule DB review tomorrow 4pm for 45 mins"
}
```

Triggers the same intent → proposal → commit pipeline as `POST /api/say`.

#### E.3.3 `accept` / `reject` / `skip` — Proposal response

```json
{
  "type": "accept",
  "proposal_id": "..."
}
```

```json
{
  "type": "reject",
  "proposal_id": "..."
}
```

```json
{
  "type": "skip",
  "proposal_id": "..."
}
```

- `accept`: commits the proposal.
- `reject`: discards the proposal.
- `skip`: dismisses the proposal without committing or rejecting (rolls to next).

### E.4 Fan-out semantics

**One hub, many clients: every mutation broadcasts to all of them** (§8.3, phase doc).

- The `RealtimeHub` maintains a set of connected WebSocket clients.
- Every mutation (event created, node updated, timer started, etc.) triggers a `patch` message broadcast to all connected clients.
- Proposals, questions, timer updates, and retry status are also broadcast to all clients.
- Concurrent writes serialize on SQLite's write lock; readers never block (§8.3).

### E.5 Realtime hub module interface

**File:** `chronos/realtime/hub.py`

```python
# chronos/realtime/hub.py

from typing import Set, Optional
from fastapi import WebSocket
from chronos.contracts import Clock

class RealtimeHub:
    """
    Manages WebSocket connections and broadcasts messages to all clients.
    One hub, many clients: every mutation broadcasts to all (§8.3).
    """
    
    def __init__(self, clock: Clock) -> None:
        self._clients: Set[WebSocket] = set()
        self._clock = clock
    
    async def connect(self, websocket: WebSocket) -> None:
        """Register a new WebSocket client."""
        ...
    
    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket client."""
        ...
    
    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients."""
        ...
    
    async def send_to(self, websocket: WebSocket, message: dict) -> None:
        """Send a message to a specific client."""
        ...
    
    async def close_all(self, code: int = 4001, reason: str = "") -> None:
        """Close all connections (used on key rotation)."""
        ...
    
    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        ...
    
    # --- Message builders ---
    
    def build_state_message(self, ...) -> dict:
        """Build a 'state' message with full snapshot."""
        ...
    
    def build_patch_message(self, ops: list[dict]) -> dict:
        """Build a 'patch' message."""
        ...
    
    def build_proposal_message(self, proposal_id: str, ...) -> dict:
        """Build a 'proposal' message."""
        ...
    
    def build_question_message(self, question_id: str, ...) -> dict:
        """Build a 'question' message."""
        ...
    
    def build_timer_message(self, action: str, session: dict, ...) -> dict:
        """Build a 'timer' message."""
        ...
    
    def build_queued_message(self, job_id: str, provider: str) -> dict:
        """Build a 'queued' message."""
        ...
    
    def build_retrying_message(self, attempt: int, provider: str, error: str) -> dict:
        """Build a 'retrying' message."""
        ...
```

**File:** `chronos/realtime/protocol.py`

```python
# chronos/realtime/protocol.py

from typing import Literal, Optional, Union
from pydantic import BaseModel

# Server → client message types

class StateMessage(BaseModel):
    type: Literal["state"]
    nodes: list[dict]
    events_today: list[dict]
    running_timer: Optional[dict]
    pending_proposals: list[dict]
    pending_questions: list[dict]

class PatchMessage(BaseModel):
    type: Literal["patch"]
    ops: list[dict]

class ProposalMessage(BaseModel):
    type: Literal["proposal"]
    proposal_id: str
    tool_calls: list[dict]
    diff: dict
    conflicts: list[dict]

class QuestionMessage(BaseModel):
    type: Literal["question"]
    question_id: str
    question: str
    context: Optional[str] = None

class TimerMessage(BaseModel):
    type: Literal["timer"]
    action: Literal["start", "stop", "tick"]
    session: dict
    elapsed_ms: int

class QueuedMessage(BaseModel):
    type: Literal["queued"]
    id: str
    provider: str

class RetryingMessage(BaseModel):
    type: Literal["retrying"]
    attempt: int
    provider: str
    error: str

ServerMessage = Union[
    StateMessage, PatchMessage, ProposalMessage, QuestionMessage,
    TimerMessage, QueuedMessage, RetryingMessage
]

# Client → server message types

class HelloMessage(BaseModel):
    type: Literal["hello"]
    key: str
    device: str

class SayMessage(BaseModel):
    type: Literal["say"]
    text: str

class AcceptMessage(BaseModel):
    type: Literal["accept"]
    proposal_id: str

class RejectMessage(BaseModel):
    type: Literal["reject"]
    proposal_id: str

class SkipMessage(BaseModel):
    type: Literal["skip"]
    proposal_id: str

ClientMessage = Union[
    HelloMessage, SayMessage, AcceptMessage, RejectMessage, SkipMessage
]
```

**File:** `chronos/realtime/__init__.py`

```python
# chronos/realtime/__init__.py

from .hub import RealtimeHub
from .protocol import (
    StateMessage, PatchMessage, ProposalMessage, QuestionMessage,
    TimerMessage, QueuedMessage, RetryingMessage,
    HelloMessage, SayMessage, AcceptMessage, RejectMessage, SkipMessage,
    ServerMessage, ClientMessage,
)

__all__ = [
    "RealtimeHub",
    "StateMessage", "PatchMessage", "ProposalMessage", "QuestionMessage",
    "TimerMessage", "QueuedMessage", "RetryingMessage",
    "HelloMessage", "SayMessage", "AcceptMessage", "RejectMessage", "SkipMessage",
    "ServerMessage", "ClientMessage",
]
```

---

## F. Smoke script

### F.1 `scripts/smoke.sh`

Boots the real server over HTTP and runs checks. This is the gate — a green unit suite is not a running app (phase doc).

```bash
#!/usr/bin/env bash
# scripts/smoke.sh — Boot the real server and run smoke checks.
# Usage: ./scripts/smoke.sh [PORT]
# Default port: 8099

set -euo pipefail

PORT="${1:-8099}"
DB_PATH="$(mktemp -u /tmp/chronos-smoke-XXXXXX.db)"
BASE_URL="http://127.0.0.1:${PORT}"
LOG_FILE="$(mktemp -u /tmp/chronos-smoke-XXXXXX.log)"

cleanup() {
    rm -f "$DB_PATH" "$LOG_FILE"
}
trap cleanup EXIT

echo "=== Chronos smoke test ==="
echo "Port: $PORT"
echo "DB:   $DB_PATH"
echo ""

# 1. Boot the server
echo "[1/8] Booting server..."
CHRONOS_DB="$DB_PATH" .venv/bin/python -m chronos.cli serve --port "$PORT" --db "$DB_PATH" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!

# Wait for health endpoint
for i in $(seq 1 30); do
    if curl -sf "$BASE_URL/api/health" > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if ! curl -sf "$BASE_URL/api/health" > /dev/null 2>&1; then
    echo "FAIL: server did not become healthy"
    cat "$LOG_FILE"
    exit 1
fi
echo "  Server is healthy."

# 2. Health is unauthenticated
echo "[2/8] Health endpoint is unauthenticated..."
HEALTH=$(curl -sf "$BASE_URL/api/health")
echo "$HEALTH" | grep -q '"status":"ok"' || { echo "FAIL: health not ok"; exit 1; }
echo "  Health OK."

# 3. Authenticated routes reject missing key
echo "[3/8] Authenticated routes reject missing key..."
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/events?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z")
[ "$CODE" = "401" ] || { echo "FAIL: expected 401, got $CODE"; exit 1; }
echo "  401 without key OK."

# 4. Extract the instance key from the server log
echo "[4/8] Extracting instance key..."
INSTANCE_KEY=$(grep -oP 'Instance key: \K[a-f0-9]{64}' "$LOG_FILE" | head -1)
if [ -z "$INSTANCE_KEY" ]; then
    echo "FAIL: could not extract instance key from log"
    cat "$LOG_FILE"
    exit 1
fi
echo "  Key extracted."

# 5. Authenticated request with key
echo "[5/8] Authenticated request with key..."
EVENTS=$(curl -sf -H "X-Chronos-Key: $INSTANCE_KEY" \
    "$BASE_URL/api/events?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z")
echo "$EVENTS" | grep -q '\[' || { echo "FAIL: events not a list"; exit 1; }
echo "  Authenticated request OK."

# 6. Query-string key works
echo "[6/8] Query-string key fallback..."
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/events?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z&key=$INSTANCE_KEY")
[ "$CODE" = "200" ] || { echo "FAIL: query-string key got $CODE"; exit 1; }
echo "  Query-string key OK."

# 7. Key in query string is redacted in logs
echo "[7/8] Query-string key is redacted in logs..."
if grep -q "$INSTANCE_KEY" "$LOG_FILE"; then
    echo "FAIL: instance key found in log file"
    exit 1
fi
echo "  Key not in logs OK."

# 8. Timer start/stop cycle
echo "[8/8] Timer start/stop cycle..."
TIMER=$(curl -sf -X POST -H "X-Chronos-Key: $INSTANCE_KEY" \
    -H "Content-Type: application/json" \
    -d '{"label":"smoke test","mode":"stopwatch","source":"smoke"}' \
    "$BASE_URL/api/timer/start")
echo "$TIMER" | grep -q '"id"' || { echo "FAIL: timer not started"; exit 1; }

# Starting a second timer must return 409
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "X-Chronos-Key: $INSTANCE_KEY" \
    -H "Content-Type: application/json" \
    -d '{"label":"second","mode":"stopwatch","source":"smoke"}' \
    "$BASE_URL/api/timer/start")
[ "$CODE" = "409" ] || { echo "FAIL: expected 409 for second timer, got $CODE"; exit 1; }

# Stop the timer
curl -sf -X POST -H "X-Chronos-Key: $INSTANCE_KEY" \
    -H "Content-Type: application/json" \
    -d '{"source":"smoke"}' \
    "$BASE_URL/api/timer/stop" > /dev/null
echo "  Timer cycle OK."

# Shutdown
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo ""
echo "=== All smoke checks passed ==="
```

---

## G. File layout

Every file in `chronos/api/` and `chronos/realtime/` with its purpose and exports.

```
chronos/api/
  __init__.py          — re-exports create_app, auth module, route types
  app.py               — create_app factory, app state, startup/shutdown
  auth.py              — instance key generation, verification, renewal, redaction
  routes.py            — all 18 REST route handlers
  voice.py             — audio upload, STT processing, transcript return
  dependencies.py      — FastAPI dependency injection helpers

chronos/realtime/
  __init__.py          — re-exports RealtimeHub and protocol types
  hub.py               — RealtimeHub class, connection management, broadcast
  protocol.py          — WebSocket message types (server→client, client→server)
```

### G.1 `chronos/api/__init__.py`

**Purpose:** Re-exports the public API surface.

**Exports:**
- `create_app` from `app`
- `auth` module (all public names from `auth.py`)
- Route request/response models from `routes`

### G.2 `chronos/api/app.py`

**Purpose:** The `create_app` factory — the load-bearing entry point.

**Imports:** `fastapi`, `sqlalchemy`, `chronos.contracts`, `chronos.db`, `chronos.api.auth`, `chronos.api.routes`, `chronos.realtime`

**Exports:** `create_app`

### G.3 `chronos/api/auth.py`

**Purpose:** Instance key lifecycle and request authentication.

**Imports:** `argon2`, `fastapi`, `logging`, `secrets`, `chronos.contracts`

**Exports:** See A.6 for the full list.

### G.4 `chronos/api/routes.py`

**Purpose:** All 18 REST route handlers.

**Imports:** `fastapi`, `chronos.contracts`, `chronos.api.auth`, `chronos.api.voice`, `chronos.realtime`

**Exports:**
- Route request models: `SayRequest`, `CommandRequest`, `TimerStartRequest`, `TimerStopRequest`, `PomodoroPreset`
- Route response models: `VoiceResponse`, `SayResponse`, `CommandResponse`, `BriefingResponse`, `TimerSummary`, `StatsResponse`, `KeyRenewResponse`, `HealthResponse`, `TokenSpendEntry`
- Router: `router` (a `fastapi.APIRouter` with all routes registered)

### G.5 `chronos/api/voice.py`

**Purpose:** Audio upload and STT processing.

**Imports:** `fastapi`, `chronos.ai.providers.stt`, `chronos.contracts`

**Exports:** `router` (APIRouter with the `/api/voice` route), `VoiceResponse`

### G.6 `chronos/api/dependencies.py`

**Purpose:** FastAPI dependency injection helpers.

**Imports:** `fastapi`, `chronos.contracts`

**Exports:**
- `get_db` — yields a SQLAlchemy session
- `get_settings_repo` — yields a SettingsRepo
- `get_clock` — yields the Clock instance
- `get_hub` — yields the RealtimeHub instance

### G.7 `chronos/realtime/__init__.py`

**Purpose:** Re-exports the realtime module's public surface.

**Exports:** See E.5 for the full list.

### G.8 `chronos/realtime/hub.py`

**Purpose:** WebSocket connection management and message broadcasting.

**Imports:** `fastapi`, `chronos.contracts`

**Exports:** `RealtimeHub`

### G.9 `chronos/realtime/protocol.py`

**Purpose:** WebSocket message type definitions.

**Imports:** `pydantic`, `typing`

**Exports:** See E.5 for the full list.

---

## H. Import graph (DAG)

```
chronos/contracts/  (frozen, Phase 1)
  ↑
chronos/api/auth.py  (imports contracts)
  ↑
chronos/api/voice.py  (imports contracts, ai.providers.stt)
  ↑
chronos/api/routes.py  (imports contracts, auth, voice, realtime)
  ↑
chronos/api/app.py  (imports contracts, db, auth, routes, realtime)
  ↑
chronos/api/__init__.py  (imports app, auth, routes)

chronos/realtime/protocol.py  (no imports from siblings)
  ↑
chronos/realtime/hub.py  (imports contracts, protocol)
  ↑
chronos/realtime/__init__.py  (imports hub, protocol)
```

No cycles. `auth.py` depends only on `contracts`. `routes.py` depends on `contracts`, `auth`, `voice`, and `realtime`. `app.py` depends on everything.

---

## I. Spec ambiguities and open questions

1. **`POST /api/say` auto-commit vs. always propose (§8.2, §6):** The spec says "text → intent → proposal → commit" and "runs propose → verify → commit and returns the result." It is unclear whether every `say` call produces a proposal that requires explicit acceptance, or whether simple unambiguous commands auto-commit. **Proposal:** If the tool calls are lookup-only or unambiguous with no conflicts, auto-commit and return `committed=True`. If there are conflicts or ambiguity, create a proposal and return `committed=False`. Confirm with Manager.

2. **`POST /api/commands` vs. `/api/say` overlap (§8.2):** Both routes accept tool calls. The distinction is unclear. **Proposal:** `/api/say` is the natural-language entry point (text → intent → tool calls), while `/api/commands` is the raw tool-call entry point for CLI and MCP clients that already know which tool to call. Confirm with Manager.

3. **WebSocket `hello` message key vs. header/query key (§8.3):** The spec shows `{type:"hello", key, device}` as a client→server message, but also says "authenticated on upgrade." **Proposal:** The key is extracted from headers or query string during the upgrade handshake. The `key` field in the `hello` message is a fallback for clients that cannot set headers or query params. If the key was already validated during upgrade, the `hello` key is ignored. Confirm with Manager.

4. **`GET /api/timer` without `node_id` (§8.2):** The spec shows `GET /api/timer?node_id` but it is unclear what happens when `node_id` is omitted. **Proposal:** Return the currently running timer regardless of node, or null if none. Confirm with Manager.

5. **`PUT /api/settings` partial update (§8.2):** It is unclear whether PUT replaces all settings or merges. **Proposal:** Merge — only the provided keys are updated, others are preserved. Confirm with Manager.

6. **`POST /api/timer/presets` — update vs. append (§8.2):** It is unclear whether POST replaces the preset list or appends. **Proposal:** Append — the new preset is added to the existing list. Confirm with Manager.

7. **Voice audio format support (§8.2):** The spec does not specify which audio formats the STT provider accepts. **Proposal:** Support `webm/opus` (browser default), `mp3`, `wav`, `ogg`. Reject others with 415. Confirm with Manager.

8. **`/api/health` response fields (§8.2):** The spec does not define the response schema. **Proposal:** Return `status`, `version`, `db_path`, `uptime_seconds`. Confirm with Manager.

---

## J. Summary

This proposal covers the complete interface surface for Phase 3:

- **Auth module** with instance key generation, Argon2 storage, header/query extraction, log redaction, and key renewal.
- **App factory** `create_app(db_path=None) -> FastAPI` — the load-bearing entry point.
- **18 REST routes** with request/response models, auth requirements, and behavior specs.
- **Voice route** with audio upload, STT processing, and transcript return.
- **Realtime hub** with WebSocket endpoint, 7 server→client message types, 5 client→server message types, and fan-out semantics.
- **Smoke script** that boots the real server and runs 8 checks.
- **9 files** across `chronos/api/` and `chronos/realtime/` with a DAG import graph.

The proposal is detailed enough that a code agent can implement it without re-reading the spec. All decisions are cited to the spec section. All models, enums, and tool schemas reference the frozen contracts from `docs/proposals/phase-1-contracts.md`.
