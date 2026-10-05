# Chronos — Technical Contracts Digest

Source: `docs/server/proposals/phase-{1..6}-*.md` (261 KB, all 6 read once, 2026-10-03).
All six docs claim status **FROZEN / Manager-approved** (ambiguities ruled on in `docs/decisions.md`).

---

## 0. Global invariants (repeat in all six docs)

| Rule | Value |
|---|---|
| Storage time unit | UTC epoch **ms** INTEGER in DB; ISO-8601 **with offset** at every API boundary |
| Timezone | one instance tz governs all bucket maths/rendering (`app.state.timezone`, IANA name) |
| Calendar grid | **1 minute** |
| Import rule | every module imports only `chronos/contracts/`; DAG, no cycles |
| `contracts/` | frozen shared surface; changes only by announced act (Phase 5 announces 10 additions) |
| Auth model | single user, one instance key, no roles/registration/multi-tenancy |
| Date args to tools | absolute ISO-8601 in instance tz; model never emits "day 8" |
| Unknown price | `None`, **never** fake `0.0` |
| Failover | never raises to caller (absolute) |
| DB story | one SQLite file; copy = backup |

---

## 1. Phase 1 — `chronos/contracts/` (FROZEN)

### 1.1 File layout (6 files)
```
contracts/__init__.py   re-exports all
contracts/enums.py      leaf, imports only `enum`
contracts/models.py     imports enums
contracts/tool_schemas.py  imports models, enums
contracts/protocols.py  imports models, enums
contracts/ddl.py        leaf, no contracts imports
```

### 1.2 Models (10 frozen dataclasses; field order = constructor order)
`Node`, `Tag`, `NodeTag`, `Event`, `Bucket`, `ReviewSeries`, `Schedule`, `Reminder`,
`TimerSession`, `AuditEntry`.

Load-bearing field contracts:
- `Node`: id/parent_id(FK self, CASCADE)/kind/title/notes/status(default active)/created_at/updated_at/done_at
- `Event`: node_id nullable (=ad-hoc), start_ms/end_ms, kind default focus, bucket_id nullable FK,
  series_id, review_index (1..N), derived_from, soft_deleted(bool→INTEGER 0/1), created_at
- `Bucket`: **id format** `Y:2026` / `M:2026-08` / `W:2026-W31` / `D:2026-08-04`; level, parent_id,
  start_ms/end_ms, seq (1-based ordinal, NOT capped at 4 despite spec wording)
- `ReviewSeries`: tier, offsets_days (JSON int array), anchor_node_id, max_count, ends_on_ms, state;
  **CHECK (max_count IS NOT NULL OR ends_on_ms IS NOT NULL)** — series must be bounded
- `Schedule`: starts_ms/ends_at_ms, start_minute (0..1439), duration_min, weekdays (JSON [1..7] ISO),
  hard_block default True, paused default False
- `Reminder`: fire_at_ms, offset_min (positive = before; `fire_at = start_ms - offset*60000`),
  state default pending, channel default `"ntfy"`
- `TimerSession`: started_at, ended_at (NULL=running), source(device), reconciled, mode,
  target_ms, phase(pomodoro only), cycle default 1
- `AuditEntry`: **id INTEGER PRIMARY KEY autoincrement** (SQLite rowid alias), at, device_id,
  action, target, context, cost_usd

### 1.3 Enums (9, all `str`-based so they serialize straight to TEXT)
`NodeKind` project|task|subtask · `NodeStatus` active|done|archived ·
`EventKind` focus|class|break|review|admin · `SeriesState` active|retired|cancelled ·
`TimerMode` stopwatch|timer|pomodoro · `TimerPhase` focus|break ·
`ReminderState` pending|sent|cancelled · `BucketLevel` Y|M|W|D ·
`ReviewTier` hard|medium|easy|custom

### 1.4 Tool schemas — 27 tools (§5.5)
Nodes: `create_node`(title,kind,parent_id?,notes?,tag_ids?)→Node · `update_node`→Node ·
`delete_node`→{deleted,cascade_count} · `link_nodes`→{link_id} · `tag_node`→NodeTag ·
`untag_node`→{removed}
Events: `create_event`(title,start_ms,end_ms,node_id?,kind?,bucket_id?,reminder_offsets? default [10,0])
→{event,requested_start_ms,requested_end_ms,actual_start_ms,actual_end_ms,pushed} ·
`update_event`→{event,pushed} · `delete_event`→{deleted} (soft delete)
Series: `schedule_series`(node_id,tier,offsets_days?,max_count?,ends_on_ms?)→{series,events} ·
`delete_series`→{deleted,event_count} · `reschedule_series`→{series,events}
Search/schedule-solver: `search_nodes`(query,limit=10,semantic=true)→array[Node] ·
`check_conflict`(start_ms,end_ms,window_days=1 max7)→{hard_conflicts,semantic_candidates} ·
`find_free_slots`→array[{start_ms,end_ms}] · `get_free_time`→{free_minutes,busy_minutes}
Schedules: `create_schedule` / `update_schedule` / `pause_schedule` → `Schedule`
Timers: `start_timer`(node_id?,label,mode,target_ms?,source) · `stop_timer`(source) → TimerSession ·
`log_time`→{node_total_ms,descendant_total_ms,project_total_ms}
Queries: `get_day`(date)→{date,events,buckets,timer} · `get_week`·`get_month`→{week_start/week_end…,events,buckets} ·
`get_briefing`(date)→{date,unallocated_tasks,rollover,due_reviews,question}
Clarification: `ask_question`(question,context?)→{question_id,queued}

