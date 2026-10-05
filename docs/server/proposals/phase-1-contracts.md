# Phase 1 — Interface Proposal: `chronos/contracts/`

**Status:** FROZEN — Phase 0 complete  
**Author:** Phase-1 Proposer  
**Date:** 2026-10-03  
**Spec source:** `docs/Chronos.md` §2.1, §4, §5.5, §6, §7  
**Phase doc:** `docs/phases/phase-1-core.md`  
**Manager review:** All 8 ambiguities ruled on and approved. See `docs/decisions.md`.

---

## 0. Scope and principles

This document proposes the complete frozen interface surface for Phase 1. It
covers:

- **A.** Models — every entity in §4 with fields, types, defaults, constraints.
- **B.** Enums — every enum with members and values.
- **C.** Tool schemas — all 27 tools from §5.5.
- **D.** Protocols — repo protocols, Clock, IdGen, Embedder, Notifier, SearchBackend.
- **E.** File layout — every file in `chronos/contracts/` with purpose and exports.
- **F.** DDL summary — every table, columns, types, constraints, indexes, plus the bucket seed spec.

**Principles:**

1. `contracts/` is the frozen shared surface (§2.1). After Phase 0 it changes
   only by deliberate, announced act.
2. Every module imports from `chronos/contracts/` and nothing else from its
   siblings (§2.1).
3. The import graph must be a DAG with no cycles.
4. All times are UTC epoch **milliseconds** (`INTEGER`) in the database (§4).
   ISO-8601 with offset at every API boundary (§7.3).
5. One instance timezone governs all bucket maths and rendering (§7.1).
6. The calendar grid is **1 minute** (§7.2).

---

## A. Models

Every model is a frozen dataclass. Field order is the constructor order.
`Optional[X]` means the field may be `None`. `List[X]` means a JSON-serializable
list. All `id` fields are `TEXT` (uuid4). All timestamp fields are `INTEGER`
(epoch ms).

### A.1 `Node` (§4.1)

Hierarchy entity — project, task, or subtask.

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, uuid4 |
| `parent_id` | `Optional[str]` | `None` | FK → `nodes.id`, ON DELETE CASCADE |
| `kind` | `NodeKind` | — | NOT NULL |
| `title` | `str` | — | NOT NULL |
| `notes` | `Optional[str]` | `None` | nullable |
| `status` | `NodeStatus` | `NodeStatus.ACTIVE` | NOT NULL |
| `created_at` | `int` | — | NOT NULL, epoch ms |
| `updated_at` | `int` | — | NOT NULL, epoch ms |
| `done_at` | `Optional[int]` | `None` | nullable, epoch ms |

**Notes:**
- Tags apply to tasks and subtasks, never to projects (§4.1). Enforced at the
  repo layer, not the model layer.
- A task may be linked to others with no structural meaning via `node_links`
  (§4.1). This is a separate table not in the DDL; the model does not carry
  links.

### A.2 `Tag` (§4.1)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, uuid4 |
| `name` | `str` | — | NOT NULL, UNIQUE |
| `color` | `Optional[str]` | `None` | nullable |

### A.3 `NodeTag` (§4.1)

Join table between nodes and tags.

| Field | Type | Default | Constraints |
|---|---|---|---|
| `node_id` | `str` | — | PK component, FK → `nodes.id`, ON DELETE CASCADE |
| `tag_id` | `str` | — | PK component, FK → `tags.id`, ON DELETE CASCADE |

Composite primary key: `(node_id, tag_id)`.

### A.4 `Event` (§4.2)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, uuid4 |
| `node_id` | `Optional[str]` | `None` | FK → `nodes.id`, ON DELETE CASCADE; NULL = ad-hoc |
| `title` | `str` | — | NOT NULL |
| `start_ms` | `int` | — | NOT NULL, epoch ms |
| `end_ms` | `int` | — | NOT NULL, epoch ms |
| `kind` | `EventKind` | `EventKind.FOCUS` | NOT NULL |
| `bucket_id` | `Optional[str]` | `None` | FK → `buckets.id`, nullable |
| `series_id` | `Optional[str]` | `None` | review series, if any |
| `review_index` | `Optional[int]` | `None` | 1..N within the series |
| `derived_from` | `Optional[str]` | `None` | source event id |
| `soft_deleted` | `bool` | `False` | NOT NULL, stored as INTEGER 0/1 |
| `created_at` | `int` | — | NOT NULL, epoch ms |

**Notes:**
- Overlap detection is a plain range query on `(start_ms, end_ms)` (§4.2).
- `soft_deleted` events are **not** conflicts (§6, phase doc).
- `end_ms > start_ms` is a repo-level invariant.

### A.5 `Bucket` (§4.3)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, format `Y:2026` / `M:2026-08` / `W:2026-W31` / `D:2026-08-04` |
| `level` | `BucketLevel` | — | NOT NULL |
| `parent_id` | `Optional[str]` | `None` | FK → `buckets.id`; NULL for year buckets |
| `start_ms` | `int` | — | NOT NULL, epoch ms |
| `end_ms` | `int` | — | NOT NULL, epoch ms |
| `seq` | `int` | — | NOT NULL, 1..4 ordinal within the parent |

**Notes:**
- The chain is nested Y → M → W → D. A day's parent is the **week** that
  contains it; a week's parent is its month; a month's parent is its year
  (§4.3, phase doc).
- A week id's number equals the **ISO week of its own start date** (§4.3).
- The seed is idempotent (§4.3).

### A.6 `ReviewSeries` (§4.4)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, uuid4 |
| `node_id` | `str` | — | NOT NULL, FK → `nodes.id`, ON DELETE CASCADE |
| `tier` | `ReviewTier` | — | NOT NULL |
| `offsets_days` | `List[int]` | — | NOT NULL, JSON int array, e.g. `[3,6,15,30]` |
| `anchor_node_id` | `str` | — | NOT NULL, the completed node that started it |
| `max_count` | `Optional[int]` | `None` | NULL = no count bound |
| `ends_on_ms` | `Optional[int]` | `None` | NULL = no date bound |
| `state` | `SeriesState` | — | NOT NULL |
| `created_at` | `int` | — | NOT NULL, epoch ms |

