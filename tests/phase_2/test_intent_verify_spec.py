"""Phase 2 intent + verify spec tests — Chronos.md §5.3, §5.5 + decisions (Phase 2: 6, 7).

Spec-only contract. Implementation surface pinned here:

  chronos.ai.pipeline.intent.parse_intent(text, *, now_ms, timezone)
      -> {"intent": str, "tool_calls": [{"tool": str, "arguments": {...}}]}
  chronos.ai.pipeline.verify.verify_calls(utterance, tool_calls, *, now_ms, timezone)
      -> corrected list (same shape); fixes dates/offsets/slots, never adds calls
  chronos.ai.pipeline.verify.is_lookup_only(parsed) -> bool
      True iff no mutation tool call is present (decision ruling 6).
      Mutation tools: create_node update_node delete_node link_nodes tag_node
      untag_node create_event update_event delete_event schedule_series
      delete_series reschedule_series create_schedule update_schedule pause_schedule
      start_timer stop_timer log_time
  chronos.ai.pipeline.intent.run_turn(text, *, now_ms, timezone)
      -> {"intent", "tool_calls", "proposal_id", "committed", "events",
          "message", "questions", "second_turn"}
      Ambiguous input: committed False, proposal_id set, len(questions) <= 1.
      Lookup-only turn: second_turn is a non-empty list of tool calls.
  Verify model selection (ruling 7): chronos.ai.pipeline.verify.VERIFY_MODEL_SOURCE
      == "last-in-chain".

now_ms is UTC epoch milliseconds. Timezone is an IANA name; tests use "UTC".
No network: parsing/verifying is local in tests (stub model data inline).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import socket
import urllib.request
from datetime import datetime, timezone

import pytest

SPEC_INTENT = "docs/server/Chronos.md §5.3"
SPEC_TOOLS = "docs/server/Chronos.md §5.5"

NOW_MS = 1785288000000  # 2026-08-04T12:00:00Z
TZ = "UTC"

MUTATION_TOOLS = frozenset([
    "create_node", "update_node", "delete_node", "link_nodes", "tag_node",
    "untag_node", "create_event", "update_event", "delete_event",
    "schedule_series", "delete_series", "reschedule_series",
    "create_schedule", "update_schedule", "pause_schedule",
    "start_timer", "stop_timer", "log_time",
])

DATE_KEYS = {"start", "end", "date", "starts_at", "ends_at", "from", "to", "ends_on"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network blocked in phase-2 tests: inject fakes (%s)" % SPEC_INTENT)

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


# ---------------------------------------------------------------- helpers

def _load_intent():
    try:
        from chronos.ai.pipeline import intent as m
        return m
    except Exception as exc:
        pytest.fail("%s: missing chronos.ai.pipeline.intent (%s)" % (SPEC_INTENT, exc))


def _load_verify():
    try:
        from chronos.ai.pipeline import verify as m
        return m
    except Exception as exc:
        pytest.fail("%s: missing chronos.ai.pipeline.verify (%s)" % (SPEC_INTENT, exc))


def _calls(parsed):
    if isinstance(parsed, dict):
        calls = parsed.get("tool_calls")
    else:
        calls = getattr(parsed, "tool_calls", None)
    assert isinstance(calls, list), "%s: parsed turn must carry a tool_calls list" % SPEC_INTENT
    return calls


def _tool(call):
    if isinstance(call, dict):
        return call.get("tool"), call.get("arguments", {})
    return getattr(call, "tool", None), getattr(call, "arguments", {})


def _assert_absolute_iso(value, spec):
    assert isinstance(value, str), "%s: date argument must be str, got %.20r" % (spec, value)
    assert value != "day 8", "%s: bare 'day 8' is forbidden" % spec
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, "%s: ISO date must carry an offset: %r" % (spec, value)


# ---------------------------------------------------------------- tests

def test_parse_emits_absolute_iso_dates():
    """§5.5: dates in tool arguments are absolute ISO-8601 in the instance timezone."""
    intent = _load_intent()
    parsed = intent.parse_intent("Schedule math review tomorrow at 4pm for 45 minutes", now_ms=NOW_MS, timezone=TZ)
    calls = _calls(parsed)
    assert len(calls) >= 1, "%s: expected at least one tool call" % SPEC_TOOLS
    seen_date = 0
    for call in calls:
        _, args = _tool(call)
        for key in DATE_KEYS.intersection(set(args.keys())):
            _assert_absolute_iso(args[key], SPEC_TOOLS)
            seen_date += 1
    assert seen_date >= 1, "%s: expected at least one absolute date argument" % SPEC_TOOLS


def test_bare_day_never_emitted():
    """§5.5: the model never emits a bare 'day 8'."""
    intent = _load_intent()
    parsed = intent.parse_intent("Remind me on day 8 at 9am", now_ms=NOW_MS, timezone=TZ)
    for call in _calls(parsed):
        _, args = _tool(call)
        for key in DATE_KEYS.intersection(set(args.keys())):
            _assert_absolute_iso(args[key], SPEC_TOOLS)


def test_uncomputable_pattern_calls_ask_question_or_lists_explicit_dates():
    """§5.5: a pattern that fits no computable rule → ask_question or explicit dates."""
    intent = _load_intent()
    parsed = intent.parse_intent("Remind me every second Tuesday when it rains", now_ms=NOW_MS, timezone=TZ)
    calls = _calls(parsed)
    assert len(calls) >= 1, "%s: uncomputable input must still produce a call" % SPEC_TOOLS
    first_tool, first_args = _tool(calls[0])
    if first_tool == "ask_question":
        assert isinstance(first_args, dict), "%s: ask_question needs arguments" % SPEC_TOOLS
    else:
        for call in calls:
            _, args = _tool(call)
            for key in DATE_KEYS.intersection(set(args.keys())):
                _assert_absolute_iso(args[key], SPEC_TOOLS)
        date_count = 0
        for call in calls:
            _, args = _tool(call)
            date_count += len(DATE_KEYS.intersection(set(args.keys())))
        assert date_count >= 1, "%s: without ask_question, explicit dates are required" % SPEC_TOOLS


def test_verify_pass_corrects_dates_offsets_slots():
    """§5.3: verify audits calls against the user's words; corrects dates/offsets/slots."""
    verify = _load_verify()
    utterance = "Schedule math review tomorrow at 4pm for 45 minutes"
    proposed = [{"tool": "create_event", "arguments": {
        "title": "math review",
        "start": "2026-08-06T16:00:00+00:00",
        "end": "2026-08-06T17:00:00+00:00",
    }}]
    fixed = verify.verify_calls(utterance, proposed, now_ms=NOW_MS, timezone=TZ)
    assert isinstance(fixed, list), "%s: verify must return a list" % SPEC_INTENT
    assert len(fixed) == 1, "%s: verify must not drop or add calls here" % SPEC_INTENT
    _, args = _tool(fixed[0])
    assert args["start"] == "2026-08-05T16:00:00+00:00", \
        "%s: wrong date must be corrected, got %r" % (SPEC_INTENT, args.get("start"))
    assert args["end"] == "2026-08-05T16:45:00+00:00", \
        "%s: slot must match 45 minutes, got %r" % (SPEC_INTENT, args.get("end"))


