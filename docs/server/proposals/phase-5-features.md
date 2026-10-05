# Phase 5 — Interface Proposal: Features (notify, briefings, stats, search, audit, export)

**Status:** FROZEN — Phase 5 proposal approved
**Manager review:** All 10 ambiguities ruled on and approved. See `docs/decisions.md`.  
**Author:** Phase-5 Proposer  
**Date:** 2026-10-03  
**Spec source:** `docs/Chronos.md` §4.4, §4.5, §4.6, §4.7, §4.8, §5.4, §5.7, §6, §8.2, §9.1, §10  
**Phase doc:** `docs/phases/phase-5-features.md`  
**Frozen contracts:** `docs/proposals/phase-1-contracts.md`

---

## 0. Scope and principles

This document proposes the complete interface surface for Phase 5. It covers:

- **A.** Notifications — ntfy publisher, reminder scheduler, `DEFAULT_REMINDER_OFFSETS_MIN` (§4.6, §10)
- **B.** Search — three-stage FTS5 → sqlite-vec → model judge, dual Session/Connection support (§4.8, §6)
- **C.** Duplicate check — semantic duplicate detection, hierarchy reuse, tag deduplication (§6, §5.4)
- **D.** Briefings — generated daily briefing, clarification budget, question queue (§9.1, §5.7)
- **E.** Stats — counts, streaks, token spend by day, price table (§8.2, §4.7, §5.2)
- **F.** Audit viewer — browsable, filterable, read-only audit log (§4.7)
- **G.** CSV export — events, timers, cost with proper quoting (§8.2, §9.2)
- **H.** File layout — every file with purpose and exports

**Principles:**

1. Every module imports from `chronos/contracts/` and nothing else from its siblings (§2.1).
2. The import graph must be a DAG with no cycles.
3. All times are UTC epoch **milliseconds** (`INTEGER`) in the database (§4). ISO-8601 with offset at every API boundary (§7.3).
4. One instance timezone governs all bucket maths and rendering (§7.1).
5. The calendar grid is **1 minute** (§7.2).
6. `contracts/` is the frozen shared surface. This proposal announces deliberate additions to contracts (new constants, new models, new DDL tables) as required by Phase 5 features.
7. No module raises on a missing optional dependency (FTS5 table, sqlite-vec table, embedding model). Degrade gracefully (§4.8, phase doc).
8. Scores are **absolute** — never normalised. bm25 rank and vector distance are distinct fields (§4.8, phase doc).

---

## A. Notifications (§4.6, §10)

### A.1 Overview

ntfy is the only notification backend in scope (§10). It is accessed through the frozen `Notifier` protocol (contracts D.5) so Gotify can be added later without touching callers. One HTTP POST per publish (§10). The reminder scheduler runs on the realtime tick and publishes anything due (§4.6).

### A.2 `DEFAULT_REMINDER_OFFSETS_MIN`

**Spec:** §4.6 — "Default offsets are 10 minutes before and at the start." §5.4 — "the AI confirms the offset list before anything is committed."

**Decision:** `DEFAULT_REMINDER_OFFSETS_MIN` has **exactly one definition** in the whole project. It is added to `chronos/contracts/` as a new constant.

```python
# chronos/contracts/constants.py
DEFAULT_REMINDER_OFFSETS_MIN: list[int] = [10, 0]
```

- `10` = 10 minutes before the event start.
- `0` = at the event start.
- The `create_event` tool schema (contracts C.7) already defaults `reminder_offsets` to `[10, 0]`. The tool implementation imports this constant rather than hardcoding the list.
- The AI layer (§5.4) imports this constant when proposing reminder offsets.

**Re-exported from:** `chronos/contracts/__init__.py`

### A.3 `NtfyNotifier`

**Spec:** §10 — "The server publishes to a topic with one HTTP POST." "Priorities map to review-due, proposal-awaiting and timer milestones."

**File:** `chronos/notify/ntfy.py`

**Imports:** `chronos.contracts` (Notifier, Reminder, Event, ReminderState)

```python
class NtfyNotifier:
    """ntfy HTTP publisher. One POST per message (§10)."""

    def __init__(self, server_url: str, topic: str, token: str | None = None) -> None:
        """
        Args:
            server_url: ntfy server base URL, e.g. "https://ntfy.sh"
            topic: ntfy topic name
            token: optional bearer token for authenticated topics
        """

    def send(self, title: str, message: str, priority: str = "default") -> bool:
        """
        Send a notification via one HTTP POST (§10).

        Args:
            title: notification title
            message: notification body
            priority: ntfy priority — "min", "low", "default", "high", "urgent"

        Returns:
            True if the HTTP POST succeeded (2xx), False otherwise.
        """

    def send_reminder(self, reminder: Reminder, event: Event) -> bool:
        """
        Send a reminder notification (§4.6).

        Args:
            reminder: the reminder row being fired
            event: the associated event

        Returns:
            True if the HTTP POST succeeded, False otherwise.
        """

    def send_proposal(self, proposal_id: str, message: str) -> bool:
        """
        Send a proposal-awaiting notification (§10).

        Args:
            proposal_id: the proposal identifier
            message: proposal summary

        Returns:
            True if the HTTP POST succeeded, False otherwise.
        """

    def send_question(self, question_id: str, question: str) -> bool:
        """
        Send a clarification question notification (§10, §5.7).

        Args:
            question_id: the question identifier
            question: the question text

        Returns:
            True if the HTTP POST succeeded, False otherwise.
        """
```

**Priority mapping (§10):**

| Context | ntfy priority |
|---|---|
| Review due | `"high"` |
| Proposal awaiting | `"default"` |
| Timer milestone | `"low"` |
| Reminder (10 min before) | `"default"` |
| Reminder (at start) | `"high"` |
| Question | `"default"` |

**HTTP details:**
- Method: `POST`
- URL: `{server_url}/{topic}`
- Headers: `Title: {title}`, `Priority: {priority}`, optional `Authorization: Bearer {token}`
- Body: `{message}` (plain text)
- One POST per call. No batching.

### A.4 `ReminderScheduler`

**Spec:** §4.6 — "The scheduler job runs on the realtime tick and publishes anything due." "A reminder row is a real row, not a derived value, so it can be cancelled individually." "Cancelled reminders never fire."

**File:** `chronos/notify/scheduler.py`

**Imports:** `chronos.contracts` (Reminder, ReminderState, Event, ReminderRepo, EventRepo, Notifier, Clock)

