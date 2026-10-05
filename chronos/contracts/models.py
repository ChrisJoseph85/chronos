"""§4 entity models. Stdlib only."""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from chronos.contracts.enums import (
    BucketLevel,
    EventKind,
    NodeKind,
    NodeStatus,
    ReminderState,
    ReviewTier,
    SeriesState,
    TimerMode,
    TimerPhase,
)


@dataclasses.dataclass
class Node:
    id: str
    parent_id: Optional[str]
    kind: Any
    title: str
    notes: Optional[str]
    status: Any
    created_at: int
    updated_at: int
    done_at: Optional[int] = None


@dataclasses.dataclass
class Tag:
    id: str
    name: str
    color: Optional[str] = None


@dataclasses.dataclass
class NodeTag:
    node_id: str
    tag_id: str


@dataclasses.dataclass
class Event:
    id: str
    node_id: Optional[str]
    title: str
    start_ms: int
    end_ms: int
    kind: Any
    bucket_id: Optional[str] = None
    series_id: Optional[str] = None
    review_index: Optional[int] = None
    derived_from: Optional[str] = None
    soft_deleted: int = 0
    created_at: int = 0


@dataclasses.dataclass
class Bucket:
    id: str
    level: Any
    parent_id: Optional[str]
    start_ms: int
    end_ms: int
    seq: int


@dataclasses.dataclass
class ReviewSeries:
    id: str
    node_id: str
    tier: Any
    offsets_days: Any
    anchor_node_id: str
    max_count: Optional[int] = None
    ends_on_ms: Optional[int] = None
    state: Any = "active"
    created_at: int = 0


@dataclasses.dataclass
class Schedule:
    id: str
    title: str
    starts_ms: int
    ends_at_ms: int
    start_minute: int
    duration_min: int
    weekdays: Any
    hard_block: int = 1
    paused: int = 0
    created_at: int = 0


@dataclasses.dataclass
class Reminder:
    id: str
    event_id: str
    fire_at_ms: int
    offset_min: int
    state: Any = "pending"
    channel: str = "ntfy"
    created_at: int = 0


@dataclasses.dataclass
class TimerSession:
    id: str
    node_id: Optional[str]
    label: str
    started_at: int
    ended_at: Optional[int] = None
    source: str = ""
    reconciled: int = 0
    mode: Any = "stopwatch"
    target_ms: Optional[int] = None
    phase: Optional[Any] = None
    cycle: int = 1


@dataclasses.dataclass
class AuditEntry:
    id: Optional[int]
    at: int
    device_id: Optional[str]
    action: str
    target: Optional[str] = None
    context: Optional[str] = None
    cost_usd: Optional[float] = None
