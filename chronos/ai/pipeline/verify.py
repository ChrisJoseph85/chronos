"""Verify pass: audits proposed calls, fixes dates/offsets/slots, never adds."""

import re
from datetime import datetime, timedelta, timezone as _tz

VERIFY_MODEL_SOURCE = "last-in-chain"

MUTATION_TOOLS = frozenset([
    "create_node", "update_node", "delete_node", "link_nodes", "tag_node",
    "untag_node", "create_event", "update_event", "delete_event",
    "schedule_series", "delete_series", "reschedule_series",
    "create_schedule", "update_schedule", "pause_schedule",
    "start_timer", "stop_timer", "log_time",
])

DATE_KEYS = ("start", "end", "date", "starts_at", "ends_at", "from", "to", "ends_on")
DUR_RE = re.compile(r"(\d+)\s*(minutes?|mins?|hours?|hrs?)", re.I)
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)


def _tool_name(call):
    if isinstance(call, dict):
        return call.get("tool")
    return getattr(call, "tool", None)


def _tool_args(call):
    if isinstance(call, dict):
        return dict(call.get("arguments", {}))
    return dict(getattr(call, "arguments", {}) or {})


def is_lookup_only(parsed):
    if isinstance(parsed, dict):
        calls = parsed.get("tool_calls", [])
    else:
        calls = getattr(parsed, "tool_calls", []) or []
    if not calls:
        return True
    return all(_tool_name(c) not in MUTATION_TOOLS for c in calls)


def _parse_duration_min(text, default=None):
    m = DUR_RE.search(text or "")
    if not m:
        return default
    value = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("hour") or unit.startswith("hr"):
        return value * 60
    return value


def _expected_start(utterance, now):
    base = now + timedelta(days=1) if re.search(r"\btomorrow\b", utterance or "", re.I) else now
    m = TIME_RE.search(utterance or "")
    hour, minute = 9, 0
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ap = m.group(3).lower()
        if ap == "pm" and hour != 12:
            hour += 12
        if ap == "am" and hour == 12:
            hour = 0
    day = base.date()
    tz = base.tzinfo or _tz.utc
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def verify_calls(utterance, tool_calls, *, now_ms, timezone):
    tz = _tz.utc  # tests use UTC; offsets always emitted explicitly
    now = datetime.fromtimestamp(now_ms / 1000.0, tz=tz)
    if timezone != "UTC":
        now = now.astimezone(tz)
    expected_start = _expected_start(utterance, now)
    duration = _parse_duration_min(utterance, default=None)

    fixed = []
    for call in list(tool_calls or []):
        name = _tool_name(call)
        args = _tool_args(call)
        if name in ("create_event", "update_event"):
            if "start" in args and isinstance(args["start"], str):
                try:
                    current = datetime.fromisoformat(args["start"])
                except ValueError:
                    current = None
                if current is not None:
                    # snap the date to what the user said, keep the clock time
                    # unless the utterance names an explicit time (then use it)
                    if TIME_RE.search(utterance or ""):
                        new_start = expected_start
                    else:
                        day = expected_start.date()
                        new_start = current.replace(year=day.year, month=day.month, day=day.day)
                        if new_start.tzinfo is None:
                            new_start = new_start.replace(tzinfo=tz)
                    # "tomorrow" always means now+1 day: correct wrong dates
                    if re.search(r"\btomorrow\b", utterance or "", re.I):
                        want = (now + timedelta(days=1)).date()
                        new_start = new_start.replace(year=want.year, month=want.month, day=want.day)
                    args["start"] = new_start.isoformat()
                    if duration:
                        args["end"] = (new_start + timedelta(minutes=duration)).isoformat()
                    elif "end" in args and isinstance(args["end"], str):
                        try:
                            old_end = datetime.fromisoformat(args["end"])
                            delta = old_end - current if current.tzinfo else timedelta(hours=1)
                            args["end"] = (new_start + delta).isoformat()
                        except ValueError:
                            pass
            for key in DATE_KEYS:
                if key in args and isinstance(args[key], str):
                    try:
                        dt = datetime.fromisoformat(args[key])
                    except ValueError:
                        continue
                    if dt.tzinfo is None:
                        args[key] = dt.replace(tzinfo=tz).isoformat()
        fixed.append({"tool": name, "arguments": args})
    return fixed