**Constraints:**
- `max_count IS NOT NULL OR ends_on_ms IS NOT NULL` — a series **must be
  bounded** (§4.4, phase doc). Enforced at both the schema (CHECK) and repo level.
- Default tiers as day offsets (§4.4):
  - hard: `[1, 2, 4, 8, 16]`
  - medium: `[3, 7, 15, 30]`
  - easy: `[10, 30, 90]`
- Creating a series writes **all** review events in one transaction, each
  carrying `series_id`, `review_index`, and `derived_from = anchor_node_id` (§4.4).
- No geometric/GP formulas. No automatic rewind (§4.4, phase doc).

### A.7 `Schedule` (§4.5)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, uuid4 |
| `title` | `str` | — | NOT NULL |
| `starts_ms` | `int` | — | NOT NULL, epoch ms |
| `ends_at_ms` | `int` | — | NOT NULL, epoch ms |
| `start_minute` | `int` | — | NOT NULL, minute of day (0..1439), e.g. 510 for 08:30 |
| `duration_min` | `int` | — | NOT NULL, minutes |
| `weekdays` | `List[int]` | — | NOT NULL, JSON int array [1..7], ISO weekday |
| `hard_block` | `bool` | `True` | NOT NULL, stored as INTEGER 0/1 |
| `paused` | `bool` | `False` | NOT NULL, stored as INTEGER 0/1 |
| `created_at` | `int` | — | NOT NULL, epoch ms |

**Notes:**
- Schedules are hard blocks: the scheduler will not place an event inside one (§4.5).
- `paused` schedules do not block. Non-`hard_block` schedules do not block (phase doc).
- Every schedule is bounded by a start and end date and may exclude weekdays (§4.5).

### A.8 `Reminder` (§4.6)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, uuid4 |
| `event_id` | `str` | — | NOT NULL, FK → `events.id`, ON DELETE CASCADE |
| `fire_at_ms` | `int` | — | NOT NULL, epoch ms |
| `offset_min` | `int` | — | NOT NULL, minutes before event |
| `state` | `ReminderState` | `ReminderState.PENDING` | NOT NULL |
| `channel` | `str` | `"ntfy"` | NOT NULL |
| `created_at` | `int` | — | NOT NULL, epoch ms |

**Notes:**
- Default offsets are **10 minutes before and at the start** (§4.6, §5.4).
- A reminder row is a real row, not a derived value, so it can be cancelled
  individually (§4.6).

### A.9 `TimerSession` (§4.7)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | — | PRIMARY KEY, uuid4 |
| `node_id` | `Optional[str]` | `None` | FK → `nodes.id`, nullable |
| `label` | `str` | — | NOT NULL |
| `started_at` | `int` | — | NOT NULL, epoch ms |
| `ended_at` | `Optional[int]` | `None` | NULL = running, epoch ms |
| `source` | `str` | — | NOT NULL, device id |
| `reconciled` | `bool` | `False` | NOT NULL, stored as INTEGER 0/1 |
| `mode` | `TimerMode` | `TimerMode.STOPWATCH` | NOT NULL |
| `target_ms` | `Optional[int]` | `None` | NULL for a stopwatch, which has no target |
| `phase` | `Optional[TimerPhase]` | `None` | pomodoro only: focus or break |
| `cycle` | `int` | `1` | NOT NULL |

**Notes:**
- One timer runs at a time, across all three modes (§4.7, phase doc).
- A stopwatch ignores a target — it must not become a countdown (§4.7, phase doc).
- A pomodoro break is excluded from work totals but still recorded (§4.7, phase doc).
- A focus phase stopped early is **not** a completed cycle (§4.7, phase doc).
- If the server dies mid-timer, the session is flagged `reconciled = 1` on the
  next boot (§4.7).

### A.10 `AuditEntry` (§4.7)

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `int` | — | PRIMARY KEY, autoincrement |
| `at` | `int` | — | NOT NULL, epoch ms |
| `device_id` | `Optional[str]` | `None` | nullable |
| `action` | `str` | — | NOT NULL |
| `target` | `Optional[str]` | `None` | nullable |
| `context` | `Optional[str]` | `None` | nullable |
| `cost_usd` | `Optional[float]` | `None` | nullable |

**Notes:**
- Audit retention is 7 days (§4.7).

---

## B. Enums

All enums are `str`-based (`enum.Enum` with `str` mixin) so they serialize
directly to SQLite `TEXT` columns.

### B.1 `NodeKind` (§4.1)

| Member | Value |
|---|---|
| `PROJECT` | `"project"` |
| `TASK` | `"task"` |
| `SUBTASK` | `"subtask"` |

### B.2 `NodeStatus` (§4.1)

| Member | Value |
|---|---|
| `ACTIVE` | `"active"` |
| `DONE` | `"done"` |
| `ARCHIVED` | `"archived"` |

### B.3 `EventKind` (§4.2)

| Member | Value |
|---|---|
| `FOCUS` | `"focus"` |
| `CLASS` | `"class"` |
| `BREAK` | `"break"` |
| `REVIEW` | `"review"` |
| `ADMIN` | `"admin"` |

### B.4 `SeriesState` (§4.4)

| Member | Value |
|---|---|
| `ACTIVE` | `"active"` |
| `RETIRED` | `"retired"` |
| `CANCELLED` | `"cancelled"` |

### B.5 `TimerMode` (§4.7)

| Member | Value |
|---|---|
| `STOPWATCH` | `"stopwatch"` |
| `TIMER` | `"timer"` |
| `POMODORO` | `"pomodoro"` |

### B.6 `TimerPhase` (§4.7)