```python
class ReminderScheduler:
    """
    Publishes due reminders on each realtime tick (§4.6).

    The scheduler queries the ReminderRepo for pending reminders whose
    fire_at_ms <= now, sends each via the Notifier, and marks them SENT.
    Cancelled reminders (state = CANCELLED) are never fired.
    """

    def __init__(
        self,
        reminder_repo: ReminderRepo,
        event_repo: EventRepo,
        notifier: Notifier,
        clock: Clock,
    ) -> None:
        """
        Args:
            reminder_repo: reminder persistence
            event_repo: event lookup for reminder context
            notifier: notification backend (ntfy)
            clock: time source
        """

    def tick(self) -> int:
        """
        Fire all due reminders. Called on each realtime tick (§4.6).

        Returns:
            Number of reminders fired.

        Behaviour:
            1. now_ms = clock.now_ms()
            2. due = reminder_repo.list_due(now_ms)
            3. For each reminder:
               a. If reminder.state == ReminderState.CANCELLED: skip (§4.6 — cancelled never fire)
               b. event = event_repo.get(reminder.event_id)
               c. If event is None or event.soft_deleted: skip
               d. notifier.send_reminder(reminder, event)
               e. reminder.state = ReminderState.SENT
               f. reminder_repo.update(reminder)
            4. Return count of fired reminders.
        """

    def cancel(self, reminder_id: str) -> bool:
        """
        Cancel a reminder individually (§4.6).

        Args:
            reminder_id: the reminder to cancel

        Returns:
            True if the reminder was found and cancelled, False otherwise.

        Behaviour:
            1. reminder = reminder_repo.get(reminder_id)
            2. If reminder is None: return False
            3. reminder.state = ReminderState.CANCELLED
            4. reminder_repo.update(reminder)
            5. return True
        """
```

### A.5 Reminder lifecycle

**Spec:** §4.6 — "A reminder row is a real row, not a derived value, so it can be cancelled individually."

**Flow:**

1. **Creation:** When an event is created with `reminder_offsets` (contracts C.7), the repo creates one `Reminder` row per offset. Each row has:
   - `fire_at_ms = event.start_ms - offset_min * 60000`
   - `offset_min` = the offset value (10 or 0)
   - `state = ReminderState.PENDING`
   - `channel = "ntfy"`

2. **Firing:** The scheduler's `tick()` method fires due reminders (§4.6).

3. **Cancellation:** A reminder can be cancelled individually via `ReminderScheduler.cancel()` or directly via `ReminderRepo.update()` with `state = CANCELLED`. Cancelled reminders never fire (§4.6, phase doc).

4. **Deletion:** When an event is deleted, its reminders cascade (FK ON DELETE CASCADE, contracts F.8).

### A.6 File layout: `chronos/notify/`

```
chronos/notify/
  __init__.py          — re-exports NtfyNotifier, ReminderScheduler
  ntfy.py              — NtfyNotifier (ntfy HTTP publisher)
  scheduler.py         — ReminderScheduler (realtime tick, cancel)
```

---

## B. Search (§4.8, §6)

### B.1 Overview

Search runs in three stages, all on the host (§4.8):

1. **FTS5** narrows candidates on keywords.
2. **sqlite-vec** ranks by cosine similarity.
3. **Model** judges whether the top hits are genuine duplicates.

The search module implements the frozen `SearchBackend` protocol (contracts D.6) and adds extended types for score-aware results.

### B.2 `SearchResult`

**Spec:** §4.8 — "FTS5 narrows candidates on keywords, sqlite-vec ranks them by cosine similarity." Phase doc — "Scores are absolute." "bm25 is not a similarity — keyword rank and vector distance are distinct fields."

**Decision:** A new `SearchResult` dataclass is added to `chronos/contracts/` to carry both scores as distinct fields.

```python
# chronos/contracts/models.py (addition)
@dataclass(frozen=True)
class SearchResult:
    """
    A search result with distinct keyword and vector scores (§4.8).

    Scores are absolute — never normalised (phase doc).
    bm25 rank and vector distance are different quantities (phase doc).
    """
    node: Node
    keyword_score: float | None      # bm25 rank from FTS5; None if keyword stage skipped
    vector_distance: float | None    # cosine distance from sqlite-vec; None if vec stage skipped
    combined_score: float | None     # fused score; None if not computed
```

**Re-exported from:** `chronos/contracts/__init__.py`

### B.3 `NodeSearch`

**Spec:** §4.8 — three-stage search. Phase doc — "Search must work against both a SQLAlchemy Session and a raw sqlite3.Connection." "Degrade at every step: a missing vec table means keywords only. Never raise." "Nodes must actually be indexed." "Best-effort: an absent FTS table must never break a write."

**File:** `chronos/db/search.py`

**Imports:** `chronos.contracts` (Node, SearchResult, SearchBackend, Embedder, DbConnection)

```python
# Type alias for dual connection support (phase doc)
DbConnection = Union[Session, sqlite3.Connection]


class NodeSearch(SearchBackend):
    """
    Three-stage node search: FTS5 → sqlite-vec → model judge (§4.8).

    Works against both SQLAlchemy Session and raw sqlite3.Connection (phase doc).
    Degrades gracefully: missing vec table → keywords only; missing FTS table →
    no indexing, no search results, never raises (phase doc).
    """

    def __init__(
        self,
        db: DbConnection,
        embedder: Embedder,
    ) -> None:
        """
        Args:
            db: database connection (Session or sqlite3.Connection)
            embedder: embedding model for semantic search
        """

    # ── Indexing lifecycle (§4.8, phase doc) ──────────────────────────

    def index_node(self, node: Node) -> None:
        """
        Index a node for search. Called on node create (phase doc).

        Best-effort: if the FTS5 table is absent, this is a no-op (phase doc).
        Writes to node_fts (title, notes) and node_vec (embedding).
        Never raises on a missing table.
        """

    def remove_node(self, node_id: str) -> None:
        """
        Remove a node from search indexes. Called on node delete (phase doc).

        Best-effort: if the FTS5 table is absent, this is a no-op (phase doc).
        Removes from node_fts and node_vec.
        Never raises on a missing table.
        """

    def reindex_node(self, node: Node) -> None:
        """
        Re-index a node. Called on node update (phase doc).

        Removes the old entry and re-inserts with the new title/notes/embedding.
        Best-effort: if the FTS5 table is absent, this is a no-op (phase doc).
        """

    # ── Search methods (contracts D.6) ───────────────────────────────

    def search_keyword(self, query: str, limit: int = 10) -> list[Node]:
        """
        Stage 1: FTS5 keyword search (§4.8).

        Args:
            query: search query string
            limit: max results

        Returns:
            Up to `limit` nodes matching the query, ranked by bm25.

        Degrade: if the FTS5 table is absent, returns [] (phase doc — never raise).
        """

    def search_semantic(self, query: str, limit: int = 10) -> list[tuple[Node, float]]:
        """
        Stage 2: sqlite-vec semantic search (§4.8).

        Args:
            query: search query string
            limit: max results

        Returns:
            Up to `limit` (node, cosine_distance) tuples, sorted by distance ascending.

        Degrade: if the vec table is absent, returns [] (phase doc — never raise).
        """

    def search_combined(self, query: str, limit: int = 10) -> list[tuple[Node, float]]:
        """
        Stages 1+2: FTS5 narrows, sqlite-vec ranks (§4.8).

        Args:
            query: search query string
            limit: max results

        Returns:
            Up to `limit` (node, combined_score) tuples.

        Degrade: if the vec table is absent, falls back to keyword-only results
        with keyword_score as the combined score (phase doc — never raise).
        """

    # ── Extended search with distinct scores (phase doc) ──────────────

    def search_with_scores(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Three-stage search returning distinct keyword and vector scores (§4.8, phase doc).

        Args:
            query: search query string
            limit: max results

        Returns:
            Up to `limit` SearchResult objects with:
            - keyword_score: bm25 rank from FTS5 (None if FTS absent)
            - vector_distance: cosine distance from sqlite-vec (None if vec absent)
            - combined_score: fused score (None if neither stage produced results)

        Degrade:
            - Missing vec table → keyword-only results, vector_distance = None (phase doc).
            - Missing FTS table → empty results (phase doc — never raise).
            - Both missing → empty results (phase doc — never raise).

        Scores are absolute — never normalised (phase doc).
        bm25 is not a similarity — keyword_score and vector_distance are distinct fields (phase doc).
        """

    # ── Internal helpers ──────────────────────────────────────────────

    def _has_fts_table(self) -> bool:
        """Check if the node_fts virtual table exists. Returns False if not."""

    def _has_vec_table(self) -> bool:
        """Check if the node_vec virtual table exists. Returns False if not."""

    def _get_connection(self) -> sqlite3.Connection:
        """
        Extract a raw sqlite3.Connection from either a Session or a Connection.

        This is the key to dual Session/Connection support (phase doc).
        If db is a Session, returns db.connection().driver_connection.
        If db is a sqlite3.Connection, returns it directly.
        """
```

