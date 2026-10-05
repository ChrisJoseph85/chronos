"""Pure scheduling logic (Chronos.md §6, §7). No DB imports."""

from __future__ import annotations

from typing import Any

MIN_MS = 60_000
DAY_MS = 86_400_000

TIER_OFFSETS: dict[str, list[int]] = {
    "hard": [1, 2, 4, 8, 16],
    "medium": [3, 7, 15, 30],
    "easy": [10, 30, 90],
}

__all__ = [
    "MIN_MS", "DAY_MS", "TIER_OFFSETS",
    "snap_to_minute", "snap_to_grid", "snap_ms",
    "validate_duration", "check_duration", "ensure_positive_duration",
    "validate_duration_ms", "validate_slot",
    "resolve_overlap", "find_first_free_slot", "push_to_free_minute",
    "first_free_minute", "resolve_conflict",
    "is_schedule_blocking", "schedule_blocks", "is_blocking",
    "tier_offsets", "offsets_for_tier", "default_offsets",
    "build_series_events", "plan_series", "expand_series", "series_events",
    "local_to_utc_ms", "wall_to_utc_ms", "to_utc_ms", "local_to_utc", "wall_to_utc",
    "utc_to_local_iso", "to_local_iso", "utc_to_wall", "utc_to_local", "render_local",
    "counts_toward_total", "counts_for_totals", "include_in_totals", "is_work_time",
    "is_cycle_complete", "is_completed_cycle", "cycle_complete", "focus_completed",
]


def _ceil_minute(ms: int) -> int:
    return ((ms + MIN_MS - 1) // MIN_MS) * MIN_MS


def snap_to_minute(ms: int) -> int:
    return _ceil_minute(int(ms))


def snap_to_grid(ms: int) -> int:
    return snap_to_minute(ms)


def snap_ms(ms: int) -> int:
    return snap_to_minute(ms)


def _norm_long(value: int, name: str) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("bad %s: %r" % (name, value)) from exc
    return iv


def validate_duration(start_ms: int, end_ms: int) -> None:
    if _norm_long(end_ms, "end_ms") <= _norm_long(start_ms, "start_ms"):
        raise ValueError("negative or zero duration rejected")


def check_duration(start_ms: int, end_ms: int) -> None:
    validate_duration(start_ms, end_ms)


def ensure_positive_duration(start_ms: int, end_ms: int) -> None:
    validate_duration(start_ms, end_ms)


def validate_duration_ms(start_ms: int, end_ms: int) -> None:
    validate_duration(start_ms, end_ms)


def validate_slot(start_ms: int, end_ms: int) -> None:
    validate_duration(start_ms, end_ms)


def _busy_pairs(busy: Any) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for item in busy or []:
        if isinstance(item, dict):
            s = item.get("start_ms", item.get("start"))
            e = item.get("end_ms", item.get("end"))
        elif isinstance(item, (list, tuple)):
            s, e = item[0], item[1]
        else:
            s = getattr(item, "start_ms", getattr(item, "start", None))
            e = getattr(item, "end_ms", getattr(item, "end", None))
        pairs.append((int(s), int(e)))
    return sorted(pairs)


def resolve_overlap(req_start: int, req_end: int, busy: Any = None) -> dict:
    rs = _ceil_minute(_norm_long(req_start, "req_start"))
    re_ = _ceil_minute(_norm_long(req_end, "req_end"))
    validate_duration(rs, re_)
    duration = re_ - rs
    candidate = rs
    for bstart, bend in _busy_pairs(busy):
        bstart = _ceil_minute(bstart)
        bend = _ceil_minute(bend)
        # Half-open [from, to): free iff candidate+duration <= bstart or candidate >= bend.
        if candidate + duration <= bstart:
            break
        if candidate < bend and candidate + duration > bstart:
            candidate = bend
    actual_end = candidate + duration
    return {
        "requested_start_ms": rs,
        "requested_end_ms": re_,
        "actual_start_ms": candidate,
        "actual_end_ms": actual_end,
    }


def find_first_free_slot(req_start: int, req_end: int, busy: Any = None) -> dict:
    return resolve_overlap(req_start, req_end, busy)


def push_to_free_minute(req_start: int, req_end: int, busy: Any = None) -> dict:
    return resolve_overlap(req_start, req_end, busy)


def first_free_minute(req_start: int, req_end: int, busy: Any = None) -> dict:
    return resolve_overlap(req_start, req_end, busy)


def resolve_conflict(req_start: int, req_end: int, busy: Any = None) -> dict:
    return resolve_overlap(req_start, req_end, busy)


def _flag(mapping: Any, *names: str) -> int:
    if isinstance(mapping, dict):
        for name in names:
            if name in mapping:
                return int(mapping[name])
        return 0
    for name in names:
        if hasattr(mapping, name):
            return int(getattr(mapping, name))
    return 0


def is_schedule_blocking(schedule: Any) -> bool:
    return bool(_flag(schedule, "hard_block")) and not bool(_flag(schedule, "paused"))


def schedule_blocks(schedule: Any) -> bool:
    return is_schedule_blocking(schedule)


def is_blocking(schedule: Any) -> bool:
    return is_schedule_blocking(schedule)


def tier_offsets(tier: str) -> list[int]:
    key = getattr(tier, "value", tier)
    if key not in TIER_OFFSETS:
        raise ValueError("unknown tier: %r" % (tier,))
    return list(TIER_OFFSETS[key])


def offsets_for_tier(tier: str) -> list[int]:
    return tier_offsets(tier)


def default_offsets(tier: str) -> list[int]:
    return tier_offsets(tier)


def _series_list(tier: Any, anchor: str, series: str, anchor_ms: int) -> list[dict]:
    key = getattr(tier, "value", tier)
    offsets = list(TIER_OFFSETS.get(key, []))
    out = []
    for index, off in enumerate(offsets, start=1):
        out.append({
            "series_id": series,
            "review_index": index,
            "derived_from": anchor,
            "anchor_node_id": anchor,
            "tier": key,
            "start_ms": int(anchor_ms) + off * DAY_MS,
            "offset_days": off,
        })
    return out


def build_series_events(tier: Any = "hard", anchor: str = "", series: str = "",
                        anchor_ms: int = 0, *args: Any, **kwargs: Any) -> list[dict]:
    if isinstance(tier, dict):
        mapping = tier
        t = mapping.get("tier", "hard")
        a = mapping.get("anchor_node_id", mapping.get("anchor", mapping.get("derived_from", "")))
        s = mapping.get("series_id", mapping.get("series", ""))
        ms = mapping.get("anchor_ms", mapping.get("anchor_ms_", mapping.get("start_ms", 0)))
        return _series_list(t, a, s, ms)
    return _series_list(tier, anchor, series, anchor_ms)


def plan_series(tier: Any = "hard", anchor: str = "", series: str = "",
                anchor_ms: int = 0, *args: Any, **kwargs: Any) -> list[dict]:
    return build_series_events(tier, anchor, series, anchor_ms, *args, **kwargs)


def expand_series(tier: Any = "hard", anchor: str = "", series: str = "",
                  anchor_ms: int = 0, *args: Any, **kwargs: Any) -> list[dict]:
    return build_series_events(tier, anchor, series, anchor_ms, *args, **kwargs)


def series_events(tier: Any = "hard", anchor: str = "", series: str = "",
                  anchor_ms: int = 0, *args: Any, **kwargs: Any) -> list[dict]:
    return build_series_events(tier, anchor, series, anchor_ms, *args, **kwargs)


def _zoneinfo(name: str):  # stdlib only
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)