| Member | Value |
|---|---|
| `FOCUS` | `"focus"` |
| `BREAK` | `"break"` |

### B.7 `ReminderState` (§4.6)

| Member | Value |
|---|---|
| `PENDING` | `"pending"` |
| `SENT` | `"sent"` |
| `CANCELLED` | `"cancelled"` |

### B.8 `BucketLevel` (§4.3)

| Member | Value |
|---|---|
| `YEAR` | `"Y"` |
| `MONTH` | `"M"` |
| `WEEK` | `"W"` |
| `DAY` | `"D"` |

### B.9 `ReviewTier` (§4.4)

| Member | Value |
|---|---|
| `HARD` | `"hard"` |
| `MEDIUM` | `"medium"` |
| `EASY` | `"easy"` |
| `CUSTOM` | `"custom"` |

---

## C. Tool schemas (§5.5)

All 27 tools. Each tool has a name, a parameter schema (JSON Schema object),
and a return type. Dates in tool arguments are absolute ISO-8601 in the
instance timezone (§5.5). The model never emits a bare "day 8".

### C.1 `create_node`

Creates a project, task, or subtask.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | `string` | yes | Node title |
| `kind` | `string` (NodeKind) | yes | `project`, `task`, or `subtask` |
| `parent_id` | `string` | no | Parent node id; omit for root |
| `notes` | `string` | no | Free-text notes |
| `tag_ids` | `array[string]` | no | Tag ids to apply at creation |

**Returns:** `Node`

### C.2 `update_node`

Updates an existing node.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | yes | Node to update |
| `title` | `string` | no | New title |
| `notes` | `string` | no | New notes |
| `status` | `string` (NodeStatus) | no | New status |
| `parent_id` | `string` | no | New parent (re-parent) |

**Returns:** `Node`

### C.3 `delete_node`

Deletes a node and cascades to children.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | yes | Node to delete |

**Returns:** `{ "deleted": boolean, "cascade_count": integer }`

### C.4 `link_nodes`

Creates a non-structural link between two nodes (§4.1).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `source_id` | `string` | yes | Source node |
| `target_id` | `string` | yes | Target node |

**Returns:** `{ "link_id": string }`

### C.5 `tag_node`

Applies a tag to a task or subtask (§4.1 — never to projects).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | yes | Node to tag |
| `tag_id` | `string` | yes | Tag to apply |

**Returns:** `NodeTag`

### C.6 `untag_node`

Removes a tag from a node.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | yes | Node to untag |
| `tag_id` | `string` | yes | Tag to remove |

**Returns:** `{ "removed": boolean }`

### C.7 `create_event`

Creates an event. If the event overlaps an existing non-deleted event, it is
pushed to the first free minute satisfying duration, hard blocks, and day
bounds (§6). The response carries both the requested and the actual slot.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | `string` | yes | Event title |
| `start_ms` | `integer` | yes | Requested start, epoch ms |
| `end_ms` | `integer` | yes | Requested end, epoch ms |
| `node_id` | `string` | no | Associated node; omit for ad-hoc |
| `kind` | `string` (EventKind) | no | Default `focus` |
| `bucket_id` | `string` | no | Target bucket |
| `reminder_offsets` | `array[integer]` | no | Minutes before start; default `[10, 0]` |

**Returns:** `{ "event": Event, "requested_start_ms": integer, "requested_end_ms": integer, "actual_start_ms": integer, "actual_end_ms": integer, "pushed": boolean }`

### C.8 `update_event`

Updates an existing event.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `event_id` | `string` | yes | Event to update |
| `title` | `string` | no | New title |
| `start_ms` | `integer` | no | New start, epoch ms |
| `end_ms` | `integer` | no | New end, epoch ms |
| `node_id` | `string` | no | New node association |
| `kind` | `string` (EventKind) | no | New kind |

**Returns:** `{ "event": Event, "pushed": boolean }`

### C.9 `delete_event`

Soft-deletes an event. Soft-deleted events are not conflicts (§6).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `event_id` | `string` | yes | Event to delete |

**Returns:** `{ "deleted": boolean }`

### C.10 `schedule_series`

Creates a review series and writes all review events in one transaction (§4.4).
A series must be bounded — `max_count` and/or `ends_on_ms`, at least one.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | yes | The completed node that started the series |
| `tier` | `string` (ReviewTier) | yes | `hard`, `medium`, `easy`, or `custom` |
| `offsets_days` | `array[integer]` | no | Required if `tier=custom`; ignored otherwise |
| `max_count` | `integer` | no | Max number of reviews |
| `ends_on_ms` | `integer` | no | Series end date, epoch ms |

**Returns:** `{ "series": ReviewSeries, "events": array[Event] }`

### C.11 `delete_series`

Deletes a series and all its review events in one transaction (§4.4).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `series_id` | `string` | yes | Series to delete |

**Returns:** `{ "deleted": boolean, "event_count": integer }`

### C.12 `reschedule_series`

Bulk-reschedules all future review events in a series (§4.4).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `series_id` | `string` | yes | Series to reschedule |
| `new_offsets_days` | `array[integer]` | no | New offsets from today |
| `tier` | `string` (ReviewTier) | no | Change tier |

**Returns:** `{ "series": ReviewSeries, "events": array[Event] }`

### C.13 `search_nodes`

Searches nodes by keyword and/or semantic similarity (§4.8).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | `string` | yes | Search query |
| `limit` | `integer` | no | Max results, default 10 |
| `semantic` | `boolean` | no | Use sqlite-vec, default true |

**Returns:** `array[Node]`

### C.14 `check_conflict`

Checks for semantic duplicates and hard conflicts in a window (§6).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `start_ms` | `integer` | yes | Window start, epoch ms |
| `end_ms` | `integer` | yes | Window end, epoch ms |
| `window_days` | `integer` | no | Semantic duplicate window, default 1, max 7 |

**Returns:** `{ "hard_conflicts": array[Event], "semantic_candidates": array[Node] }`