### B.4 Dual Session/Connection support

**Spec:** Phase doc — "Search must work against both a SQLAlchemy Session (what the app uses) and a raw sqlite3.Connection (what tests pass)."

**Decision:** All `NodeSearch` methods accept `DbConnection = Union[Session, sqlite3.Connection]`. The `_get_connection()` helper extracts a raw `sqlite3.Connection` from either type. All SQL execution uses the raw connection.

**Why:** v1 shipped a version that silently returned nothing under a Session because a broad `except` swallowed the argument error (phase doc). The fix is to explicitly handle both types and narrow the catch to specific exceptions (`sqlite3.OperationalError` for missing tables).

### B.5 Degradation strategy

**Spec:** Phase doc — "Degrade at every step: a missing vec table means keywords only. Never raise."

| Stage | Missing component | Behaviour |
|---|---|---|
| Index (FTS) | `node_fts` table absent | No-op, write succeeds (phase doc) |
| Index (vec) | `node_vec` table absent | No-op, write succeeds (phase doc) |
| Search keyword | `node_fts` table absent | Return `[]` (phase doc) |
| Search semantic | `node_vec` table absent | Return `[]` (phase doc) |
| Search combined | `node_vec` table absent | Fall back to keyword-only (phase doc) |
| Search combined | `node_fts` table absent | Return `[]` (phase doc) |
| Search combined | Both tables absent | Return `[]` (phase doc) |

**Rule:** No search or indexing method ever raises due to a missing table. The `_has_fts_table()` and `_has_vec_table()` helpers check for table existence before attempting operations.

### B.6 Indexing lifecycle

**Spec:** Phase doc — "Nodes must actually be indexed. v1 shipped `create_node` that never wrote to the FTS table, so search returned nothing in the real app while the search tests passed. Index on create, re-index on update, remove on delete."

**Decision:** The `NodeRepo.create()`, `NodeRepo.update()`, and `NodeRepo.delete()` implementations (in `chronos/db/`, Phase 1) call `NodeSearch.index_node()`, `NodeSearch.reindex_node()`, and `NodeSearch.remove_node()` respectively. This is best-effort: if the FTS or vec table is absent, the indexing call is a no-op and the write succeeds (phase doc).

**Integration point:** The Phase 1 `NodeRepo` implementation receives a `NodeSearch` instance (or a callable) and invokes it after each write. The exact wiring is a Phase 1 implementation detail; this proposal specifies that the indexing calls happen and are best-effort.

### B.7 File layout: `chronos/db/search.py`

```
chronos/db/search.py  — NodeSearch, DbConnection, SearchResult re-export
```

---

## C. Duplicate check (§6, §5.4)

### C.1 Overview

**Spec:** §6 — "Before a create, FTS5 plus sqlite-vec search over ±1 day surfaces candidates that look like the same work. This warns and proposes; it never moves anything, because it can be wrong. The model returns a confidence and the user decides. The window may be widened through `check_conflict`, up to ±7 days."

§5.4 — "Before creating, search for an existing node that matches. Above a similarity threshold the existing one is reused rather than duplicated. Tags are never duplicated. An existing tag by name is always reused."

### C.2 `check_conflict` tool

**Spec:** Contracts C.14 — `check_conflict` returns `{ "hard_conflicts": array[Event], "semantic_candidates": array[Node] }`.

**Decision:** The `semantic_candidates` field is extended to carry scores. The return type becomes:

```json
{
  "hard_conflicts": array[Event],
  "semantic_candidates": array[SearchResult]
}
```

Where `SearchResult` is the new contracts type from §B.2. This change is backward-compatible: `SearchResult` contains the `Node` plus additional score fields.

**Implementation:** The `check_conflict` tool handler (in `chronos/api/` or `chronos/core/`, Phase 3) calls `NodeSearch.search_with_scores()` over the ±window and returns the results as `semantic_candidates`.

### C.3 Semantic duplicate detection

**Spec:** §6 — "FTS5 plus sqlite-vec search over ±1 day surfaces candidates."

**File:** `chronos/db/search.py` (duplicate check logic)

**Imports:** `chronos.contracts` (Node, SearchResult, NodeSearch, Event, EventRepo)

```python
DEFAULT_SEMANTIC_DUPLICATE_WINDOW_DAYS: int = 1   # §6 — ±1 day default
MAX_SEMANTIC_DUPLICATE_WINDOW_DAYS: int = 7       # §6 — up to ±7 days


def find_semantic_candidates(
    db: DbConnection,
    title: str,
    notes: str | None,
    target_ms: int,
    window_days: int = DEFAULT_SEMANTIC_DUPLICATE_WINDOW_DAYS,
    limit: int = 10,
) -> list[SearchResult]:
    """
    Find semantic duplicate candidates for a potential new node (§6).

    Searches over ±window_days from target_ms using FTS5 + sqlite-vec.
    Returns candidates with their scores. Never moves anything (§6).

    Args:
        db: database connection
        title: title of the potential new node
        notes: notes of the potential new node
        target_ms: epoch ms of the proposed creation time
        window_days: search window in days (default 1, max 7) (§6)
        limit: max candidates to return

    Returns:
        Up to `limit` SearchResult objects, sorted by combined_score descending.

    Raises:
        ValueError: if window_days > MAX_SEMANTIC_DUPLICATE_WINDOW_DAYS (§6 — max 7).
    """
```

