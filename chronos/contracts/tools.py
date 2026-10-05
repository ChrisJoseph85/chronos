"""TOOL_SCHEMAS for the frozen 27 tools (Chronos.md §5.5). Stdlib only."""

from __future__ import annotations

_TOOL_NAMES = [
    "create_node", "update_node", "delete_node", "link_nodes",
    "tag_node", "untag_node",
    "create_event", "update_event", "delete_event",
    "schedule_series", "delete_series", "reschedule_series",
    "search_nodes", "check_conflict", "find_free_slots", "get_free_time",
    "create_schedule", "update_schedule", "pause_schedule",
    "start_timer", "stop_timer", "log_time",
    "get_day", "get_week", "get_month", "get_briefing",
    "ask_question",
]


def _schema(name: str, description: str, properties: dict | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
        },
    }


TOOL_SCHEMAS: dict = {
    "create_node": _schema("create_node", "Create a node (project/task/subtask).",
                           {"parent_id": {"type": ["string", "null"]}, "kind": {"type": "string"},
                            "title": {"type": "string"}, "notes": {"type": ["string", "null"]}}),
    "update_node": _schema("update_node", "Update a node by id.",
                           {"id": {"type": "string"}}),
    "delete_node": _schema("delete_node", "Delete a node by id (cascades).",
                           {"id": {"type": "string"}}),
    "link_nodes": _schema("link_nodes", "Record a non-structural link between two nodes.",
                          {"source_id": {"type": "string"}, "target_id": {"type": "string"}}),
    "tag_node": _schema("tag_node", "Attach a tag to a task or subtask (never a project).",
                        {"node_id": {"type": "string"}, "tag": {"type": "string"}}),
    "untag_node": _schema("untag_node", "Remove a tag from a node.",
                          {"node_id": {"type": "string"}, "tag": {"type": "string"}}),
    "create_event": _schema("create_event", "Create an event; overlaps push to first free minute.",
                            {"node_id": {"type": ["string", "null"]}, "title": {"type": "string"},
                             "start_ms": {"type": "integer"}, "end_ms": {"type": "integer"}}),
    "update_event": _schema("update_event", "Update an event by id.",
                            {"id": {"type": "string"}}),
    "delete_event": _schema("delete_event", "Delete (soft) an event by id.",
                            {"id": {"type": "string"}}),
    "schedule_series": _schema("schedule_series", "Create a bounded review series in one call.",
                               {"node_id": {"type": "string"}, "tier": {"type": "string"}}),
    "delete_series": _schema("delete_series", "Bulk-delete a review series.",
                             {"series_id": {"type": "string"}}),
    "reschedule_series": _schema("reschedule_series", "Bulk-reschedule a review series.",
                                 {"series_id": {"type": "string"}}),
    "search_nodes": _schema("search_nodes", "Keyword + semantic node search.",
                            {"q": {"type": "string"}, "limit": {"type": "integer"}}),
    "check_conflict": _schema("check_conflict", "Check a slot for conflicts.",
                              {"start_ms": {"type": "integer"}, "end_ms": {"type": "integer"}}),
    "find_free_slots": _schema("find_free_slots", "Find free slots in a window.",
                               {"from_ms": {"type": "integer"}, "to_ms": {"type": "integer"}}),
    "get_free_time": _schema("get_free_time", "Report free time in a window.",
                             {"from_ms": {"type": "integer"}, "to_ms": {"type": "integer"}}),
    "create_schedule": _schema("create_schedule", "Create a recurring hard-block schedule.",
                               {"title": {"type": "string"}}),
    "update_schedule": _schema("update_schedule", "Update a schedule by id.",
                               {"id": {"type": "string"}}),
    "pause_schedule": _schema("pause_schedule", "Pause or resume a schedule.",
                              {"id": {"type": "string"}, "paused": {"type": "boolean"}}),
    "start_timer": _schema("start_timer", "Start a timer (409 if one running).",
                           {"node_id": {"type": ["string", "null"]}, "label": {"type": "string"},
                            "mode": {"type": "string"}}),
    "stop_timer": _schema("stop_timer", "Stop the running timer.",
                          {"source": {"type": "string"}}),
    "log_time": _schema("log_time", "Log time and report per-node rollup.",
                        {"node_id": {"type": "string"}}),
    "get_day": _schema("get_day", "Get one day's events.",
                       {"date": {"type": "string"}}),
    "get_week": _schema("get_week", "Get one week's events.",
                        {"date": {"type": "string"}}),
    "get_month": _schema("get_month", "Get one month's events.",
                         {"date": {"type": "string"}}),
    "get_briefing": _schema("get_briefing", "Get the daily briefing.",
                            {"date": {"type": "string"}}),
    "ask_question": _schema("ask_question", "Ask the user one clarification question.",
                            {"question": {"type": "string"}}),
}

assert set(TOOL_SCHEMAS) == set(_TOOL_NAMES) and len(TOOL_SCHEMAS) == 27