### C.15 `find_free_slots`

Finds free time slots in a range (§6).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `start_ms` | `integer` | yes | Range start, epoch ms |
| `end_ms` | `integer` | yes | Range end, epoch ms |
| `duration_min` | `integer` | yes | Required slot duration in minutes |
| `max_results` | `integer` | no | Max slots to return, default 5 |

**Returns:** `array[{ "start_ms": integer, "end_ms": integer }]`

### C.16 `get_free_time`

Returns the total free time in a range.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `start_ms` | `integer` | yes | Range start, epoch ms |
| `end_ms` | `integer` | yes | Range end, epoch ms |

**Returns:** `{ "free_minutes": integer, "busy_minutes": integer }`

### C.17 `create_schedule`

Creates a recurring commitment (§4.5).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | `string` | yes | Schedule title |
| `starts_ms` | `integer` | yes | Start date, epoch ms |
| `ends_at_ms` | `integer` | yes | End date, epoch ms |
| `start_minute` | `integer` | yes | Minute of day (0..1439) |
| `duration_min` | `integer` | yes | Duration in minutes |
| `weekdays` | `array[integer]` | yes | ISO weekdays [1..7] |
| `hard_block` | `boolean` | no | Default true |
| `paused` | `boolean` | no | Default false |

**Returns:** `Schedule`

### C.18 `update_schedule`

Updates an existing schedule.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `schedule_id` | `string` | yes | Schedule to update |
| `title` | `string` | no | New title |
| `starts_ms` | `integer` | no | New start date |
| `ends_at_ms` | `integer` | no | New end date |
| `start_minute` | `integer` | no | New minute of day |
| `duration_min` | `integer` | no | New duration |
| `weekdays` | `array[integer]` | no | New weekdays |
| `hard_block` | `boolean` | no | New hard_block flag |
| `paused` | `boolean` | no | New paused flag |

**Returns:** `Schedule`

### C.19 `pause_schedule`

Pauses or unpauses a schedule. Paused schedules do not block (§4.5).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `schedule_id` | `string` | yes | Schedule to pause/unpause |
| `paused` | `boolean` | yes | true to pause, false to resume |

**Returns:** `Schedule`

### C.20 `start_timer`

Starts a timer session. Only one timer runs at a time across all modes (§4.7).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | no | Associated node |
| `label` | `string` | yes | Session label |
| `mode` | `string` (TimerMode) | yes | `stopwatch`, `timer`, or `pomodoro` |
| `target_ms` | `integer` | no | Target duration for timer/pomodoro; ignored for stopwatch |
| `source` | `string` | yes | Device id |

**Returns:** `TimerSession`

### C.21 `stop_timer`

Stops the running timer.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `source` | `string` | yes | Device id |

**Returns:** `TimerSession`

### C.22 `log_time`

Logs time for a node. Reports per node: the node's own total, the total
including descendants, and the project total for a tagged task (§4.7).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `node_id` | `string` | yes | Node to log time for |
| `start_ms` | `integer` | yes | Session start, epoch ms |
| `end_ms` | `integer` | yes | Session end, epoch ms |
| `mode` | `string` (TimerMode) | yes | Session mode |
| `phase` | `string` (TimerPhase) | no | Pomodoro phase |

**Returns:** `{ "node_total_ms": integer, "descendant_total_ms": integer, "project_total_ms": integer }`

### C.23 `get_day`

Returns the day view for a given date.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `date` | `string` (ISO-8601) | yes | Date in instance timezone |

**Returns:** `{ "date": string, "events": array[Event], "buckets": array[Bucket], "timer": TimerSession | null }`

### C.24 `get_week`

Returns the week view for a given date.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `date` | `string` (ISO-8601) | yes | Any date within the target week |

**Returns:** `{ "week_start": string, "week_end": string, "events": array[Event], "buckets": array[Bucket] }`

### C.25 `get_month`

Returns the month view for a given date.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `date` | `string` (ISO-8601) | yes | Any date within the target month |

**Returns:** `{ "month_start": string, "month_end": string, "events": array[Event], "buckets": array[Bucket] }`

### C.26 `get_briefing`

Returns the daily briefing: unallocated tasks, rollover, due reviews, at most
one question (§5.7).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `date` | `string` (ISO-8601) | yes | Briefing date in instance timezone |

**Returns:** `{ "date": string, "unallocated_tasks": array[Node], "rollover": array[Node], "due_reviews": array[Event], "question": string | null }`

### C.27 `ask_question`

Asks the user a clarification question. One proactive question per day by
default (§5.7).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `question` | `string` | yes | The question to ask |
| `context` | `string` | no | Context for the question |

**Returns:** `{ "question_id": string, "queued": boolean }`

---

## D. Protocols

Protocols define the interfaces that `contracts/` exposes to the rest of the
system. They are implemented in `db/`, `core/`, `ai/`, `notify/`, etc.

### D.1 `Repo` protocols

One protocol per entity, plus a generic base. All repo protocols are
`runtime_checkable` so they can be used with `isinstance`.

#### D.1.1 `NodeRepo`

```python
class NodeRepo(Protocol):
    def create(self, node: Node) -> Node: ...
    def get(self, node_id: str) -> Optional[Node]: ...
    def update(self, node: Node) -> Node: ...
    def delete(self, node_id: str) -> int: ...  # returns cascade count
    def list_children(self, parent_id: Optional[str]) -> list[Node]: ...
    def list_all(self) -> list[Node]: ...
    def find_by_title(self, title: str) -> list[Node]: ...
```

#### D.1.2 `TagRepo`

```python
class TagRepo(Protocol):
    def create(self, tag: Tag) -> Tag: ...
    def get(self, tag_id: str) -> Optional[Tag]: ...
    def get_by_name(self, name: str) -> Optional[Tag]: ...
    def list_all(self) -> list[Tag]: ...
    def delete(self, tag_id: str) -> bool: ...
```

#### D.1.3 `NodeTagRepo`