**Behaviour:**
1. Validate `window_days <= 7` (§6 — "up to ±7 days"). Raise `ValueError` if exceeded.
2. Compute window: `[target_ms - window_days * 86400000, target_ms + window_days * 86400000]`.
3. Call `NodeSearch.search_with_scores(query=title, limit=limit * 3)` to get candidates.
4. Filter candidates to those created within the window.
5. Return up to `limit` candidates sorted by `combined_score` descending.

### C.4 Hierarchy reuse

**Spec:** §5.4 — "Before creating, search for an existing node that matches. Above a similarity threshold the existing one is reused rather than duplicated."

**Decision:** The reuse threshold is a configurable constant.

```python
# chronos/contracts/constants.py (addition)
DEFAULT_REUSE_SIMILARITY_THRESHOLD: float = 0.85
```

**Flow (AI layer, §5.4):**
1. Before calling `create_node`, the AI layer calls `find_semantic_candidates()` with the proposed title.
2. If any candidate has `combined_score >= DEFAULT_REUSE_SIMILARITY_THRESHOLD`, the AI layer reuses the existing node instead of creating a new one.
3. The AI layer reports the reuse decision to the user.

**Note:** The reuse logic lives in the AI layer (Phase 2/3), not in the search module. The search module provides the candidates; the AI layer decides.

### C.5 Tag deduplication

**Spec:** §5.4 — "Tags are never duplicated. An existing tag by name is always reused."

**Decision:** Before creating a tag, the AI layer calls `TagRepo.get_by_name()`. If a tag with the same name exists, its `id` is reused. No new tag row is created.

**Flow (AI layer, §5.4):**
1. Before calling `create_tag` (or equivalent), call `TagRepo.get_by_name(name)`.
2. If found: use the existing tag's `id`.
3. If not found: create the new tag.

**Note:** This is an AI layer behaviour, not a repo-level constraint. The `tags.name` UNIQUE constraint (contracts F.2) provides a database-level backstop.

### C.6 File layout

The duplicate check logic lives in `chronos/db/search.py` (§B.7). The hierarchy reuse and tag deduplication logic live in the AI layer (Phase 2/3) and are not part of Phase 5's file layout.

---

## D. Briefings (§9.1, §5.7)

### D.1 Overview

**Spec:** §9.1 — "Briefing — the daily planning session: unallocated tasks for today and this week, rollover, due reviews, at most one question." §5.7 — "One proactive question per day by default, queued in the briefing panel rather than blocking. When the day's budget is spent, questions roll into tomorrow's briefing. Configurable in Settings."

Phase doc — "Briefings are generated, not templated — the content must vary with the underlying data. A fixed template is not a briefing." "The budget must persist across a process restart." "The briefing reports what it considered — 'checked 30 tasks, showing 8'."

### D.2 `Briefing` result type

**Spec:** Contracts C.26 — `get_briefing` returns `{ "date": string, "unallocated_tasks": array[Node], "rollover": array[Node], "due_reviews": array[Event], "question": string | null }`.

**Decision:** A `Briefing` dataclass is added to `chronos/contracts/` for type safety.

```python
# chronos/contracts/models.py (addition)
@dataclass(frozen=True)
class Briefing:
    """
    Daily briefing content (§9.1).

    Generated, not templated — content varies with data (phase doc).
    """
    date: str                                    # ISO-8601 date
    unallocated_tasks_today: list[Node]          # unallocated tasks for today (§9.1)
    unallocated_tasks_week: list[Node]           # unallocated tasks for this week (§9.1)
    rollover: list[Node]                         # rollover tasks (§9.1)
    due_reviews: list[Event]                     # due reviews (§9.1)
    question: str | None                         # at most one question (§9.1, §5.7)
    considered_count: int                        # "checked 30 tasks" (§5.6, phase doc)
    shown_count: int                             # "showing 8" (§5.6, phase doc)
```

**Re-exported from:** `chronos/contracts/__init__.py`

### D.3 `BriefingGenerator`

**Spec:** §9.1 — briefing content. §5.6 — "The packer records what it cut so the UI can say 'checked 30 tasks, showing 8'." §5.7 — clarification budget.

**File:** `chronos/ai/briefings.py`

**Imports:** `chronos.contracts` (Briefing, Node, Event, NodeRepo, EventRepo, ReviewSeriesRepo, Clock, ClarificationBudget)

```python
class BriefingGenerator:
    """
    Generates the daily briefing (§9.1).

    Content is generated from the underlying data, not templated (phase doc).
    Reports what it considered — "checked 30 tasks, showing 8" (§5.6, phase doc).
    """

    def __init__(
        self,
        node_repo: NodeRepo,
        event_repo: EventRepo,
        series_repo: ReviewSeriesRepo,
        budget: ClarificationBudget,
        clock: Clock,
    ) -> None:
        """
        Args:
            node_repo: node persistence
            event_repo: event persistence
            series_repo: review series persistence
            budget: clarification budget tracker (§5.7)
            clock: time source
        """

    def generate(self, date: str) -> Briefing:
        """
        Generate the briefing for a given date (§9.1).

        Args:
            date: ISO-8601 date string in instance timezone

        Returns:
            Briefing with:
            - unallocated_tasks_today: tasks with no event scheduled today (§9.1)
            - unallocated_tasks_week: tasks with no event scheduled this week (§9.1)
            - rollover: tasks that were scheduled before today but not completed (§9.1)
            - due_reviews: review events due today (§9.1)
            - question: at most one clarification question (§9.1, §5.7)
            - considered_count: total tasks checked (§5.6)
            - shown_count: total tasks shown across all sections (§5.6)

        Behaviour:
            1. Query all active tasks (node_repo.list_all, filter kind=TASK, status=ACTIVE).
            2. For each task, check if it has an event today / this week.
            3. Unallocated = tasks with no event in the period.
            4. Rollover = tasks with events before today that are not done.
            5. Due reviews = events with kind=REVIEW and start_ms today.
            6. Question = budget.next_question() — at most one (§5.7).
            7. considered_count = total tasks checked.
            8. shown_count = len(unallocated_today) + len(unallocated_week) + len(rollover) + len(due_reviews).
            9. Content varies with data — no fixed template (phase doc).
        """
```

