"""Phase 2 tool-dispatcher spec tests — Chronos.md §5.5 + API.md MCP list.

Spec-only contract. Implementation surface pinned here:

  chronos.ai.pipeline.tools.TOOL_SCHEMAS: dict[str, dict] (exactly 27 entries)
  chronos.ai.pipeline.tools.ToolDispatcher
      __init__(store)  # store methods are named after the tools they serve:
          create_node/update_node/delete_node/link_nodes/tag_node/untag_node,
          create_event/update_event/delete_event (+ list_events(from_ms, to_ms),
          list_schedules()), schedule_series/delete_series/reschedule_series,
          search_nodes, check_conflict, find_free_slots, get_free_time,
          create_schedule/update_schedule/pause_schedule,
          start_timer/stop_timer/log_time, get_day/get_week/get_month/get_briefing,
          ask_question, get_node_kind(node_id) -> "project"|"task"|"subtask".
          Each returns a plain dict; dispatcher wraps it into a result dict.
      .dispatch(tool, arguments) -> {"success": bool, ...}
          success True on happy path; False (or a raised ValueError) on refusal.
          Never returns success True for an unimplemented/unknown tool.
          create_event resolves hard blocks + overlaps in code and reports both
          requested_start_ms and start_ms (actual).
          schedule_series creates the whole series in ONE store call and refuses
          unbounded series (neither max_count nor ends_on_ms).
          tag_node on a project is refused.
          No "move" tool exists anywhere near the dispatcher.

The 27 tools (API.md): create_node update_node delete_node link_nodes tag_node
untag_node create_event update_event delete_event schedule_series delete_series
reschedule_series search_nodes check_conflict find_free_slots get_free_time
create_schedule update_schedule pause_schedule start_timer stop_timer log_time
get_day get_week get_month get_briefing ask_question.

Backend-only freeze (2026-10-05): no cost assertions. No network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import socket
import urllib.request

import pytest

SPEC = "docs/server/Chronos.md §5.5"

EXPECTED_TOOLS = frozenset([
    "create_node", "update_node", "delete_node", "link_nodes", "tag_node",
    "untag_node", "create_event", "update_event", "delete_event",
    "schedule_series", "delete_series", "reschedule_series",
    "search_nodes", "check_conflict", "find_free_slots", "get_free_time",
    "create_schedule", "update_schedule", "pause_schedule",
    "start_timer", "stop_timer", "log_time",
    "get_day", "get_week", "get_month", "get_briefing", "ask_question",
])


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network blocked in phase-2 tests: inject fakes (%s)" % SPEC)

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


# ---------------------------------------------------------------- helpers

def _load_tools():
    try:
        from chronos.ai.pipeline import tools as t
        return t
    except Exception as exc:
        pytest.fail("%s: missing chronos.ai.pipeline.tools (%s)" % (SPEC, exc))


class FakeStore:
    """Hand-rolled in-memory store (no mocks). Records every op."""

    def __init__(self):
        self.ops = []
        self.nodes = {"task-1": "task", "project-1": "project"}
        self.events = []
        self.hard_blocks = []
        self.series_created = []

    def _rec(self, op, payload):
        self.ops.append(op)
        return dict(payload)

    def get_node_kind(self, node_id):
        return self.nodes.get(node_id, "task")

    def create_node(self, args):
        return self._rec("create_node", {"id": "node-1"})

    def update_node(self, args):
        return self._rec("update_node", {"id": args.get("id", "node-1")})

    def delete_node(self, args):
        return self._rec("delete_node", {"id": args.get("id", "node-1")})

    def link_nodes(self, args):
        return self._rec("link_nodes", {"ok": True})

    def tag_node(self, args):
        return self._rec("tag_node", {"ok": True})

    def untag_node(self, args):
        return self._rec("untag_node", {"ok": True})

    def create_event(self, args):
        event = {"id": "event-%d" % (len(self.events) + 1), "start_ms": args["start_ms"]}
        self.events.append(event)
        return self._rec("create_event", event)

    def update_event(self, args):
        return self._rec("update_event", {"id": args.get("id", "event-1")})

    def delete_event(self, args):
        return self._rec("delete_event", {"id": args.get("id", "event-1")})

    def schedule_series(self, args):
        self.series_created.append(args)
        return self._rec("schedule_series", {"series_id": "series-1", "count": len(args["starts_ms"])})

    def delete_series(self, args):
        return self._rec("delete_series", {"series_id": args.get("series_id", "series-1")})

    def reschedule_series(self, args):
        return self._rec("reschedule_series", {"series_id": args.get("series_id", "series-1")})

    def search_nodes(self, args):
        return self._rec("search_nodes", {"nodes": []})

    def check_conflict(self, args):
        return self._rec("check_conflict", {"conflicts": []})

    def find_free_slots(self, args):
        return self._rec("find_free_slots", {"slots": []})

    def get_free_time(self, args):
        return self._rec("get_free_time", {"slots": []})

    def create_schedule(self, args):
        return self._rec("create_schedule", {"id": "sched-1"})

    def update_schedule(self, args):
        return self._rec("update_schedule", {"id": args.get("id", "sched-1")})

    def pause_schedule(self, args):
        return self._rec("pause_schedule", {"id": args.get("id", "sched-1")})

    def start_timer(self, args):
        return self._rec("start_timer", {"id": "timer-1"})

    def stop_timer(self, args):
        return self._rec("stop_timer", {"id": "timer-1"})

    def log_time(self, args):
        return self._rec("log_time", {"ok": True})

    def get_day(self, args):
        return self._rec("get_day", {"events": []})

    def get_week(self, args):
        return self._rec("get_week", {"events": []})

    def get_month(self, args):
        return self._rec("get_month", {"events": []})

    def get_briefing(self, args):
        return self._rec("get_briefing", {"date": args.get("date", "2026-08-04")})

    def ask_question(self, args):
        return self._rec("ask_question", {"question": args.get("question", "q?")})

    def list_events(self, from_ms, to_ms):
        return [e for e in self.events if from_ms <= e["start_ms"] < to_ms]

    def list_schedules(self):
        return list(self.hard_blocks)


def _args_for(tool):
    base = {
        "create_node": {"kind": "task", "title": "t"},
        "update_node": {"id": "task-1", "title": "t2"},
        "delete_node": {"id": "task-1"},
        "link_nodes": {"source_id": "task-1", "target_id": "task-1"},
        "tag_node": {"node_id": "task-1", "tag": "math"},
        "untag_node": {"node_id": "task-1", "tag": "math"},
        "create_event": {"title": "study", "start_ms": 1785288000000, "end_ms": 1785290700000},
        "update_event": {"id": "event-1", "title": "s2"},
        "delete_event": {"id": "event-1"},
        "schedule_series": {"node_id": "task-1", "tier": "medium", "max_count": 3,
                            "starts_ms": [1785288000000, 1785547200000]},
        "delete_series": {"series_id": "series-1"},
        "reschedule_series": {"series_id": "series-1", "max_count": 2},
        "search_nodes": {"q": "math"},
        "check_conflict": {"start_ms": 1785288000000, "end_ms": 1785290700000},
        "find_free_slots": {"date": "2026-08-05", "duration_min": 45},
        "get_free_time": {"date": "2026-08-05"},
        "create_schedule": {"title": "school", "starts_ms": 1785288000000,
                            "ends_at_ms": 1793064000000, "start_minute": 480,
                            "duration_min": 420, "weekdays": [1, 2, 3, 4, 5]},
        "update_schedule": {"id": "sched-1", "title": "s2"},
        "pause_schedule": {"id": "sched-1"},
        "start_timer": {"label": "focus", "mode": "stopwatch", "source": "test"},
        "stop_timer": {"source": "test"},
        "log_time": {"node_id": "task-1", "duration_ms": 1500000},
        "get_day": {"date": "2026-08-05"},
        "get_week": {"date": "2026-08-05"},
        "get_month": {"date": "2026-08-01"},
        "get_briefing": {"date": "2026-08-05"},
        "ask_question": {"question": "which day?"},
    }
    return dict(base[tool])


def _success(result):
    if isinstance(result, dict):
        return result.get("success")
    return getattr(result, "success", None)


# ---------------------------------------------------------------- tests

def test_tool_schemas_list_exactly_27_tools():
    """§5.5 + API.md: the dispatcher exposes all 27 tools."""
    t = _load_tools()
    schemas = getattr(t, "TOOL_SCHEMAS", None)
    assert isinstance(schemas, dict), "%s: TOOL_SCHEMAS must be a dict" % SPEC
    assert set(schemas.keys()) == set(EXPECTED_TOOLS), \
        "%s: schema set mismatch (missing %r, extra %r)" % (
            SPEC, sorted(set(EXPECTED_TOOLS) - set(schemas.keys())),
            sorted(set(schemas.keys()) - set(EXPECTED_TOOLS)))
    for name in sorted(EXPECTED_TOOLS):
        assert isinstance(schemas[name], dict), "%s: schema for %r must be a dict" % (SPEC, name)


@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_each_tool_dispatches_none_not_implemented(tool):
    """§5.5: all 27 tools dispatch — none returns 'not implemented'."""
    t = _load_tools()
    dispatcher = t.ToolDispatcher(FakeStore())
    result = dispatcher.dispatch(tool, _args_for(tool))
    assert _success(result) is True, \
        "%s: tool %r must dispatch with success True" % (SPEC, tool)


def test_series_is_one_tool_call_never_n():
    """§5.5 + §4.4: creating a series writes all review events in one tool call."""
    t = _load_tools()
    store = FakeStore()
    dispatcher = t.ToolDispatcher(store)
    starts = [1785288000000 + i * 86400000 for i in range(4)]
    result = dispatcher.dispatch("schedule_series", {
        "node_id": "task-1", "tier": "medium", "max_count": 4, "starts_ms": starts})
    assert _success(result) is True, "%s: bounded series must be accepted" % SPEC
    series_ops = [op for op in store.ops if op == "schedule_series"]
    assert len(series_ops) == 1, \
        "%s: series must be one store call, got %r" % (SPEC, len(series_ops))
    assert len(store.series_created) == 1, "%s: exactly one series payload expected" % SPEC


def test_no_ai_callable_move_tool():
    """§5.5: there is no AI-callable move tool — only create/delete event."""
    t = _load_tools()
    schemas = getattr(t, "TOOL_SCHEMAS", {})
    assert "move_event" not in schemas, "%s: move_event must not be a tool" % SPEC
    assert "move" not in schemas, "%s: move must not be a tool" % SPEC
    dispatcher = t.ToolDispatcher(FakeStore())
    result = dispatcher.dispatch("move_event", {"id": "event-1", "start_ms": 1})
    assert _success(result) is False, "%s: unknown move tool must never succeed" % SPEC


def test_hard_blocks_and_overlaps_resolved_in_code():
    """§5.5 + §6: hard blocks/overlaps resolved in code; response carries both slots."""
    t = _load_tools()
    store = FakeStore()
    store.events.append({"id": "event-9", "start_ms": 1785288000000})
    store.hard_blocks.append({"id": "sched-9"})
    dispatcher = t.ToolDispatcher(store)
    result = dispatcher.dispatch("create_event", {
        "title": "study", "start_ms": 1785288000000, "end_ms": 1785290700000})
    assert _success(result) is True, "%s: conflicting create must still resolve" % SPEC
    assert isinstance(result, dict), "%s: result must be a dict" % SPEC
    assert result["requested_start_ms"] == 1785288000000, \
        "%s: response must carry the requested slot" % SPEC
    assert result["start_ms"] != result["requested_start_ms"], \
        "%s: overlapping event must be pushed, not silently kept" % SPEC


def test_unbounded_series_refused():
    """§4.4 + §5.5: a series must be bounded (max_count and/or ends_on_ms)."""
    t = _load_tools()
    dispatcher = t.ToolDispatcher(FakeStore())
    unbounded = {"node_id": "task-1", "tier": "medium",
                 "starts_ms": [1785288000000, 1785547200000]}
    try:
        result = dispatcher.dispatch("schedule_series", unbounded)
    except (ValueError, t.DispatcherError if hasattr(t, "DispatcherError") else ValueError):
        return
    assert _success(result) is False, \
        "%s: unbounded series (no max_count/ends_on_ms) must be refused" % SPEC


def test_tags_never_on_projects():
    """§4.1 + decisions: tags apply to tasks and subtasks, never to projects."""
    t = _load_tools()
    dispatcher = t.ToolDispatcher(FakeStore())
    try:
        result = dispatcher.dispatch("tag_node", {"node_id": "project-1", "tag": "math"})
    except (ValueError, t.DispatcherError if hasattr(t, "DispatcherError") else ValueError):
        return
    assert _success(result) is False, "%s: tagging a project must be refused" % SPEC


def test_unimplemented_tool_never_success_true():
    """API.md: an unimplemented tool never returns success:true."""
    t = _load_tools()
    dispatcher = t.ToolDispatcher(FakeStore())
    result = dispatcher.dispatch("teleport_node", {"id": "task-1"})
    assert _success(result) is False, "%s: unknown tool must never succeed" % SPEC