```python
class NodeTagRepo(Protocol):
    def add(self, node_id: str, tag_id: str) -> NodeTag: ...
    def remove(self, node_id: str, tag_id: str) -> bool: ...
    def list_for_node(self, node_id: str) -> list[Tag]: ...
    def list_for_tag(self, tag_id: str) -> list[Node]: ...
```

#### D.1.4 `EventRepo`

```python
class EventRepo(Protocol):
    def create(self, event: Event) -> Event: ...
    def get(self, event_id: str) -> Optional[Event]: ...
    def update(self, event: Event) -> Event: ...
    def delete(self, event_id: str) -> bool: ...  # soft delete
    def hard_delete(self, event_id: str) -> bool: ...
    def list_range(self, start_ms: int, end_ms: int) -> list[Event]: ...
    def list_for_node(self, node_id: str) -> list[Event]: ...
    def list_for_series(self, series_id: str) -> list[Event]: ...
    def find_overlapping(self, start_ms: int, end_ms: int) -> list[Event]: ...
    def find_soft_deleted(self, start_ms: int, end_ms: int) -> list[Event]: ...
```

#### D.1.5 `BucketRepo`

```python
class BucketRepo(Protocol):
    def create(self, bucket: Bucket) -> Bucket: ...
    def get(self, bucket_id: str) -> Optional[Bucket]: ...
    def get_by_level_and_date(self, level: BucketLevel, date_ms: int) -> Optional[Bucket]: ...
    def list_children(self, parent_id: str) -> list[Bucket]: ...
    def list_at_level(self, level: BucketLevel) -> list[Bucket]: ...
    def get_chain(self, bucket_id: str) -> list[Bucket]: ...  # Y→M→W→D
    def seed(self, years: int = 10) -> int: ...  # returns rows created
```

#### D.1.6 `ReviewSeriesRepo`

```python
class ReviewSeriesRepo(Protocol):
    def create(self, series: ReviewSeries, events: list[Event]) -> ReviewSeries: ...
    def get(self, series_id: str) -> Optional[ReviewSeries]: ...
    def update(self, series: ReviewSeries) -> ReviewSeries: ...
    def delete(self, series_id: str) -> int: ...  # returns event count deleted
    def list_for_node(self, node_id: str) -> list[ReviewSeries]: ...
    def list_active(self) -> list[ReviewSeries]: ...
```

#### D.1.7 `ScheduleRepo`

```python
class ScheduleRepo(Protocol):
    def create(self, schedule: Schedule) -> Schedule: ...
    def get(self, schedule_id: str) -> Optional[Schedule]: ...
    def update(self, schedule: Schedule) -> Schedule: ...
    def delete(self, schedule_id: str) -> bool: ...
    def list_all(self) -> list[Schedule]: ...
    def list_active(self) -> list[Schedule]: ...
    def list_blocking(self, start_ms: int, end_ms: int) -> list[Schedule]: ...
```

#### D.1.8 `ReminderRepo`

```python
class ReminderRepo(Protocol):
    def create(self, reminder: Reminder) -> Reminder: ...
    def get(self, reminder_id: str) -> Optional[Reminder]: ...
    def update(self, reminder: Reminder) -> Reminder: ...
    def delete(self, reminder_id: str) -> bool: ...
    def list_for_event(self, event_id: str) -> list[Reminder]: ...
    def list_due(self, now_ms: int) -> list[Reminder]: ...
    def list_pending(self) -> list[Reminder]: ...
```

#### D.1.9 `TimerSessionRepo`

```python
class TimerSessionRepo(Protocol):
    def create(self, session: TimerSession) -> TimerSession: ...
    def get(self, session_id: str) -> Optional[TimerSession]: ...
    def update(self, session: TimerSession) -> TimerSession: ...
    def get_running(self) -> Optional[TimerSession]: ...
    def list_for_node(self, node_id: str) -> list[TimerSession]: ...
    def list_reconciled(self) -> list[TimerSession]: ...
    def mark_reconciled(self, session_id: str) -> TimerSession: ...
    def get_node_total(self, node_id: str) -> int: ...  # ms
    def get_descendant_total(self, node_id: str) -> int: ...  # ms
    def get_project_total(self, node_id: str) -> int: ...  # ms
```

#### D.1.10 `AuditRepo`

```python
class AuditRepo(Protocol):
    def log(self, entry: AuditEntry) -> AuditEntry: ...
    def list_recent(self, limit: int = 100) -> list[AuditEntry]: ...
    def prune(self, before_ms: int) -> int: ...  # returns rows deleted
```

### D.2 `Clock`

Provides the current time. Abstracts time for testability.

```python
class Clock(Protocol):
    def now_ms(self) -> int: ...  # current epoch ms
    def today_start_ms(self) -> int: ...  # start of today in instance tz
    def to_local(self, epoch_ms: int) -> datetime: ...  # to instance tz
    def to_utc(self, dt: datetime) -> int: ...  # from instance tz to epoch ms
    def snap_to_minute(self, epoch_ms: int) -> int: ...  # snap to 1-min grid
```

### D.3 `IdGen`

Generates unique identifiers.

```python
class IdGen(Protocol):
    def new_id(self) -> str: ...  # returns uuid4 string
```

### D.4 `Embedder`

Generates embeddings for semantic search (§4.8).

```python
class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...  # returns 768-dim vector
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    def dimension(self) -> int: ...  # returns 768
```

### D.5 `Notifier`

Sends notifications (§10). Abstracts ntfy so Gotify can be added later.

```python
class Notifier(Protocol):
    def send(self, title: str, message: str, priority: str = "default") -> bool: ...
    def send_reminder(self, reminder: Reminder, event: Event) -> bool: ...
    def send_proposal(self, proposal_id: str, message: str) -> bool: ...
    def send_question(self, question_id: str, question: str) -> bool: ...
```

### D.6 `SearchBackend`