### D.4 `ClarificationBudget`

**Spec:** §5.7 — "One proactive question per day by default, queued in the briefing panel rather than blocking. When the day's budget is spent, questions roll into tomorrow's briefing. Configurable in Settings."

Phase doc — "The budget must persist across a process restart. v1's triage recorded this exact failure: 'counter is in memory, not persisted'. A fresh object built from the same database must see the day as spent."

**Decision:** The budget is persisted in the `settings` table (contracts F.10). A fresh `ClarificationBudget` built from the same database sees the day as spent.

**File:** `chronos/ai/briefings.py`

**Imports:** `chronos.contracts` (Clock)

```python
DEFAULT_CLARIFICATION_BUDGET_PER_DAY: int = 1   # §5.7 — one question per day


class ClarificationBudget:
    """
    Tracks the daily clarification question budget (§5.7).

    Persisted in the settings table — survives process restart (phase doc).
    One question per day by default; configurable via Settings (§5.7).
    """

    def __init__(self, db: DbConnection, clock: Clock) -> None:
        """
        Args:
            db: database connection (for settings persistence)
            clock: time source

        Loads the current budget state from the settings table.
        A fresh instance built from the same database sees the day as spent (phase doc).
        """

    @property
    def budget_per_day(self) -> int:
        """
        The configured daily budget (§5.7 — configurable in Settings).

        Default: 1 (§5.7).
        Stored in settings key "clarification.budget_per_day".
        """

    @property
    def used_today(self) -> int:
        """
        Number of questions already asked today.

        Stored in settings key "clarification.used_today".
        """

    @property
    def last_question_date(self) -> str | None:
        """
        The date (ISO-8601) when the last question was asked.

        Stored in settings key "clarification.last_question_date".
        None if no question has been asked yet.
        """

    def can_ask(self) -> bool:
        """
        Check if a question can be asked today (§5.7).

        Returns:
            True if used_today < budget_per_day, False otherwise.
        """

    def record_question(self) -> str:
        """
        Record that a question was asked (§5.7).

        Increments used_today and updates last_question_date.
        Persists to the settings table (phase doc — survives restart).

        Returns:
            The question_id (uuid4).

        Raises:
            BudgetExhausted: if used_today >= budget_per_day.
        """

    def next_question(self) -> str | None:
        """
        Get the next question to ask, or None if the budget is spent (§5.7).

        Returns:
            A question_id if the budget allows, None otherwise.
            When the budget is spent, questions roll into tomorrow's briefing (§5.7).
        """

    def reset_if_new_day(self) -> None:
        """
        Reset the daily counter if the date has changed (§5.7).

        Called on each briefing generation. If last_question_date != today,
        resets used_today to 0.
        """
```

**Settings keys:**

| Key | Value | Description |
|---|---|---|
| `clarification.budget_per_day` | `"1"` | Daily question budget (§5.7) |
| `clarification.used_today` | `"0"` | Questions asked today |
| `clarification.last_question_date` | `"2026-10-03"` | Date of last question |

**Persistence:** All state is stored in the `settings` table (contracts F.10). A fresh `ClarificationBudget` instance reads from the same table and sees the current state (phase doc — survives process restart).

### D.5 `Question` model

**Spec:** Contracts C.27 — `ask_question` returns `{ "question_id": string, "queued": boolean }`.

**Decision:** A `Question` dataclass is added to `chronos/contracts/` for the question queue.

```python
# chronos/contracts/models.py (addition)
@dataclass(frozen=True)
class Question:
    """
    A clarification question queued in the briefing panel (§5.7).
    """
    id: str                  # uuid4
    question: str            # the question text
    context: str | None      # optional context
    created_at: int          # epoch ms
    queued: bool = True       # True if queued in briefing panel (§5.7)
    answered_at: int | None = None  # epoch ms when answered
```

**Re-exported from:** `chronos/contracts/__init__.py`

### D.6 Question queue

**Spec:** §5.7 — "queued in the briefing panel rather than blocking."

**Decision:** Questions are stored in the `audit` table (contracts F.11) with `action = "question"`. The `context` field holds the question text. The `target` field holds the question_id.

Alternatively, a dedicated `questions` table can be added. Since the audit table already exists and is designed for logging, we use it for Phase 5. A dedicated table can be added in a future phase if needed.

**Query:** To get queued questions for the briefing panel:
```sql
SELECT * FROM audit
WHERE action = 'question'
  AND context IS NOT NULL
ORDER BY at DESC
LIMIT 1;
```

### D.7 File layout: `chronos/ai/briefings.py`

```
chronos/ai/briefings.py  — BriefingGenerator, ClarificationBudget, Question re-export
```

---

## E. Stats (§8.2, §4.7, §5.2)

### E.1 Overview

**Spec:** §8.2 — "GET /api/stats — counts, streaks, token spend by day." §4.7 — "Audit retention is 7 days. Log retention is 7 days." §5.2 — "Every attempt, failed or not, is written to the daily token-cost table."

Phase doc — "cost_usd comes from a real price table. An unknown price is None — never a fake 0.0."

### E.2 New DDL tables

**Decision:** Two new tables are added to the DDL for Phase 5.

#### E.2.1 `token_costs` (§5.2, §8.2)

```sql
CREATE TABLE token_costs (
    id          INTEGER PRIMARY KEY,
    at          INTEGER NOT NULL,       -- epoch ms
    provider    TEXT NOT NULL,          -- e.g. "groq", "nim"
    model       TEXT NOT NULL,          -- e.g. "openai/gpt-oss-120b"
    tokens_in   INTEGER NOT NULL,       -- input tokens
    tokens_out  INTEGER NOT NULL,       -- output tokens
    cost_usd    REAL,                   -- NULL if price unknown (phase doc — never 0.0)
    attempt     INTEGER NOT NULL DEFAULT 1,  -- attempt number
    success     INTEGER NOT NULL DEFAULT 1,  -- 1 = success, 0 = failure
    created_at  INTEGER NOT NULL        -- epoch ms
);
CREATE INDEX ix_token_costs_day ON token_costs(at);
CREATE INDEX ix_token_costs_provider ON token_costs(provider, model);
```

#### E.2.2 `provider_prices` (§8.2)

```sql
CREATE TABLE provider_prices (
    provider    TEXT NOT NULL,          -- e.g. "groq", "nim"
    model       TEXT NOT NULL,          -- e.g. "openai/gpt-oss-120b"
    price_in    REAL NOT NULL,          -- USD per 1M input tokens
    price_out   REAL NOT NULL,          -- USD per 1M output tokens
    PRIMARY KEY (provider, model)
);
```

**Seeding:** The `provider_prices` table is seeded with known prices at deployment time. Unknown models are simply absent from the table — their `cost_usd` is `None` (phase doc — never 0.0).