**No `move` tool exists** — moves go through `update_event` or delete+create.

### 1.5 Protocols (16; 10 repos + 6 infra), all `runtime_checkable`
Repos: `NodeRepo` (create/get/update/delete→cascade count/list_children/list_all/find_by_title),
`TagRepo` (+`get_by_name` — used for tag dedup), `NodeTagRepo`, `EventRepo`
(+`list_range`,`find_overlapping`,`find_soft_deleted`,`hard_delete`),
`BucketRepo` (+`get_by_level_and_date`,`get_chain` Y→M→W→D,`seed(years=10)`),
`ReviewSeriesRepo` (`create(series, events)` atomic; `delete`→event count),
`ScheduleRepo` (+`list_blocking`), `ReminderRepo` (+`list_due(now_ms)`),
`TimerSessionRepo` (`get_running` singleton; `mark_reconciled`; get_node/descendant/project_total),
`AuditRepo` (+`prune(before_ms)`).
Infra: `Clock`(now_ms, today_start_ms, to_local, to_utc, snap_to_minute) ·
`IdGen`(new_id→uuid4) · `Embedder`(embed, embed_batch, dimension=**768**) ·
`Notifier`(send, send_reminder, send_proposal, send_question) ·
`SearchBackend`(index_node, remove_node, search_keyword, search_semantic, search_combined).

### 1.6 DDL — 13 tables + 2 virtual tables
`nodes`(+`ix_nodes_parent`) · `tags`(name UNIQUE) · `node_tags`(composite PK, both CASCADE) ·
`events`(+`ix_events_window(start_ms,end_ms)`, `ix_events_series(series_id)`) ·
`buckets` · `review_series`(with the bound CHECK) · `schedules` · `reminders`(+`ix_reminders_due(state,fire_at_ms)`) ·
`timer_sessions` · `settings`(key TEXT PK, value TEXT) · `audit` ·
`node_fts` = **fts5(title, notes, content='')** (contentless!) ·
`node_vec` = **vec0(node_id TEXT PRIMARY KEY, embedding FLOAT[768])**.
Booleans stored as INTEGER 0/1; JSON arrays stored as TEXT.
No indexes declared on `buckets`, `schedules`, `review_series`, `timer_sessions`, `audit`.