Three-stage search: FTS5 narrows, sqlite-vec ranks, model judges (§4.8).

```python
class SearchBackend(Protocol):
    def index_node(self, node: Node) -> None: ...
    def remove_node(self, node_id: str) -> None: ...
    def search_keyword(self, query: str, limit: int = 10) -> list[Node]: ...
    def search_semantic(self, query: str, limit: int = 10) -> list[tuple[Node, float]]: ...
    def search_combined(self, query: str, limit: int = 10) -> list[tuple[Node, float]]: ...
```

---

## E. File layout

Every file in `chronos/contracts/` with its purpose and exports. The import
graph is a DAG with no cycles.

```
chronos/contracts/
  __init__.py          — re-exports everything below
  enums.py             — all enums (B.1–B.9)
  models.py            — all model dataclasses (A.1–A.10)
  tool_schemas.py      — ToolCall, ToolResult, TOOL_SCHEMAS (C.1–C.27)
  protocols.py         — all Protocol classes (D.1–D.6)
  ddl.py               — DDL constants and bucket seed spec (F)
```

### E.1 `chronos/contracts/__init__.py`

**Purpose:** Re-exports all public names from the submodules.

**Exports:**
- From `enums`: `NodeKind`, `NodeStatus`, `EventKind`, `SeriesState`, `TimerMode`, `TimerPhase`, `ReminderState`, `BucketLevel`, `ReviewTier`
- From `models`: `Node`, `Tag`, `NodeTag`, `Event`, `Bucket`, `ReviewSeries`, `Schedule`, `Reminder`, `TimerSession`, `AuditEntry`
- From `tool_schemas`: `ToolCall`, `ToolResult`, `TOOL_SCHEMAS`
- From `protocols`: `NodeRepo`, `TagRepo`, `NodeTagRepo`, `EventRepo`, `BucketRepo`, `ReviewSeriesRepo`, `ScheduleRepo`, `ReminderRepo`, `TimerSessionRepo`, `AuditRepo`, `Clock`, `IdGen`, `Embedder`, `Notifier`, `SearchBackend`
- From `ddl`: `DDL_STATEMENTS`, `BUCKET_SEED_SPEC`

### E.2 `chronos/contracts/enums.py`

**Purpose:** All enum definitions. No imports from other contracts modules.

**Imports:** `enum`

**Exports:** `NodeKind`, `NodeStatus`, `EventKind`, `SeriesState`, `TimerMode`, `TimerPhase`, `ReminderState`, `BucketLevel`, `ReviewTier`

### E.3 `chronos/contracts/models.py`

**Purpose:** All model dataclasses. Imports enums.

**Imports:** `enums`

**Exports:** `Node`, `Tag`, `NodeTag`, `Event`, `Bucket`, `ReviewSeries`, `Schedule`, `Reminder`, `TimerSession`, `AuditEntry`

### E.4 `chronos/contracts/tool_schemas.py`

**Purpose:** Tool call/result types and the 27 tool schemas. Imports models and enums.

**Imports:** `models`, `enums`

**Exports:** `ToolCall`, `ToolResult`, `TOOL_SCHEMAS`

### E.5 `chronos/contracts/protocols.py`

**Purpose:** All Protocol definitions. Imports models and enums for type hints.

**Imports:** `models`, `enums`

**Exports:** `NodeRepo`, `TagRepo`, `NodeTagRepo`, `EventRepo`, `BucketRepo`, `ReviewSeriesRepo`, `ScheduleRepo`, `ReminderRepo`, `TimerSessionRepo`, `AuditRepo`, `Clock`, `IdGen`, `Embedder`, `Notifier`, `SearchBackend`

### E.6 `chronos/contracts/ddl.py`

**Purpose:** DDL constants and bucket seed spec. No imports from other contracts modules.

**Imports:** none

**Exports:** `DDL_STATEMENTS`, `BUCKET_SEED_SPEC`

### E.7 Import graph (DAG)

```
enums.py  (no imports from contracts/)
  ↑
models.py  (imports enums)
  ↑
tool_schemas.py  (imports models, enums)
  ↑
__init__.py  (imports all)

protocols.py  (imports models, enums)
  ↑
__init__.py  (imports all)

ddl.py  (no imports from contracts/)
  ↑
__init__.py  (imports all)
```

No cycles. `enums.py` and `ddl.py` are leaves. `models.py` depends only on
`enums.py`. `tool_schemas.py` depends on `models.py` and `enums.py`.
`protocols.py` depends on `models.py` and `enums.py`. `__init__.py` depends on
everything.

---

## F. DDL summary

### F.1 `nodes` (§4.1)

```sql
CREATE TABLE nodes (
    id         TEXT PRIMARY KEY,
    parent_id  TEXT REFERENCES nodes(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    notes      TEXT,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    done_at    INTEGER
);
CREATE INDEX ix_nodes_parent ON nodes(parent_id);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `parent_id` | TEXT | FK → nodes(id), ON DELETE CASCADE, nullable |
| `kind` | TEXT | NOT NULL |
| `title` | TEXT | NOT NULL |
| `notes` | TEXT | nullable |
| `status` | TEXT | NOT NULL, DEFAULT 'active' |
| `created_at` | INTEGER | NOT NULL |
| `updated_at` | INTEGER | NOT NULL |
| `done_at` | INTEGER | nullable |

**Indexes:** `ix_nodes_parent` on `(parent_id)`

### F.2 `tags` (§4.1)

```sql
CREATE TABLE tags (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    color TEXT
);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `name` | TEXT | NOT NULL, UNIQUE |
| `color` | TEXT | nullable |

### F.3 `node_tags` (§4.1)

```sql
CREATE TABLE node_tags (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    tag_id  TEXT NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (node_id, tag_id)
);
```

| Column | Type | Constraints |
|---|---|---|
| `node_id` | TEXT | PK, FK → nodes(id), ON DELETE CASCADE |
| `tag_id` | TEXT | PK, FK → tags(id), ON DELETE CASCADE |