### E.3 `TokenCost` model

**Spec:** §5.2 — "Every attempt, failed or not, is written to the daily token-cost table."

**Decision:** A `TokenCost` dataclass is added to `chronos/contracts/`.

```python
# chronos/contracts/models.py (addition)
@dataclass(frozen=True)
class TokenCost:
    """
    A token cost record (§5.2, §8.2).

    Every provider attempt, failed or not, is recorded (§5.2).
    cost_usd is None if the price is unknown — never 0.0 (phase doc).
    """
    id: int | None              # None before persistence
    at: int                     -- epoch ms
    provider: str               -- provider name
    model: str                  -- model name
    tokens_in: int              -- input tokens
    tokens_out: int             -- output tokens
    cost_usd: float | None      -- USD cost; None if price unknown (phase doc)
    attempt: int = 1            -- attempt number
    success: bool = True        -- whether the attempt succeeded
    created_at: int | None      -- epoch ms; None before persistence
```

**Re-exported from:** `chronos/contracts/__init__.py`

### E.4 `ProviderPrice` model

**Spec:** §8.2 — "cost_usd comes from a real price table."

**Decision:** A `ProviderPrice` dataclass is added to `chronos/contracts/`.

```python
# chronos/contracts/models.py (addition)
@dataclass(frozen=True)
class ProviderPrice:
    """
    A provider model price (§8.2).

    Prices are USD per 1M tokens. Used to compute cost_usd.
    """
    provider: str       -- provider name
    model: str          -- model name
    price_in: float     -- USD per 1M input tokens
    price_out: float    -- USD per 1M output tokens
```

**Re-exported from:** `chronos/contracts/__init__.py`

### E.5 `StatsCollector`

**Spec:** §8.2 — "counts, streaks, token spend by day." §4.7 — "Audit retention is 7 days. Log retention is 7 days."

**File:** `chronos/ai/stats.py`

**Imports:** `chronos.contracts` (TokenCost, ProviderPrice, NodeRepo, EventRepo, TimerSessionRepo, AuditRepo, Clock)

```python
class StatsCollector:
    """
    Collects stats: counts, streaks, token spend by day (§8.2).

    cost_usd comes from a real price table (§8.2).
    Unknown price is None — never 0.0 (phase doc).
    Every provider attempt is recorded (§5.2).
    """

    def __init__(
        self,
        db: DbConnection,
        node_repo: NodeRepo,
        event_repo: EventRepo,
        timer_repo: TimerSessionRepo,
        audit_repo: AuditRepo,
        clock: Clock,
    ) -> None:
        """
        Args:
            db: database connection
            node_repo: node persistence
            event_repo: event persistence
            timer_repo: timer session persistence
            audit_repo: audit persistence
            clock: time source
        """

    def get_stats(self, days: int = 7) -> dict:
        """
        Get stats for the last N days (§8.2).

        Args:
            days: number of days to include (default 7, matching retention)

        Returns:
            {
                "period_days": int,
                "counts": {
                    "nodes_total": int,
                    "nodes_active": int,
                    "nodes_done": int,
                    "events_total": int,
                    "events_focus": int,
                    "events_review": int,
                    "timer_sessions": int,
                    "timer_sessions_completed": int,
                },
                "streaks": {
                    "current_streak_days": int,     -- consecutive days with activity
                    "longest_streak_days": int,     -- longest streak ever
                    "last_activity_date": str | None,  -- ISO-8601 date
                },
                "token_spend_by_day": [
                    {
                        "date": str,                -- ISO-8601 date
                        "tokens_in": int,
                        "tokens_out": int,
                        "cost_usd": float | None,   -- None if price unknown (phase doc)
                        "attempts": int,
                        "failures": int,
                    },
                    ...
                ],
                "audit_entries": int,               -- entries in retention window
                "retention_days": 7,                -- §4.7
            }
        """

    def record_token_cost(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        attempt: int = 1,
        success: bool = True,
    ) -> TokenCost:
        """
        Record a provider attempt (§5.2).

        Every attempt, failed or not, is recorded (§5.2).
        cost_usd is computed from the price table (§8.2).
        Unknown price → cost_usd = None (phase doc — never 0.0).

        Args:
            provider: provider name
            model: model name
            tokens_in: input tokens
            tokens_out: output tokens
            attempt: attempt number
            success: whether the attempt succeeded

        Returns:
            The recorded TokenCost with cost_usd computed.

        Behaviour:
            1. Look up (provider, model) in provider_prices.
            2. If found: cost_usd = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
            3. If not found: cost_usd = None (phase doc — never 0.0)
            4. Insert into token_costs table.
            5. Return the TokenCost.
        """

    def prune_audit(self) -> int:
        """
        Prune audit entries older than 7 days (§4.7).

        Returns:
            Number of entries pruned.
        """

    def prune_logs(self) -> int:
        """
        Prune log entries older than 7 days (§4.7).

        Returns:
            Number of entries pruned.
        """
```

### E.6 Retention

**Spec:** §4.7 — "Audit retention is 7 days. Log retention is 7 days."

**Decision:**
- Audit entries older than 7 days are excluded from the audit viewer (§F).
- Log entries older than 7 days are pruned.
- The `prune_audit()` and `prune_logs()` methods enforce this.
- The stats endpoint only includes data from the last 7 days by default.

### E.7 File layout: `chronos/ai/stats.py`

```
chronos/ai/stats.py  — StatsCollector, TokenCost re-export, ProviderPrice re-export
```

---

## F. Audit viewer (§4.7)

### F.1 Overview

**Spec:** §4.7 — "Audit retention is 7 days." Phase doc — "Browsable and filterable by action, by target and by time range. Read-only. Rows older than 7 days are excluded."

### F.2 `AuditFilter`

**Spec:** Phase doc — "filterable by action, by target and by time range."

**File:** `chronos/db/audit.py`

**Imports:** `chronos.contracts` (AuditEntry)

```python
@dataclass(frozen=True)
class AuditFilter:
    """
    Filter criteria for the audit viewer (§4.7, phase doc).

    All fields are optional. None means "no filter on this field".
    """
    action: str | None = None           # filter by action (§4.7)
    target: str | None = None          # filter by target (§4.7)
    from_ms: int | None = None         # time range start (§4.7)
    to_ms: int | None = None           # time range end (§4.7)
    limit: int = 100                   # max results (default 100)
    offset: int = 0                    # pagination offset
```

### F.3 `AuditViewer`

**Spec:** §4.7 — audit log. Phase doc — "Browsable, filterable, read-only, rows older than 7 days excluded."

**File:** `chronos/db/audit.py`

**Imports:** `chronos.contracts` (AuditEntry, AuditRepo, Clock)

