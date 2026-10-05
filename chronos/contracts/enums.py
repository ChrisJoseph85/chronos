"""Frozen shared surface (Chronos.md §2.1). Stdlib only."""

from __future__ import annotations

import enum


class NodeKind(str, enum.Enum):
    project = "project"
    task = "task"
    subtask = "subtask"


class NodeStatus(str, enum.Enum):
    active = "active"
    done = "done"
    archived = "archived"


class EventKind(str, enum.Enum):
    focus = "focus"
    class_ = "class"
    break_ = "break"
    review = "review"
    admin = "admin"


class SeriesState(str, enum.Enum):
    active = "active"
    retired = "retired"
    cancelled = "cancelled"


class TimerMode(str, enum.Enum):
    stopwatch = "stopwatch"
    timer = "timer"
    pomodoro = "pomodoro"


class TimerPhase(str, enum.Enum):
    focus = "focus"
    break_ = "break"


class ReminderState(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    cancelled = "cancelled"


class BucketLevel(str, enum.Enum):
    Y = "Y"
    M = "M"
    W = "W"
    D = "D"


class ReviewTier(str, enum.Enum):
    hard = "hard"
    medium = "medium"
    easy = "easy"
    custom = "custom"