### F.4 `events` (§4.2)

```sql
CREATE TABLE events (
    id           TEXT PRIMARY KEY,
    node_id      TEXT REFERENCES nodes(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    start_ms     INTEGER NOT NULL,
    end_ms       INTEGER NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'focus',
    bucket_id    TEXT REFERENCES buckets(id),
    series_id    TEXT,
    review_index INTEGER,
    derived_from TEXT,
    soft_deleted  INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);
CREATE INDEX ix_events_window ON events(start_ms, end_ms);
CREATE INDEX ix_events_series ON events(series_id);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `node_id` | TEXT | FK → nodes(id), ON DELETE CASCADE, nullable |
| `title` | TEXT | NOT NULL |
| `start_ms` | INTEGER | NOT NULL |
| `end_ms` | INTEGER | NOT NULL |
| `kind` | TEXT | NOT NULL, DEFAULT 'focus' |
| `bucket_id` | TEXT | FK → buckets(id), nullable |
| `series_id` | TEXT | nullable |
| `review_index` | INTEGER | nullable |
| `derived_from` | TEXT | nullable |
| `soft_deleted` | INTEGER | NOT NULL, DEFAULT 0 |
| `created_at` | INTEGER | NOT NULL |

**Indexes:** `ix_events_window` on `(start_ms, end_ms)`, `ix_events_series` on `(series_id)`

### F.5 `buckets` (§4.3)

```sql
CREATE TABLE buckets (
    id        TEXT PRIMARY KEY,
    level     TEXT NOT NULL,
    parent_id TEXT REFERENCES buckets(id),
    start_ms  INTEGER NOT NULL,
    end_ms    INTEGER NOT NULL,
    seq       INTEGER NOT NULL
);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `level` | TEXT | NOT NULL |
| `parent_id` | TEXT | FK → buckets(id), nullable (NULL for year buckets) |
| `start_ms` | INTEGER | NOT NULL |
| `end_ms` | INTEGER | NOT NULL |
| `seq` | INTEGER | NOT NULL |

### F.6 `review_series` (§4.4)

```sql
CREATE TABLE review_series (
    id             TEXT PRIMARY KEY,
    node_id        TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    tier           TEXT NOT NULL,
    offsets_days   TEXT NOT NULL,
    anchor_node_id TEXT NOT NULL,
    max_count      INTEGER,
    ends_on_ms     INTEGER,
    state          TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    CHECK (max_count IS NOT NULL OR ends_on_ms IS NOT NULL)
);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `node_id` | TEXT | NOT NULL, FK → nodes(id), ON DELETE CASCADE |
| `tier` | TEXT | NOT NULL |
| `offsets_days` | TEXT | NOT NULL (JSON int array) |
| `anchor_node_id` | TEXT | NOT NULL |
| `max_count` | INTEGER | nullable |
| `ends_on_ms` | INTEGER | nullable |
| `state` | TEXT | NOT NULL |
| `created_at` | INTEGER | NOT NULL |

**Check constraint:** `max_count IS NOT NULL OR ends_on_ms IS NOT NULL`

### F.7 `schedules` (§4.5)

```sql
CREATE TABLE schedules (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    starts_ms      INTEGER NOT NULL,
    ends_at_ms     INTEGER NOT NULL,
    start_minute   INTEGER NOT NULL,
    duration_min   INTEGER NOT NULL,
    weekdays       TEXT NOT NULL,
    hard_block     INTEGER NOT NULL DEFAULT 1,
    paused         INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL
);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `title` | TEXT | NOT NULL |
| `starts_ms` | INTEGER | NOT NULL |
| `ends_at_ms` | INTEGER | NOT NULL |
| `start_minute` | INTEGER | NOT NULL |
| `duration_min` | INTEGER | NOT NULL |
| `weekdays` | TEXT | NOT NULL (JSON int array) |
| `hard_block` | INTEGER | NOT NULL, DEFAULT 1 |
| `paused` | INTEGER | NOT NULL, DEFAULT 0 |
| `created_at` | INTEGER | NOT NULL |

### F.8 `reminders` (§4.6)

```sql
CREATE TABLE reminders (
    id           TEXT PRIMARY KEY,
    event_id     TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    fire_at_ms   INTEGER NOT NULL,
    offset_min   INTEGER NOT NULL,
    state        TEXT NOT NULL DEFAULT 'pending',
    channel      TEXT NOT NULL DEFAULT 'ntfy',
    created_at   INTEGER NOT NULL
);
CREATE INDEX ix_reminders_due ON reminders(state, fire_at_ms);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `event_id` | TEXT | NOT NULL, FK → events(id), ON DELETE CASCADE |
| `fire_at_ms` | INTEGER | NOT NULL |
| `offset_min` | INTEGER | NOT NULL |
| `state` | TEXT | NOT NULL, DEFAULT 'pending' |
| `channel` | TEXT | NOT NULL, DEFAULT 'ntfy' |
| `created_at` | INTEGER | NOT NULL |

**Indexes:** `ix_reminders_due` on `(state, fire_at_ms)`

### F.9 `timer_sessions` (§4.7)

```sql
CREATE TABLE timer_sessions (
    id         TEXT PRIMARY KEY,
    node_id    TEXT REFERENCES nodes(id),
    label      TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,
    source     TEXT NOT NULL,
    reconciled INTEGER NOT NULL DEFAULT 0,
    mode       TEXT NOT NULL DEFAULT 'stopwatch',
    target_ms  INTEGER,
    phase      TEXT,
    cycle      INTEGER NOT NULL DEFAULT 1
);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `node_id` | TEXT | FK → nodes(id), nullable |
| `label` | TEXT | NOT NULL |
| `started_at` | INTEGER | NOT NULL |
| `ended_at` | INTEGER | nullable (NULL = running) |
| `source` | TEXT | NOT NULL |
| `reconciled` | INTEGER | NOT NULL, DEFAULT 0 |
| `mode` | TEXT | NOT NULL, DEFAULT 'stopwatch' |
| `target_ms` | INTEGER | nullable |
| `phase` | TEXT | nullable |
| `cycle` | INTEGER | NOT NULL, DEFAULT 1 |