```python
AUDIT_RETENTION_DAYS: int = 7   # §4.7 — 7 days


class AuditViewer:
    """
    Browsable, filterable, read-only audit viewer (§4.7, phase doc).

    Rows older than 7 days are excluded (§4.7, phase doc).
    Read-only — no write methods (phase doc).
    """

    def __init__(self, audit_repo: AuditRepo, clock: Clock) -> None:
        """
        Args:
            audit_repo: audit persistence
            clock: time source
        """

    def list_entries(self, filter: AuditFilter | None = None) -> list[AuditEntry]:
        """
        List audit entries matching the filter (§4.7, phase doc).

        Args:
            filter: filter criteria; None = no filter (but still excludes old rows)

        Returns:
            Up to `filter.limit` audit entries matching the filter,
            ordered by `at` descending (newest first).

        Behaviour:
            1. Compute retention cutoff: now_ms - 7 * 86400000 (§4.7).
            2. Exclude entries older than the cutoff (§4.7, phase doc).
            3. Apply action filter if set (phase doc).
            4. Apply target filter if set (phase doc).
            5. Apply time range filter if set (phase doc).
            6. Apply limit and offset.
            7. Return entries ordered by `at` descending.
        """

    def get_entry(self, entry_id: int) -> AuditEntry | None:
        """
        Get a single audit entry by id (§4.7).

        Args:
            entry_id: the audit entry id

        Returns:
            The AuditEntry if found and within retention, None otherwise.

        Note: entries older than 7 days return None (§4.7, phase doc).
        """

    def count_entries(self, filter: AuditFilter | None = None) -> int:
        """
        Count audit entries matching the filter (§4.7).

        Args:
            filter: filter criteria; None = no filter (but still excludes old rows)

        Returns:
            The number of matching entries within the retention window.
        """
```

### F.4 File layout: `chronos/db/audit.py`

```
chronos/db/audit.py  — AuditViewer, AuditFilter, AUDIT_RETENTION_DAYS
```

---

## G. CSV export

### G.1 Overview

**Spec:** §8.2 — "chronos export" CLI command. §9.2 — "chronos export" in CLI. Phase doc — "Events, timers, cost. A header row; one row per record. Values containing commas, quotes or newlines are quoted so the file opens cleanly in a spreadsheet. An unknown cost is an empty cell — not 0.0, not None."

### G.2 `CSVExporter`

**File:** `chronos/ai/export.py`

**Imports:** `chronos.contracts` (Event, TimerSession, TokenCost, EventRepo, TimerSessionRepo, Clock)

```python
class CSVExporter:
    """
    Exports events, timers, and cost to CSV (§8.2, §9.2).

    Header row; one row per record (phase doc).
    Values with commas/quotes/newlines are quoted (phase doc).
    Unknown cost is an empty cell — not 0.0, not None (phase doc).
    """

    def __init__(
        self,
        event_repo: EventRepo,
        timer_repo: TimerSessionRepo,
        db: DbConnection,
        clock: Clock,
    ) -> None:
        """
        Args:
            event_repo: event persistence
            timer_repo: timer session persistence
            db: database connection (for token_costs query)
            clock: time source
        """

    def export_events(self, start_ms: int, end_ms: int) -> str:
        """
        Export events to CSV (§8.2, §9.2).

        Args:
            start_ms: range start, epoch ms
            end_ms: range end, epoch ms

        Returns:
            CSV string with header row and one row per event.

        Columns:
            id, title, start_ms, end_ms, kind, node_id, bucket_id,
            series_id, review_index, derived_from, soft_deleted, created_at

        Timestamps are ISO-8601 with offset (§7.3).
        Values with commas/quotes/newlines are quoted (phase doc).
        """

    def export_timers(self, start_ms: int, end_ms: int) -> str:
        """
        Export timer sessions to CSV (§8.2, §9.2).

        Args:
            start_ms: range start, epoch ms
            end_ms: range end, epoch ms

        Returns:
            CSV string with header row and one row per timer session.

        Columns:
            id, node_id, label, started_at, ended_at, source,
            reconciled, mode, target_ms, phase, cycle

        Timestamps are ISO-8601 with offset (§7.3).
        Values with commas/quotes/newlines are quoted (phase doc).
        """

    def export_cost(self, start_ms: int, end_ms: int) -> str:
        """
        Export token costs to CSV (§8.2, §9.2).

        Args:
            start_ms: range start, epoch ms
            end_ms: range end, epoch ms

        Returns:
            CSV string with header row and one row per cost record.

        Columns:
            id, at, provider, model, tokens_in, tokens_out,
            cost_usd, attempt, success

        Timestamps are ISO-8601 with offset (§7.3).
        Values with commas/quotes/newlines are quoted (phase doc).
        Unknown cost is an empty cell — not 0.0, not None (phase doc).
        """
```

### G.3 CSV format rules

**Spec:** Phase doc — "A header row; one row per record. Values containing commas, quotes or newlines are quoted so the file opens cleanly in a spreadsheet. An unknown cost is an empty cell — not 0.0, not None."

**Decision:**
- Use Python's `csv` module with `csv.writer` and default quoting (`QUOTE_MINIMAL`).
- `QUOTE_MINIMAL` quotes values containing commas, quotes, or newlines — exactly what the spec requires.
- `None` values are written as empty strings (empty cell) — this is the default `csv` behaviour for `None`.
- Unknown `cost_usd` is `None` in the database → written as empty cell in CSV (phase doc — not 0.0, not None).
- Timestamps are converted to ISO-8601 with offset (§7.3) before writing.
- Booleans are written as `"1"` or `"0"` (matching the database convention).

### G.4 File layout: `chronos/ai/export.py`

```
chronos/ai/export.py  — CSVExporter
```

---

## H. File layout

Every file in Phase 5 with its purpose and exports. The import graph is a DAG with no cycles.

```
chronos/notify/
  __init__.py          — re-exports NtfyNotifier, ReminderScheduler
  ntfy.py              — NtfyNotifier (ntfy HTTP publisher, §10)
  scheduler.py         — ReminderScheduler (realtime tick, cancel, §4.6)

chronos/db/
  search.py            — NodeSearch, DbConnection, find_semantic_candidates (§4.8, §6)
  audit.py             — AuditViewer, AuditFilter, AUDIT_RETENTION_DAYS (§4.7)

chronos/ai/
  briefings.py         — BriefingGenerator, ClarificationBudget, Question re-export (§9.1, §5.7)
  stats.py             — StatsCollector, TokenCost re-export, ProviderPrice re-export (§8.2, §5.2)
  export.py            — CSVExporter (§8.2, §9.2)
```

### H.1 `chronos/notify/__init__.py`

**Purpose:** Re-exports from the notify submodules.

**Imports:** `ntfy`, `scheduler`

**Exports:** `NtfyNotifier`, `ReminderScheduler`