**Bucket seed:** 10 years forward from today; Y→M→W→D nesting (day's parent is the containing **week**,
week's parent is its month); ~4303 rows (10 yr / 120 mo / 522 wk / 3653 day); idempotent
(`INSERT OR IGNORE`); week number = ISO week of the week's own start date; background auto-extend when <180 days remain.

### 1.7 Domain rules stated as constraints
- Tags apply to tasks/subtasks, never projects (repo-layer enforcement).
- `end_ms > start_ms` repo invariant; soft-deleted events are **not** conflicts.
- Overlap push: at commit, push to first free minute satisfying duration + hard blocks + day bounds.
- Review tiers (day offsets): hard `[1,2,4,8,16]`, medium `[3,7,15,30]`, easy `[10,30,90]`.
  No geometric/GP formulas, no automatic rewind. Series write is one transaction.
- Pomodoro break excluded from work totals; focus stopped early is **not** a completed cycle.
- Server death mid-timer → `reconciled=1` on next boot.
- Audit retention 7 days.

### 1.8 Unresolved (flagged in doc, claimed approved elsewhere)
`node_links` has no DDL (`link_nodes` implies it) — proposal: `(source_id,target_id)` PK + CASCADE FKs.
Tier offsets ignored when `tier != custom`. `Event.bucket_id` set by scheduler at placement, not creation.
Pomodoro `target_ms` = focus duration; break from preset (25/5 × 4).

---

## 2. Phase 2 — `chronos/ai/`

### 2.1 File layout
```
ai/__init__.py
ai/providers/{__init__,adapter,chain,worker,stt}.py
ai/pipeline/{__init__,packer,intent,verify,tools}.py
ai/cost.py  ai/prices.py  ai/cost_hook.py
```
Leaves: `prices.py` (no imports), `adapter.py` + `packer.py` (depend only on contracts).

### 2.2 Adapter — one class, three provider groups, zero provider-specific code
`Adapter(name, base_url, model, api_key, timeout=30.0)`; props name/base_url/model/timeout.
- `chat(messages, tools=None, temperature=0.0) -> ChatResponse` — `POST {base}/chat/completions`
- `transcribe(audio: bytes, filename="audio.wav") -> str` — `POST {base}/audio/transcriptions` (multipart)
- `embed(texts: list[str]) -> list[list[float]]` (768-dim) — `POST {base}/embeddings`
- `is_available() -> bool`
Auth header `Authorization: Bearer ***` on all three.
`ChatResponse(content, tool_calls=None, usage: TokenUsage|None, raw={})`;
`TokenUsage(prompt_tokens, completion_tokens, total_tokens)`.

### 2.3 Provider error taxonomy (retry keyed off type)
`ProviderError(message, provider, status_code=None)` base.
Retryable: `ProviderRateLimit` (429), `ProviderServerError` (5xx), `ProviderTimeout`.
Non-retryable: `ProviderAuthError` (401/403), `ProviderRejected` (400/410/other).
Parse errors also non-retryable.

### 2.4 Chain + retry worker
`Chain(adapters, cost_tracker=None, worker=None)`; `submit(ChainRequest) -> ChainResult` —
**never raises**; first attempt synchronous on the request path, retries off-path.
`ChainResult.status ∈ {"completed","queued","failed"}` (never "pending").
`ChainRequest(request_id, kind∈chat|transcribe|embed, messages?, tools?, audio?, filename, texts?, submitted_at, attempt, adapter_index)`.
`next_adapter(current=None)` wraps around. `record_attempt(...)` records **every** attempt, success or failure.

Retry constants: `RETRY_SKIP_AFTER_SECONDS=120`, `RETRY_MAX_INFLIGHT=8`, `RETRY_BASE_DELAY=1.0`,
`RETRY_MAX_DELAY=60.0`, `RETRY_BACKOFF_MULTIPLIER=2.0`, `RETRY_JITTER_FRACTION=0.25`.
```
delay = min(1.0 * 2.0**attempt, 60.0); delay += delay * 0.25 * uniform(-1,1)
```
Retries are effectively **unbounded** (cycle until success or user skip). After 120 s the client is
offered a manual skip so a dead provider can't trap the UI.
`RetryWorker(chain, max_inflight=8)`: `start/stop/enqueue(job)/status() -> WorkerStatus`
(`running, queue_depth, inflight, max_inflight, total_retried, total_succeeded, total_failed`).

### 2.5 Context packer — 5 layers, strict priority, drop from lowest up
1. identity + hard blocks + preferences + **current time** (stable prefix for prompt caching)
2. ancestor chain · 3. search results (top N, titles + relative dates) · 4. ±1 day events · 5. user utterance **verbatim, last**
`Packer(token_ceiling, clock, node_repo, event_repo, search, schedule_repo=None)`;
`pack(TurnContext) -> PackedContext{messages, token_count, cuts, layers_included, layers_excluded}`;
`estimate_tokens(text)` = deterministic `len(text)//4` (no tokenizer call).
`CutRecord(layer, priority, items_total, items_included, items_cut, reason)` → UI says "checked 30 tasks, showing 8".

### 2.6 Intent + verify
No separate decision model. Three roles: Understand (primary text model), Verify + Classify (cheap tier = **last adapter in chain**).
`IntentParser(adapter, packer).parse(text, TurnContext) -> IntentResult{tool_calls, needs_clarification,
clarification_question, is_lookup_only, raw_response}`.
`needs_second_turn(intent_result) -> bool` — lookup-only turn (no mutation tools) gets a **second turn**;
lookup-only = only `search_nodes/get_day/get_week/get_month/get_briefing/find_free_slots/get_free_time/check_conflict/ask_question`.
`Verifier(adapter).audit(intent_result, user_text, context) -> VerifiedResult{tool_calls, approved, corrections, rejection_reason}`;
`Correction(tool_call_index, field, old_value, new_value, reason)`. Verifier **never invents an unrequested call**.

### 2.7 Tool dispatcher
`ToolDispatcher(node_repo, tag_repo, node_tag_repo, event_repo, bucket_repo, review_series_repo,
schedule_repo, reminder_repo, timer_session_repo, audit_repo, search, clock, id_gen, cost_tracker=None)`.
`dispatch(ToolCall) -> ToolResult`, `dispatch_all(list) -> list` (no cross-tool transaction; per-tool atomicity).
All 27 implemented; **none returns "not implemented"**. `_validate_series_bounds` raises `ValueError` on unbounded series.
Hard conflicts and overlaps resolved in **code**, never by the model; semantic dup check warns/proposes only.

### 2.8 Cost + prices
`CostTracker(db_connection).record(provider, model, prompt_tokens, completion_tokens, total_tokens, success,
error_type=None, cost_usd=None)` — every attempt; unknown price written as NULL.
`get_daily_cost(date_ms) -> DailyCost`, `get_cost_range(start_ms,end_ms) -> list[DailyCost]`.
`PriceTable(prices=None).get_price(provider, model, token_type∈input|output) -> float|None` (per 1M tokens);
`compute_cost(...) = (prompt/1e6)*in + (completion/1e6)*out`, `None` if either price unknown.
`DEFAULT_PRICES`: groq `openai/gpt-oss-120b` in 0.25 / out 0.50; nim `nvidia/nemotron-3-super-120b-a12b` 0.0/0.0 (known free).
`token_cost` table + `ix_token_cost_day(at)`, `ix_token_cost_provider(provider)`.
`cost_hook(chain, tracker, price_table)` or `CostHook.on_attempt(...)`.

### 2.9 Env vars (defaults are the contract)
`TEXT_PROVIDERS=groq,nim` (order = failover order) · `GROQ_BASE_URL=https://api.groq.com/openai/v1` ·
`GROQ_MODEL=openai/gpt-oss-120b` · `NIM_BASE_URL=https://integrate.api.nvidia.com/v1` ·
`NIM_MODEL=nvidia/nemotron-3-super-120b-a12b` (NIM returns 410 for gpt-oss) · `STT_*` = groq + `whisper-large-v3-turbo` ·
`EMBED_BASE_URL=http://localhost:8000/v1` · `EMBED_MODEL=llama-embedding` · `CONTEXT_TOKEN_CEILING=4096` ·
`CONTEXT_SEARCH_LIMIT=10` · `CONTEXT_EVENT_WINDOW_MS=86400000`.
`chronos setup` writes `.env`: STT first, then N text providers (entry order = failover), then embeddings;
multiple keys per endpoint tried round-robin before falling through.

### 2.10 Unresolved
"Cloudflare → Groq → NIM" in spec dropped: chain = whatever `TEXT_PROVIDERS` lists. No STT failover, no embedding
failover in Phase 2. Similarity threshold setting `ai.duplicate_threshold` default 0.85.

---

## 3. Phase 3 — `chronos/api/` + `chronos/realtime/`

### 3.1 Auth
- Key: ≥32 random bytes hex → 64 chars; printed once; only Argon2id hash stored at
  `settings["auth.instance_key_hash"]` (time_cost=2, memory_cost=65536, parallelism=1). Plaintext never on disk/log/API.
- Transport: header `X-Chronos-Key`, fallback `?key=` (for MCP clients that can't set headers).
- Status codes: no key → **401**; no hash yet → **503** "Instance key not yet generated. Run `chronos serve` first."; bad key → 401.
- **`/api/health` is the only unauthenticated route.**
- Redaction must happen at **record-creation time** (`Logger.makeRecord` override / root LoggerAdapter) —
  a logger-attached filter does not cover descendant loggers like `httpx._client`. Scrub `?key=`/`&key=` → `key=***`.
- Renewal: `chronos key-renew` / `POST /api/keys/renew` → new key, updates hash, disconnects all WS with close code **4001 "key rotated"**.
- `chronos/api/auth.py` exports: `generate_instance_key, get_stored_hash, store_instance_key, rotate_instance_key,
  verify_instance_key, extract_key_from_request, extract_key_from_websocket, require_key, require_key_ws,
  redact_key_from_url, KeyRedactingLoggerAdapter, install_key_redaction, health_unauthenticated`.

### 3.2 `create_app(db_path: Optional[str] = None) -> FastAPI` — **load-bearing, do not change signature**
Resolution order: explicit arg → `CHRONOS_DB` → `~/.chronos/chronos.db` (mkdir parents).
Also: engine + sessionmaker, alembic migrate if stale, seed buckets if fresh, load tz, reconcile running timers,
install redaction + generate/print key if absent, create `RealtimeHub`, register all routes with `require_key` except health,
exception handlers (401/409/422/500), startup (reminder scheduler + timer tick) / shutdown (disconnect all).
`app.state`: `db_path, engine, session_factory, settings_repo, clock, hub, timezone, api_key_hash`.

### 3.3 REST — 20 rows for "18 routes" (table counts 20 incl. health + keys/renew)
| Method/Path | Auth | Req → Resp | Notable errors |
|---|---|---|---|
| POST `/api/voice` | yes | multipart(audio, language?) → `VoiceResponse{transcript,confidence?,language?}` | 400 no file, 415 bad format, 413 >25 MB, 502 STT |
| POST `/api/say` | yes | `SayRequest{text,device_id?}` → `SayResponse{intent,tool_calls,proposal_id?,committed,events,message?}` | 400 empty, 502 AI |
| POST `/api/commands` | yes | `CommandRequest{tool,arguments,device_id?}` → `CommandResponse{tool,result,events,proposal_id?}` | 400 unknown tool, 422 schema, 502 |
| GET `/api/events?from&to` | yes | → `list[Event]`; `start_ms < to AND end_ms > from`; excludes soft-deleted | |
| GET `/api/nodes?parent&tag` | yes | → `list[Node]`; no parent ⇒ roots | |
| GET `/api/buckets?level&date` | yes | → `list[Bucket]`; date ⇒ that bucket's children | |
| GET `/api/briefing?date` | yes | → `BriefingResponse` | |
| GET `/api/search?q&limit` | yes | → `list[Node]` w/ **absolute** (unnormalized) scores; vec absent ⇒ keywords only | |
| GET `/api/reminders` | yes | → pending, ordered by fire_at_ms | |
| POST `/api/timer/start` | yes | `TimerStartRequest{node_id?,label,mode,target_ms?,source}` → TimerSession; stopwatch ignores target_ms | **409** if one running |
| POST `/api/timer/stop` | yes | `{source}` → TimerSession | **409** if none running |
| GET `/api/timer?node_id` | yes | → TimerSession\|null | |
| GET `/api/timer/summary?node_id` | yes | → `TimerSummary{node_total_ms,descendant_total_ms,project_total_ms}` | |
| GET/POST `/api/timer/presets` | yes | `PomodoroPreset{name,focus_minutes,break_minutes,cycles}`; GET always includes 25/5×4; POST **appends** | |
| GET `/api/stats` | yes | `StatsResponse{total_nodes,active_nodes,done_nodes,total_events,events_today,current_streak_days,longest_streak_days,token_spend_by_day[TokenSpendEntry]}` | |
| GET/PUT `/api/settings` | yes | `dict[str,str]`; GET **hides** `auth.instance_key_hash`; PUT **merges**, rejects that key, tz change re-buckets + audits | |
| POST `/api/keys/renew` | yes | → `KeyRenewResponse{new_key,message}` | |
| GET `/api/health` | **no** | `HealthResponse{status,version,db_path,uptime_seconds}` | |

`/api/say` policy: lookup-only or unambiguous+no conflicts ⇒ auto-commit `committed=True`; conflicts/ambiguity ⇒ proposal, `committed=False` + `proposal_id`, broadcast over WS.
`/api/commands` = raw tool entry point for CLI/MCP (already knows the tool).

### 3.4 Realtime — one hub, every mutation broadcast to all clients
`/ws`, one connection per client, authenticated on upgrade, reject close code **4001**.
Server→client: `state`(snapshot: nodes, events_today, running_timer, pending_proposals, pending_questions) ·
`patch`(`ops:[{op:insert|update|delete, table, row|id, changes}]`) · `proposal`(proposal_id, tool_calls, diff, conflicts) ·
`question`(question_id, question, context?) · `timer`(action start|stop|tick, session, elapsed_ms) ·
`queued`(id, provider) · `retrying`(attempt, provider, error).
Client→server: `hello`(key, device — key is fallback only if not validated at upgrade) · `say`(text) ·
`accept`/`reject`/`skip`(proposal_id). `skip` dismisses without commit or reject.
`RealtimeHub(clock)`: `connect/disconnect/broadcast/send_to/close_all(code=4001)/client_count` + `build_*_message` helpers.

### 3.5 `scripts/smoke.sh` — the real gate (a green unit suite is not a running app)
Port default 8099; 8 checks: boot→healthy, health unauthenticated & `"status":"ok"`, 401 without key,
extract 64-hex instance key from server log via `grep -oP 'Instance key: \K[a-f0-9]{64}'`,
authenticated list works, `?key=` fallback returns 200, **key absent from log file**, timer start + second timer ⇒ 409 + stop.

### 3.6 Files
`api/{__init__,app,auth,routes,voice,dependencies}.py`, `realtime/{__init__,hub,protocol}.py`.
`dependencies.py`: `get_db, get_settings_repo, get_clock, get_hub`.

---

## 4. Phase 4 — Web HUD, CLI, MCP

### 4.1 Web HUD — no build step, no bundler, no framework, vanilla JS
`web/__init__.py` + `web/static/{index.html, styles.css, app.js}`; mounted at root, same origin as API.
`mount_hud(app: FastAPI, db_path: str) -> None` serves `/`→index.html, `/styles.css`, `/app.js`.
**8 screens:** Today · Timer controls · Calendar · Briefing · Projects · Schedules · Time Log · Settings.
Styling bans: no `backdrop-filter`, no blur/translucency, no gradients, no orbital/ring elements, minimal radius.
**Zero-form:** no save/submit buttons anywhere; every change commits on `blur`; no date pickers, no time dropdowns.
Say box (`#say-input` + `#say-mic`): mic streams to `/api/voice`, transcript is **appended** after existing
content (space-separated); **never auto-submits** — Enter sends to `/api/say` and clears.
Calendar: 1-minute grid (`§7.2`), hour rule every 60 min, hours collapsed with `.calendar-expander` revealing the 60
minute cells (not a 1440-row grid); drag = move, edge handles = resize, both commit via `POST /api/commands` → `update_event`;
click an empty minute → populates say box "here at 4". Start/end snap to the minute.
Timer field visibility matrix: `#timer-target-ms` hidden for stopwatch, visible for timer+pomodoro; `#timer-pomodoro-*`
and `#timer-phase`/`#timer-cycle` visible only for pomodoro (phase/cycle only when running).
Key handling: received via `/?key=` only; stored in a JS variable; sent as `X-Chronos-Key` header; **never** in
localStorage/sessionStorage/HTML source/request body/`console.log`.
WS: `hello` on connect, expect `state`, re-render per message, reconnect with exponential backoff **1 s → max 30 s** + "disconnected" banner.

### 4.2 CLI — `chronos/cli/{__init__,__main__,commands}.py`
`main() -> int` (argparse, dispatch). `commands.py`: `serve, key_renew, db_upgrade, token_cost, export, say, get`.
Rules: stdout for data, stderr for errors, **no prompts**, pipe-safe, exit 0/non-zero, no color when not a TTY.
- `serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]` — must resolve `chronos.api.create_app` and **pass `--db` through**; mounts HUD unless `--no-web` or `CHRONOS_WEB=0`.
- `db-upgrade [--db]` — alembic via `sys.executable -m alembic upgrade head` (**not** a PATH lookup), load sqlite-vec into the current process (schema creates `vec0`), export `CHRONOS_DB` to the subprocess.
- `token-cost [--days 7]` · `export [--format json] [--output]` (JSON only in v1; CSV deferred to M4) ·
  `say -` (stdin → `POST /api/say`; error + non-zero exit if server down) ·
  `get day|timer|briefing [--date]` (`get_week`/`get_month` deliberately not in CLI).
- `setup` = interactive provider config (Phase 2 flow), writes `.env`.
- CLI auth: reads key from `~/.chronos/key` (mode `0600`, written on first run), sends `X-Chronos-Key`, errors out if missing, never prints the key (except `key-renew`).

### 4.3 MCP — same 27 tools, no reimplementation
`create_mcp_server(executor, db_path, device_id="mcp")`; `adapt_tools(executor) -> list[dict]`;
`mcp/auth.py`: `verify_key(key, db_path) -> bool`, `extract_key(headers, query_string) -> str|None`.
Transport: HTTP `/mcp`. Every call validated against the Phase-1 schema, converted to the executor format,
executed, converted back — same code path as voice input. Every call writes an `AuditEntry`
(`action`=tool name, `target`=entity id, `context`=args JSON).

---

## 5. Phase 5 — notify, search, briefings, stats, audit, export

### 5.1 Contracts additions (announced changes to the frozen surface)
`constants.py`: `DEFAULT_REMINDER_OFFSETS_MIN = [10, 0]`, `DEFAULT_REUSE_SIMILARITY_THRESHOLD = 0.85`.
`models.py`: `SearchResult`, `Briefing`, `Question`, `TokenCost`, `ProviderPrice`.
`ddl.py`: `token_costs`, `provider_prices` tables.

### 5.3 `token_costs` vs Phase 2's `token_cost` — CONFLICT
Phase 2 §G.7 defines **`token_cost`** (prompt_tokens/completion_tokens/total_tokens/error_type).
Phase 5 §E.2.1 defines **`token_costs`** (tokens_in/tokens_out/attempt/created_at).
Same purpose, different table name, different columns, no reconciliation note. Both claim FROZEN status.
Must be reconciled before implementation or cost queries/stats silently diverge.

### 5.4 Other cross-doc conflicts worth flagging
- **CLI entry point:** Phase 4 defines `chronos/cli/{__init__,__main__,commands}.py` with `main` in `__main__.py`;
  Phase 6 `pyproject.toml` points `[project.scripts] chronos = "chronos.cli.main:main"` — a `main.py` that
  does not exist in the Phase 4 layout. Packaging entry point is broken as written.
- **`mount_hud`:** Phase 4 §B.4 calls `chronos.web.mount_hud(app)` (one arg) while §F.1/D.1 specify
  `mount_hud(app, db_path)` (two args).
- **`SettingsRepo`:** Phase 3 `auth.py` imports it from `chronos.contracts`, but Phase 1's frozen 16 protocols
  do not include it (only the `settings` DDL table exists).
- **`Briefing` shape vs `get_briefing` tool:** contracts C.26 returns
  `{date, unallocated_tasks, rollover, due_reviews, question}`; Phase 5's `Briefing` has
  `unallocated_tasks_today` + `unallocated_tasks_week` + `considered_count` + `shown_count` — a breaking
  change to the frozen tool return, partially acknowledged in ambiguity I.10.
- **`check_conflict` return type change** acknowledged as breaking (Phase 5 I.2).
- **Duplicate-search cost:** `find_semantic_candidates` calls `search_with_scores(limit*3)` then filters by window.
- **`/api/health` example payload** in Phase 6 §B.6 (`{"status":"ok","version":"2.0.0","db":"ok"}`) does not
  match the Phase 3 `HealthResponse{status,version,db_path,uptime_seconds}` schema.

### 5.5 Search — `NodeSearch` in `chronos/db/search.py`
`DbConnection = Union[Session, sqlite3.Connection]`; `_get_connection()` extracts the raw connection
(v1 silently returned nothing under a Session because a broad `except` swallowed the error — catch must be
narrowed to `sqlite3.OperationalError`).
Methods: `index_node, remove_node, reindex_node, search_keyword, search_semantic, search_combined,
search_with_scores -> list[SearchResult], _has_fts_table, _has_vec_table`.
`SearchResult(node, keyword_score|None, vector_distance|None, combined_score|None)` — scores **absolute, never normalized**.
Degradation matrix: missing FTS ⇒ index ops no-op, searches return `[]`; missing vec ⇒ no-op on index,
`[]` on semantic, keyword-only on combined. **Never raises** on a missing table.
Indexing lifecycle: `NodeRepo.create/update/delete` call index/reindex/remove — best-effort (v1 shipped a
`create_node` that never wrote FTS, so search returned nothing in the real app while tests passed).
`find_semantic_candidates(db, title, notes, target_ms, window_days=1, limit=10) -> list[SearchResult]`;
`DEFAULT_SEMANTIC_DUPLICATE_WINDOW_DAYS=1`, `MAX_...=7`; raises `ValueError` if `window_days > 7`.
Reuse/tag-dedup decisions live in the **AI layer**, not the search module (`tags.name UNIQUE` is the DB backstop).

### 5.6 Notifications
`NtfyNotifier(server_url, topic, token=None)`: `send/send_reminder/send_proposal/send_question` — exactly **one
HTTP POST per message** to `{server_url}/{topic}` with `Title`, `Priority`, optional `Authorization: Bearer`.
Priority map: review due `high` · proposal awaiting `default` · timer milestone `low` · reminder 10-min `default` ·
reminder at start `high` · question `default`.
`ReminderScheduler(reminder_repo, event_repo, notifier, clock)`: `tick() -> int` (fires pending with
`fire_at_ms <= now`, skips CANCELLED and missing/soft-deleted events, marks SENT, returns count);
`cancel(reminder_id) -> bool`. Runs on the realtime tick. Reminder rows are real rows ⇒ individually cancellable;
cascade-delete with their event. `fire_at_ms = event.start_ms - offset_min * 60000`.

### 5.7 Briefings — generated, not templated
`BriefingGenerator(node_repo, event_repo, series_repo, budget, clock).generate(date) -> Briefing`
(unallocated today/week, rollover, due reviews = kind REVIEW starting today, one question, considered/shown counts).
`ClarificationBudget(db, clock)` **persisted in `settings`** — settings keys `clarification.budget_per_day` ("1"),
`clarification.used_today` ("0"), `clarification.last_question_date`; a fresh instance from the same DB must see
the day as spent (v1's failure: "counter is in memory, not persisted").
API: `budget_per_day`, `used_today`, `last_question_date`, `can_ask()`, `record_question() -> question_id`
(raises `BudgetExhausted`), `next_question() -> str|None`, `reset_if_new_day()`.
Questions stored in the **`audit` table** with `action='question'`, `context`=question text, `target`=question_id
(hack; dedicated table deferred).

### 5.8 Stats
`token_costs(at, provider, model, tokens_in, tokens_out, cost_usd NULL, attempt=1, success=1, created_at)` +
`ix_token_costs_day(at)`, `ix_token_costs_provider(provider,model)`.
`provider_prices(provider, model, price_in, price_out)` PK(provider,model); seeded at deploy time.
`StatsCollector(db, node_repo, event_repo, timer_repo, audit_repo, clock)`:
`get_stats(days=7)` → `{period_days, counts{…}, streaks{current,longest,last_activity_date},
token_spend_by_day[{date,tokens_in,tokens_out,cost_usd|None,attempts,failures}], audit_entries, retention_days:7}`;
`record_token_cost(...) -> TokenCost` (`cost = (tokens_in*price_in + tokens_out*price_out)/1e6`, else `None`);
`prune_audit()`, `prune_logs()` — 7-day retention.

### 5.9 Audit viewer
`AUDIT_RETENTION_DAYS = 7`; `AuditFilter(action, target, from_ms, to_ms, limit=100, offset=0)`;
`AuditViewer(audit_repo, clock)` read-only: `list_entries(filter)`, `get_entry(id)` (out-of-window ⇒ `None`), `count_entries(filter)`.

### 5.10 CSV export
`CSVExporter(event_repo, timer_repo, db, clock)`:
`export_events(start_ms,end_ms)`, `export_timers(...)`, `export_cost(...)` → CSV strings.
Columns as declared per method (events: id,title,start_ms,end_ms,kind,node_id,bucket_id,series_id,review_index,
derived_from,soft_deleted,created_at; timers: …; cost: id,at,provider,model,tokens_in,tokens_out,cost_usd,attempt,success).
Rules: header row, one row per record, `csv.writer` default `QUOTE_MINIMAL`, timestamps ISO-8601 with offset in
instance tz, booleans as `"1"`/`"0"`, **unknown cost = empty cell** (not `0.0`, not `None`).

---

## 6. Phase 6 — Deployment

### 6.1 Docker
Base pinned **`python:3.14.7-slim-bookworm`**, multi-arch (amd64 + arm64). Multi-stage: builder installs
`build-essential` + `pip install .` (sqlite-vec compiles from sdist); runtime copies only
`/usr/local/lib/python3.14/site-packages` and `/usr/local/bin/chronos`.
`ENTRYPOINT ["chronos"]`, `CMD ["serve","--host","0.0.0.0","--port","8080"]`, `EXPOSE 8080`, `VOLUME ["/data"]`.
Env: `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`, `CHRONOS_DB=/data/chronos.db`, `CHRONOS_WEB=1`.
`HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3` hitting `/api/health`.
Image contains **no** `.env`, no DB, no build tools, no `.git`, no `tests/ docs/ scripts/`.
`.dockerignore`: `.venv/ .env *.db *.sqlite *.sqlite3 __pycache__/ *.pyc *.egg-info/ dist/ build/
.pytest_cache/ .ruff_cache/ .git/ .github/ tests/ android/ docs/ scripts/ *.bundle`.

### 6.2 Compose
`chronos` service, `restart: unless-stopped`, `8080:8080`, volume `chronos-data:/data`,
`environment: {CHRONOS_DB: /data/chronos.db, CHRONOS_WEB: "1"}`, `env_file: [{path: .env, required: false}]`.
Non-secret config in `environment:`, secrets only in `.env` (gitignored + dockerignored). No systemd, no root,
no OS timezone configuration. Backup = `docker cp chronos:/data/chronos.db ./backup.db`.

### 6.3 Termux
`scripts/termux.sh install|start|stop`.
`install`: `pkg update -y`; `pkg install -y python git rust binutils libsqlite` (rust needed to compile sqlite-vec);
venv at `$HOME/.chronos/venv`; `pip install -e .`.
`start`: **`termux-wake-lock` BEFORE the server** (Android doze kills backgrounded servers) → `CHRONOS_DB=$HOME/.chronos/chronos.db`
→ `nohup … chronos serve --host 127.0.0.1 --port 8080 &` → PID to `$HOME/.chronos/server.pid` → 2 s then health check; on failure print log path, exit 1.
`stop`: kill PID, rm PID file, `termux-wake-unlock`.
Embedding model `llama-embedding` ~274 MB downloads on first `embed()`, announced with progress, **never silently inside a request**.
Untestable on this host (Fedora 44 aarch64 proot): `termux-wake-lock`/`unlock`, Android doze, exact `pkg` package names.
`docs/termux.md` must state prereqs, exact commands, why (wake lock/venv/nohup), health verification, what was and wasn't tested, troubleshooting.

### 6.4 Packaging
```toml
[build-system] requires=["setuptools>=68"]; build-backend="setuptools.build_meta"
[project] name="chronos" version="2.0.0" requires-python=">=3.14" license={text="GPL-3.0-or-later"}
dependencies = fastapi>=0.115, uvicorn>=0.30, sqlalchemy>=2.0, alembic>=1.13,
               argon2-cffi>=23.1, sqlite-vec>=0.1.6, python-multipart>=0.0.9, httpx>=0.27
[project.optional-dependencies] dev = pytest>=8.0, ruff>=0.6
[project.scripts] chronos = "chronos.cli.main:main"
[tool.setuptools.packages.find] include = ["chronos*"]
```
Version single-sourced: `from importlib.metadata import version; __version__ = version("chronos")`;
`chronos --version` prints `chronos 2.0.0`.
Package excludes `.env`, DB, `tests/ docs/ scripts/`.
Note: `pytest`/`ruff` only in `dev` extra, but `scripts/smoke.sh` (Phase 3) hardcodes `.venv/bin/python -m chronos.cli serve` — ok.

### 6.5 CI
`.github/workflows/ci.yml`: `guard` job detects whether `chronos/**/*.py` exists (repo is docs-only until the build
produces it — skip cleanly so the badge stays honest) → `tests` job on ubuntu-latest, Python 3.14,
`pip install -e ".[dev]"`, `ruff check chronos tests`, `pytest tests -q`.
`.github/workflows/docker.yml`: same guard → `docker build -t chronos:ci .` → run container, poll
`/api/health` up to 30 s, else `docker logs` + exit 1.
Neither requires `.env`; neither runs on Windows; no registry push in this phase.

### 6.6 Deploy scripts
`scripts/termux.sh` (install/start/stop) · `scripts/smoke.sh` (`./scripts/smoke.sh 8099` — **conflicts with Phase 3's
8-check version**, Phase 6 §F.2 describes a 4-step health-only variant) · `scripts/backup.sh`
(`backups/chronos-$(date +%Y%m%d-%H%M%S).db`) · `scripts/restore.sh` (stop, copy, start).
No systemd units, no root-required scripts, no OS timezone config.

### 6.7 Phase 6 unresolved
Base patch pin `3.14.7`; multi-arch via buildx; embedding progress via library tqdm + pre-log line;
Termux packages list; Windows explicitly **untested** (document, don't claim); no registry; backup script;
`docs/docker.md` created (listed in phase-doc checklist but not its Parts table).

---

## 7. Consolidated unresolved decisions / action items

1. **`token_cost` vs `token_costs`** — two different schemas for the same data across Phase 2 and Phase 5. Reconcile.
2. **`chronos.cli.main` vs `chronos.cli.__main__`** — Phase 6's console-script entry point doesn't exist in Phase 4's layout. Pick one module and fix both docs.
3. **`mount_hud(app)` vs `mount_hud(app, db_path)`** — Phase 4 §B.4 contradicts §F.1/D.1.
4. **`SettingsRepo`** — imported from contracts by Phase 3 but not among the 16 frozen protocols. Add or rewire.
5. **`get_briefing` return shape** — frozen C.26 vs Phase 5 `Briefing`; needs an explicit contract amendment, not a silent divergence.
6. **`check_conflict` return type** — Phase 5 I.2 admits this breaks the frozen tool schema; needs the same amendment.
7. **`node_links` DDL missing** — `link_nodes` has no table.
8. **`node_fts` is contentless (`content=''`)** — but `NodeSearch.search_keyword` needs to return full `Node` rows; must join back to `nodes` by rowid or `remove_node`/`reindex_node` cannot work on a contentless table without external content. Verify feasibility early.
9. **Question storage in `audit`** — acknowledged hack; a `questions` table would be cleaner.
10. **`smoke.sh` two versions** (Phase 3 8-check gate vs Phase 6 4-step) — keep the stronger one.
11. **`/api/health` example response** in Phase 6 doesn't match Phase 3's `HealthResponse`.
12. **Indexes missing** on `buckets` (hot path: `get_by_level_and_date`, `get_chain`), `schedules.list_blocking`, `review_series`, `timer_sessions.get_running` (singleton lookup on `ended_at IS NULL`).
13. **`CHRONOS_PORT` (Phase 6 Termux §C.4)** is only read by `termux.sh`, not by the server — confirm no one expects the server to honor it.