def test_verify_never_invents_unasked_calls():
    """§5.3: verify never invents a call the user did not ask for."""
    verify = _load_verify()
    utterance = "Delete the dentist appointment tomorrow"
    proposed = [{"tool": "delete_event", "arguments": {"title": "dentist"}}]
    fixed = verify.verify_calls(utterance, proposed, now_ms=NOW_MS, timezone=TZ)
    out_tools = set()
    for call in fixed:
        name, _ = _tool(call)
        out_tools.add(name)
    assert out_tools <= {"delete_event"}, \
        "%s: verify invented calls: %r" % (SPEC_INTENT, sorted(out_tools))
    assert len(fixed) <= len(proposed), "%s: verify must not add calls" % SPEC_INTENT


def test_lookup_only_turn_triggers_second_turn_no_silent_noop():
    """§5.3: a lookup-only turn gets a second turn (no silent no-op)."""
    intent = _load_intent()
    verify = _load_verify()
    parsed = intent.parse_intent("Am I free tomorrow evening?", now_ms=NOW_MS, timezone=TZ)
    assert verify.is_lookup_only(parsed) is True, \
        "%s: question with no mutation calls is lookup-only" % SPEC_INTENT
    turn = intent.run_turn("Am I free tomorrow evening?", now_ms=NOW_MS, timezone=TZ)
    assert turn["committed"] is False, "%s: lookup turn must not commit" % SPEC_INTENT
    second = turn["second_turn"]
    assert isinstance(second, list), "%s: lookup-only turn needs a second turn" % SPEC_INTENT
    assert len(second) >= 1, "%s: second turn must act, not no-op" % SPEC_INTENT


def test_ambiguous_input_proposes_with_at_most_one_question_never_silent_commit():
    """API.md + §5.5: ambiguous input → proposal + at most one question, never a silent commit."""
    intent = _load_intent()
    turn = intent.run_turn("Schedule it soon", now_ms=NOW_MS, timezone=TZ)
    assert turn["committed"] is False, "%s: ambiguous input must never silently commit" % SPEC_TOOLS
    assert turn["proposal_id"] is not None, "%s: ambiguous input needs a proposal" % SPEC_TOOLS
    assert isinstance(turn["questions"], list), "%s: turn must carry a questions list" % SPEC_TOOLS
    assert len(turn["questions"]) <= 1, \
        "%s: at most one question, got %r" % (SPEC_TOOLS, len(turn["questions"]))


def test_verify_uses_cheapest_last_in_chain_model():
    """Decisions Phase 2 ruling 7: verify runs on the last adapter in the chain."""
    verify = _load_verify()
    assert getattr(verify, "VERIFY_MODEL_SOURCE", None) == "last-in-chain", \
        "%s: VERIFY_MODEL_SOURCE must be 'last-in-chain'" % SPEC_INTENT