### F.10 `settings` (§4.7)

```sql
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

| Column | Type | Constraints |
|---|---|---|
| `key` | TEXT | PRIMARY KEY |
| `value` | TEXT | NOT NULL |

### F.11 `audit` (§4.7)

```sql
CREATE TABLE audit (
    id        INTEGER PRIMARY KEY,
    at        INTEGER NOT NULL,
    device_id TEXT,
    action    TEXT NOT NULL,
    target    TEXT,
    context   TEXT,
    cost_usd  REAL
);
```

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | PRIMARY KEY, autoincrement |
| `at` | INTEGER | NOT NULL |
| `device_id` | TEXT | nullable |
| `action` | TEXT | NOT NULL |
| `target` | TEXT | nullable |
| `context` | TEXT | nullable |
| `cost_usd` | REAL | nullable |

### F.12 `node_fts` (§4.8)

```sql
CREATE VIRTUAL TABLE node_fts USING fts5(title, notes, content='');
```

### F.13 `node_vec` (§4.8)

```sql
CREATE VIRTUAL TABLE node_vec USING vec0(
    node_id    TEXT PRIMARY KEY,
    embedding FLOAT[768]
);
```

### F.14 Bucket seed spec (§4.3)

**Scope:** First run creates exactly **10 years** forward from the instance
timezone's current date.

**Expected row counts:**

| Level | Count | Notes |
|---|---|---|
| Year | 10 | `Y:2026` through `Y:2035` |
| Month | ~120 | ~12 per year |
| Week | ~522 | ~52.2 per year |
| Day | ~3653 | ~365.3 per year |
| **Total** | **~4303** | |

**Nesting:** Y → M → W → D. A day's parent is the **week** that contains it;
a week's parent is its month; a month's parent is its year.

**ID formats:**
- Year: `Y:2026`
- Month: `M:2026-08`
- Week: `W:2026-W31` (ISO week number of the week's own start date)
- Day: `D:2026-08-04`

**Idempotency:** The seed is idempotent — running it twice does not create
duplicate rows. Implemented as `INSERT OR IGNORE` or equivalent.

**Auto-extension:** A background job extends the range whenever fewer than 180
days remain (§4.3).

---

## G. Spec ambiguities and open questions

1. **`node_links` table (§4.1):** The spec mentions `node_links` for
   non-structural links but does not provide DDL. The `link_nodes` tool (C.4)
   implies a table exists. **Proposal:** Add a `node_links` table with
   `(source_id, target_id, PRIMARY KEY (source_id, target_id))` and FKs to
   `nodes(id)` with ON DELETE CASCADE. Confirm with Manager.

2. **`ReviewSeries.offsets_days` for non-custom tiers (§4.4):** The spec says
   the AI picks the tier and can be overruled. When `tier` is not `custom`,
   `offsets_days` is derived from the tier defaults. **Proposal:** The
   `schedule_series` tool ignores `offsets_days` when `tier != "custom"` and
   uses the tier defaults. The stored `offsets_days` always reflects the
   actual offsets used. Confirm with Manager.

3. **`Event.bucket_id` vs. scheduling (§4.3):** The spec says "An unallocated
   task points at one bucket level. Scheduling walks it down: bucket → day →
   minutes." It is unclear whether `bucket_id` on an event is set at creation
   time or only after scheduling. **Proposal:** `bucket_id` is nullable at
   creation and set by the scheduler when the event is placed. Confirm with
   Manager.

4. **`TimerSession.target_ms` for pomodoro (§4.7):** The spec says a pomodoro
   alternates focus and break phases across `cycle`. It is unclear whether
   `target_ms` is the focus duration, break duration, or total session target.
   **Proposal:** `target_ms` is the focus duration; break duration is derived
   from the pomodoro preset (default 25/5 × 4). Confirm with Manager.

5. **`AuditEntry.id` autoincrement (§4.7):** The DDL shows `INTEGER PRIMARY KEY`
   which in SQLite is an alias for `rowid` and auto-assigns. **Proposal:**
   Use SQLite's native autoincrement behavior. Confirm with Manager.

6. **`Reminder.offset_min` sign convention (§4.6):** The spec says "10 minutes
   before and at the start." **Proposal:** `offset_min` is positive for
   "before" (e.g., 10 = 10 minutes before) and 0 for "at the start." The
   `fire_at_ms` is computed as `event.start_ms - offset_min * 60000`. Confirm
   with Manager.

7. **`Schedule.weekdays` JSON format (§4.5):** The spec says "JSON int array
   [1..7], ISO weekday." **Proposal:** Stored as `[1,2,3,4,5]` for Monday
   through Friday. Confirm with Manager.

8. **`Bucket.seq` range (§4.3):** The spec says "1..4 ordinal within the parent."
   This is ambiguous — months have up to 31 days, weeks have up to 53 weeks
   per year. **Proposal:** `seq` is the ordinal within the parent (1-based),
   not capped at 4. The "1..4" in the spec likely refers to the 4 levels, not
   the seq range. Confirm with Manager.

---

## H. Summary

This proposal covers the complete frozen interface surface for Phase 1:

- **10 models** with every field, type, default, and constraint
- **9 enums** with every member and value
- **27 tool schemas** with parameters and return types
- **16 protocols** (10 repo + 6 infrastructure) with full method signatures
- **6 files** in `chronos/contracts/` with a DAG import graph
- **13 DDL tables** + 2 virtual tables with all columns, types, constraints, and indexes
- **Bucket seed spec** with 10-year forward seeding, Y→M→W→D nesting, ~4300 rows

The proposal is detailed enough that a code agent can implement it without
re-reading the spec. All decisions are cited to the spec section.