### H.2 `chronos/notify/ntfy.py`

**Purpose:** ntfy HTTP publisher (§10). One HTTP POST per publish.

**Imports:** `chronos.contracts` (Notifier, Reminder, Event, ReminderState)

**Exports:** `NtfyNotifier`

### H.3 `chronos/notify/scheduler.py`

**Purpose:** Reminder scheduler — fires due reminders on realtime tick, cancels individually (§4.6).

**Imports:** `chronos.contracts` (Reminder, ReminderState, Event, ReminderRepo, EventRepo, Notifier, Clock)

**Exports:** `ReminderScheduler`

### H.4 `chronos/db/search.py`

**Purpose:** Three-stage node search (FTS5 → sqlite-vec → model judge), dual Session/Connection support, semantic duplicate detection (§4.8, §6).

**Imports:** `chronos.contracts` (Node, SearchResult, SearchBackend, Embedder, Event, EventRepo)

**Exports:** `NodeSearch`, `DbConnection`, `find_semantic_candidates`, `DEFAULT_SEMANTIC_DUPLICATE_WINDOW_DAYS`, `MAX_SEMANTIC_DUPLICATE_WINDOW_DAYS`

### H.5 `chronos/db/audit.py`

**Purpose:** Browsable, filterable, read-only audit viewer (§4.7).

**Imports:** `chronos.contracts` (AuditEntry, AuditRepo, Clock)

**Exports:** `AuditViewer`, `AuditFilter`, `AUDIT_RETENTION_DAYS`

### H.6 `chronos/ai/briefings.py`

**Purpose:** Daily briefing generator, clarification budget, question queue (§9.1, §5.7).

**Imports:** `chronos.contracts` (Briefing, Node, Event, Question, NodeRepo, EventRepo, ReviewSeriesRepo, Clock)

**Exports:** `BriefingGenerator`, `ClarificationBudget`, `DEFAULT_CLARIFICATION_BUDGET_PER_DAY`

### H.7 `chronos/ai/stats.py`

**Purpose:** Stats collector — counts, streaks, token spend by day (§8.2, §5.2).

**Imports:** `chronos.contracts` (TokenCost, ProviderPrice, NodeRepo, EventRepo, TimerSessionRepo, AuditRepo, Clock)

**Exports:** `StatsCollector`

### H.8 `chronos/ai/export.py`

**Purpose:** CSV exporter — events, timers, cost (§8.2, §9.2).

**Imports:** `chronos.contracts` (Event, TimerSession, TokenCost, EventRepo, TimerSessionRepo, Clock)

**Exports:** `CSVExporter`

### H.9 Import graph (DAG)

```
chronos/contracts/  (frozen, Phase 1 + Phase 5 additions)
  ↑
chronos/notify/     (imports contracts)
chronos/db/search.py  (imports contracts)
chronos/db/audit.py   (imports contracts)
chronos/ai/briefings.py  (imports contracts)
chronos/ai/stats.py      (imports contracts)
chronos/ai/export.py     (imports contracts)
```

No cycles. All modules import only from `chronos/contracts/`.

### H.10 Contracts additions summary

The following are added to `chronos/contracts/` as part of this Phase 5 proposal:

| Addition | Location | Spec |
|---|---|---|
| `DEFAULT_REMINDER_OFFSETS_MIN` | `constants.py` | §4.6 |
| `DEFAULT_REUSE_SIMILARITY_THRESHOLD` | `constants.py` | §5.4 |
| `DEFAULT_CLARIFICATION_BUDGET_PER_DAY` | `constants.py` | §5.7 |
| `SearchResult` | `models.py` | §4.8 |
| `Briefing` | `models.py` | §9.1 |
| `Question` | `models.py` | §5.7 |
| `TokenCost` | `models.py` | §5.2 |
| `ProviderPrice` | `models.py` | §8.2 |
| `token_costs` table | `ddl.py` | §5.2 |
| `provider_prices` table | `ddl.py` | §8.2 |

All additions are re-exported from `chronos/contracts/__init__.py`.

---

## I. Spec ambiguities and open questions

1. **`DEFAULT_REUSE_SIMILARITY_THRESHOLD` value (§5.4):** The spec says "Above a similarity threshold the existing one is reused" but does not specify the threshold. **Proposal:** Default 0.85, configurable via Settings. Confirm with Manager.

2. **`check_conflict` return type change (§6, contracts C.14):** The frozen tool schema returns `semantic_candidates: array[Node]`. This proposal changes it to `array[SearchResult]` to carry scores. **Proposal:** Extend the return type. This is a breaking change to the tool schema. Confirm with Manager.

3. **Question storage (§5.7):** The spec does not specify where queued questions are stored. **Proposal:** Use the `audit` table with `action = "question"`. A dedicated `questions` table can be added later. Confirm with Manager.

4. **`provider_prices` seeding (§8.2):** The spec says "cost_usd comes from a real price table" but does not specify how prices are seeded or updated. **Proposal:** Seed at deployment time via a migration or setup script. Prices can be updated manually or via a settings interface. Confirm with Manager.

5. **Briefing "generated, not templated" (§9.1, phase doc):** The spec says briefings are generated, not templated, but does not specify the generation mechanism. **Proposal:** The `BriefingGenerator` queries the database and assembles the briefing from the results. The AI layer (Phase 2/3) may enhance the briefing with natural language, but the structure and content vary with the data. Confirm with Manager.

6. **`token_costs` table vs. daily token-cost table (§5.2):** The spec mentions a "daily token-cost table" but does not specify its schema. **Proposal:** The `token_costs` table records every attempt with a timestamp, and the stats endpoint aggregates by day. Confirm with Manager.

7. **Audit viewer pagination (§4.7):** The spec says "browsable" but does not specify pagination. **Proposal:** `AuditFilter` includes `limit` and `offset` for pagination. Default limit is 100. Confirm with Manager.

8. **CSV export timestamp format (§7.3):** The spec says ISO-8601 with offset at every API boundary. **Proposal:** All timestamps in CSV exports are ISO-8601 with offset in the instance timezone. Confirm with Manager.

9. **`NodeSearch` integration with `NodeRepo` (§4.8, phase doc):** The phase doc says "Index on create, re-index on update, remove on delete." The exact wiring between `NodeRepo` and `NodeSearch` is a Phase 1 implementation detail. **Proposal:** `NodeRepo` receives a `NodeSearch` instance and calls it after each write. The calls are best-effort. Confirm with Manager.

10. **`Briefing` dataclass vs. tool schema (§9.1, contracts C.26):** The frozen tool schema returns a dict, not a `Briefing` object. **Proposal:** The `Briefing` dataclass is used internally; the tool handler converts it to the dict format specified in C.26. The `considered_count` and `shown_count` fields are added to the dict. Confirm with Manager.
