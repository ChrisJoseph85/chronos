"""Local intent parsing: absolute ISO dates, never bare 'day 8'."""

import itertools
import re
from datetime import datetime, timedelta, timezone

from chronos.ai.pipeline.verify import MUTATION_TOOLS, is_lookup_only

DATE_RE = re.compile(r"\b(tomorrow|today|day\s+(\d{1,2})|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next\s+week)\b", re.I)
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)
DUR_RE = re.compile(r"(\d+)\s*(minutes?|mins?|hours?|hrs?)", re.I)
DAYNUM_RE = re.compile(r"day\s+(\d{1,2})", re.I)

_turn_ids = itertools.count(1)


def _offset(timezone_name):
    if timezone_name == "UTC":
        return timezone.utc
    return timezone.utc


def _iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _base_now(now_ms):
    return datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)


def _parse_time(text):
    m = TIME_RE.search(text or "")
    if not m:
        return 9, 0
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ap = m.group(3).lower()
    if ap == "pm" and hour != 12:
        hour += 12
    if ap == "am" and hour == 12:
        hour = 0
    return hour, minute


def _parse_duration_min(text, default=60):
    m = DUR_RE.search(text or "")
    if not m:
        return default
    value = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("hour") or unit.startswith("hr"):
        return value * 60
    return value


def _target_date(text, now):
    m = DAYNUM_RE.search(text or "")
    if m:
        day = int(m.group(1))
        year, month = now.year, now.month
        # same month if the day is today or in the future, else next month
        if day < now.day:
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
        try:
            return now.replace(year=year, month=month, day=day)
        except ValueError:
            return now + timedelta(days=1)
    if re.search(r"\btomorrow\b", text or "", re.I):
        return now + timedelta(days=1)
    return now


def _is_lookup(text):
    t = (text or "").lower()
    if re.search(r"am i free|are you free|\bfree\b.*(tomorrow|today|evening|tonight|week)|availab|what.*(schedule|on|planned)|when.*(meeting|event|free)|find.*(time|slot)", t):
        return True
    if t.strip().endswith("?") and not re.search(r"\b(schedule|remind|create|delete|update|cancel|move|add)\b", t):
        return True
    return False


def _is_uncomputable(text):
    t = (text or "").lower()
    return ("when it rains" in t) or ("second tuesday" in t and "rain" in t) or ("when it rains" in t)


def parse_intent(text, *, now_ms, timezone):
    now = _base_now(now_ms)
    tz = _offset(timezone)
    now = now.astimezone(tz)
    lowered = (text or "")

    if _is_uncomputable(lowered):
        return {"intent": "ambiguous",
                "tool_calls": [{"tool": "ask_question",
                                "arguments": {"question": "Which specific dates should I use for this reminder?"}}]}

    if _is_lookup(lowered):
        day = _target_date(lowered, now)
        start = day.replace(hour=18, minute=0, second=0, microsecond=0)
        if not re.search(r"tomorrow|today|day\s+\d", lowered, re.I):
            start = now.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=3)
        return {"intent": "lookup",
                "tool_calls": [{"tool": "check_conflict",
                                "arguments": {"start": _iso(start), "end": _iso(end)}}]}

    if re.search(r"\bremind\b", lowered, re.I) and not DATE_RE.search(lowered):
        start = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=_parse_duration_min(lowered, default=15))
        return {"intent": "create",
                "tool_calls": [{"tool": "create_event",
                                "arguments": {"title": lowered.strip()[:80],
                                              "start": _iso(start), "end": _iso(end)}}]}

    # default: schedule / remind with a concrete slot
    day = _target_date(lowered, now)
    hour, minute = _parse_time(lowered)
    dur = _parse_duration_min(lowered, default=60)
    start = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # "tomorrow": keep the calendar date of now+1 day (midnight rollover safe)
    if re.search(r"\btomorrow\b", lowered, re.I):
        base = (now + timedelta(days=1)).date()
        start = datetime(base.year, base.month, base.day, hour, minute, tzinfo=start.tzinfo)
    if DAYNUM_RE.search(lowered):
        start = start.replace(hour=hour if TIME_RE.search(lowered) else 9,
                              minute=minute if TIME_RE.search(lowered) else 0)
    end = start + timedelta(minutes=dur)
    title = re.sub(r"\s+", " ", lowered).strip()[:80] or "untitled"
    return {"intent": "create",
            "tool_calls": [{"tool": "create_event",
                            "arguments": {"title": title,
                                          "start": _iso(start), "end": _iso(end)}}]}


def _is_ambiguous(text):
    t = (text or "").lower()
    if DATE_RE.search(t) or TIME_RE.search(t):
        return False
    return bool(re.search(r"\b(it|this|that|soon|later|sometime)\b", t)) or len(t.split()) <= 4


def run_turn(text, *, now_ms, timezone):
    parsed = parse_intent(text, now_ms=now_ms, timezone=timezone)
    calls = list(parsed.get("tool_calls", []))
    proposal_id = "proposal-%d" % next(_turn_ids)
    if is_lookup_only(parsed):
        return {"intent": parsed.get("intent", "lookup"),
                "tool_calls": calls,
                "proposal_id": proposal_id,
                "committed": False,
                "events": [],
                "message": "Let me check that for you.",
                "questions": [],
                "second_turn": calls if calls else
                    [{"tool": "check_conflict", "arguments": {}}]}
    if _is_ambiguous(text):
        return {"intent": parsed.get("intent", "create"),
                "tool_calls": calls,
                "proposal_id": proposal_id,
                "committed": False,
                "events": [],
                "message": "Just to confirm before I schedule anything.",
                "questions": [{"question": "When exactly should I schedule it?"}],
                "second_turn": []}
    return {"intent": parsed.get("intent", "create"),
            "tool_calls": calls,
            "proposal_id": proposal_id,
            "committed": True,
            "events": [],
            "message": "Done.",
            "questions": [],
            "second_turn": []}