def local_to_utc_ms(wall: str, zone: str) -> int:
    import datetime as _dt

    naive = _dt.datetime.fromisoformat(wall)
    if naive.tzinfo is not None:
        naive = naive.replace(tzinfo=None)
    aware = naive.replace(tzinfo=_zoneinfo(zone))
    return int(aware.timestamp() * 1000)


def wall_to_utc_ms(wall: str, zone: str) -> int:
    return local_to_utc_ms(wall, zone)


def to_utc_ms(wall: str, zone: str) -> int:
    return local_to_utc_ms(wall, zone)


def local_to_utc(wall: str, zone: str) -> int:
    return local_to_utc_ms(wall, zone)


def wall_to_utc(wall: str, zone: str) -> int:
    return local_to_utc_ms(wall, zone)


def utc_to_local_iso(utc_ms: int, zone: str) -> str:
    import datetime as _dt

    aware = _dt.datetime.fromtimestamp(int(utc_ms) / 1000, tz=_dt.timezone.utc)
    local = aware.astimezone(_zoneinfo(zone))
    return local.replace(tzinfo=None).isoformat()


def to_local_iso(utc_ms: int, zone: str) -> str:
    return utc_to_local_iso(utc_ms, zone)


def utc_to_wall(utc_ms: int, zone: str) -> str:
    return utc_to_local_iso(utc_ms, zone)


def utc_to_local(utc_ms: int, zone: str) -> str:
    return utc_to_local_iso(utc_ms, zone)


def render_local(utc_ms: int, zone: str) -> str:
    return utc_to_local_iso(utc_ms, zone)


def _mode_phase(mode: Any, phase: Any) -> tuple[str, Any]:
    m = getattr(mode, "value", mode)
    p = getattr(phase, "value", phase) if phase is not None else None
    return (str(m).lower() if m is not None else "", p.lower() if isinstance(p, str) else p)


def counts_toward_total(mode: Any, phase: Any = None) -> bool:
    m, p = _mode_phase(mode, phase)
    if m == "pomodoro":
        return p != "break"
    return True


def counts_for_totals(mode: Any, phase: Any = None) -> bool:
    return counts_toward_total(mode, phase)


def include_in_totals(mode: Any, phase: Any = None) -> bool:
    return counts_toward_total(mode, phase)


def is_work_time(mode: Any, phase: Any = None) -> bool:
    return counts_toward_total(mode, phase)


def is_cycle_complete(mode: Any, phase: Any = None, elapsed_ms: int = 0,
                      target_ms: int | None = None, **kwargs: Any) -> bool:
    if "elapsed" in kwargs and elapsed_ms == 0:
        elapsed_ms = kwargs["elapsed"]
    if "target" in kwargs and target_ms is None:
        target_ms = kwargs["target"]
    if target_ms is None:
        return False
    return int(elapsed_ms) >= int(target_ms)


def is_completed_cycle(mode: Any, phase: Any = None, elapsed_ms: int = 0,
                       target_ms: int | None = None, **kwargs: Any) -> bool:
    return is_cycle_complete(mode, phase, elapsed_ms, target_ms, **kwargs)


def cycle_complete(mode: Any, phase: Any = None, elapsed_ms: int = 0,
                   target_ms: int | None = None, **kwargs: Any) -> bool:
    return is_cycle_complete(mode, phase, elapsed_ms, target_ms, **kwargs)


def focus_completed(mode: Any, phase: Any = None, elapsed_ms: int = 0,
                    target_ms: int | None = None, **kwargs: Any) -> bool:
    return is_cycle_complete(mode, phase, elapsed_ms, target_ms, **kwargs)
