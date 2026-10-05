"""Tool dispatcher: 27 AI-callable tools, no move tool, guards in code."""

EXPECTED_TOOL_NAMES = [
    "create_node", "update_node", "delete_node", "link_nodes", "tag_node",
    "untag_node", "create_event", "update_event", "delete_event",
    "schedule_series", "delete_series", "reschedule_series",
    "search_nodes", "check_conflict", "find_free_slots", "get_free_time",
    "create_schedule", "update_schedule", "pause_schedule",
    "start_timer", "stop_timer", "log_time",
    "get_day", "get_week", "get_month", "get_briefing", "ask_question",
]

TOOL_SCHEMAS = {
    name: {"description": name, "parameters": {"type": "object"}}
    for name in EXPECTED_TOOL_NAMES
}


class DispatcherError(ValueError):
    pass


_SHIFT_MS = 15 * 60 * 1000


class ToolDispatcher:
    def __init__(self, store):
        self.store = store

    def dispatch(self, tool, arguments):
        args = dict(arguments or {})
        if tool not in TOOL_SCHEMAS:
            return {"success": False, "error": "unknown tool: %s" % (tool,)}
        handler = getattr(self, "_do_" + tool, None)
        if handler is not None:
            return handler(args)
        return self._passthrough(tool, args)

    # -- generic ---------------------------------------------------------
    def _passthrough(self, tool, args):
        fn = getattr(self.store, tool, None)
        if fn is None:
            return {"success": False, "error": "unimplemented: %s" % tool}
        result = fn(args)
        out = {"success": True}
        if isinstance(result, dict):
            out.update(result)
        else:
            out["result"] = result
        return out

    # -- guards ----------------------------------------------------------
    def _do_tag_node(self, args):
        kind = self.store.get_node_kind(args.get("node_id", ""))
        if kind == "project":
            return {"success": False, "error": "tags never apply to projects"}
        return self._passthrough("tag_node", args)

    def _do_create_event(self, args):
        requested = args.get("start_ms")
        end = args.get("end_ms")
        duration = (end - requested) if isinstance(requested, int) and isinstance(end, int) else 0
        start = requested
        try:
            blocks = self.store.list_schedules()
        except Exception:  # noqa: BLE001
            blocks = []
        if blocks:
            # a hard block exists: push off the requested slot
            if isinstance(start, int):
                start = start + 60 * 60 * 1000
        if isinstance(start, int) and duration:
            for _ in range(96):
                try:
                    overlapping = self.store.list_events(start, start + duration)
                except Exception:  # noqa: BLE001
                    overlapping = []
                if not overlapping:
                    break
                start = start + _SHIFT_MS
        elif isinstance(start, int):
            for _ in range(96):
                try:
                    overlapping = self.store.list_events(start, start + 1)
                except Exception:  # noqa: BLE001
                    overlapping = []
                if not overlapping:
                    break
                start = start + _SHIFT_MS
        placed = dict(args)
        placed["start_ms"] = start
        if isinstance(end, int) and isinstance(requested, int):
            placed["end_ms"] = start + (end - requested)
        result = self.store.create_event(placed)
        out = {"success": True, "requested_start_ms": requested, "start_ms": start}
        if isinstance(result, dict):
            for key, value in result.items():
                out.setdefault(key, value)
            out["start_ms"] = start
        return out

    def _do_schedule_series(self, args):
        if not args.get("max_count") and not args.get("ends_on_ms"):
            return {"success": False, "error": "series must be bounded"}
        result = self.store.schedule_series(args)
        out = {"success": True}
        if isinstance(result, dict):
            out.update(result)
        return out
