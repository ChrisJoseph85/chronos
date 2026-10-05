"""Phase 1 contracts spec tests (Chronos.md §2.1, §4, §5.5; API.md; decisions.md).

Spec-text only: every check goes through imports and runtime inspection.
No source-text grepping, no mocks. All chronos imports are lazy so this file
collects cleanly and each test FAILS individually until chronos/ exists.
"""

import ast
import importlib
import importlib.util
import os

import pytest

# Chronos.md §5.5 + API.md MCP section: the frozen 27-tool set.
EXPECTED_TOOLS = [
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

# Chronos.md §4 enum tables (+ decisions.md 2026-10-03 rulings for
# SeriesState values, Reminder.offset_min sign, Schedule.weekdays [1..7]).
EXPECTED_ENUM_VALUES = {
    # §4.1: kind project|task|subtask
    "NodeKind": ("project", "task", "subtask"),
    # §4.1: status active|done|archived
    "NodeStatus": ("active", "done", "archived"),
    # §4.2: kind focus|class|break|review|admin
    "EventKind": ("focus", "class", "break", "review", "admin"),
    # §4.4: state active|retired|cancelled
    "SeriesState": ("active", "retired", "cancelled"),
    # §4.7: mode stopwatch|timer|pomodoro
    "TimerMode": ("stopwatch", "timer", "pomodoro"),
    # §4.7: phase pomodoro only focus|break
    "TimerPhase": ("focus", "break"),
    # §4.6: state pending|sent|cancelled
    "ReminderState": ("pending", "sent", "cancelled"),
    # §4.3: level Y|M|W|D
    "BucketLevel": ("Y", "M", "W", "D"),
    # §4.4: tier hard|medium|easy|custom
    "ReviewTier": ("hard", "medium", "easy", "custom"),
}

# Chronos.md §4 entity tables (field names taken from the §4 DDL blocks).
EXPECTED_MODEL_FIELDS = {
    # §4.1 nodes
    "Node": ("id", "parent_id", "kind", "title", "notes", "status",
             "created_at", "updated_at", "done_at"),
    # §4.1 tags
    "Tag": ("id", "name", "color"),
    # §4.1 node_tags
    "NodeTag": ("node_id", "tag_id"),
    # §4.2 events (bucket_id on events, NOT on nodes — decisions.md)
    "Event": ("id", "node_id", "title", "start_ms", "end_ms", "kind",
              "bucket_id", "series_id", "review_index", "derived_from",
              "soft_deleted", "created_at"),
    # §4.3 buckets (seq uncapped — decisions.md ruling 8)
    "Bucket": ("id", "level", "parent_id", "start_ms", "end_ms", "seq"),
    # §4.4 review_series
    "ReviewSeries": ("id", "node_id", "tier", "offsets_days",
                     "anchor_node_id", "max_count", "ends_on_ms",
                     "state", "created_at"),
    # §4.5 schedules (weekdays JSON [1..7] — decisions.md ruling 7)
    "Schedule": ("id", "title", "starts_ms", "ends_at_ms", "start_minute",
                 "duration_min", "weekdays", "hard_block", "paused",
                 "created_at"),
    # §4.6 reminders (offset_min positive = before start — decisions.md ruling 6)
    "Reminder": ("id", "event_id", "fire_at_ms", "offset_min", "state",
                 "channel", "created_at"),
    # §4.7 timer_sessions (target_ms NULL for stopwatch — decisions.md ruling 4)
    "TimerSession": ("id", "node_id", "label", "started_at", "ended_at",
                     "source", "reconciled", "mode", "target_ms",
                     "phase", "cycle"),
    # §4.7 audit (id INTEGER PRIMARY KEY — decisions.md ruling 5)
    "AuditEntry": ("id", "at", "device_id", "action", "target",
                   "context", "cost_usd"),
}

_CONTRACT_SUBMODULES = (
    "chronos.contracts.enums",
    "chronos.contracts.models",
    "chronos.contracts.tools",
    "chronos.contracts.protocols",
    "chronos.contracts.types",
    "chronos.contracts.schema",
)


def _contracts_pkg():
    try:
        return importlib.import_module("chronos.contracts")
    except ImportError:
        pytest.fail(
            "chronos.contracts package missing "
            "(Chronos.md §2.1/phase-1-core Part 1.1: frozen shared surface). "
            "Implement chronos/contracts/ with enums, models, TOOL_SCHEMAS, Protocols."
        )


def _lookup(name):
    """Find a contracts-level name on the package root or a known submodule."""
    pkg = _contracts_pkg()
    if hasattr(pkg, name):
        return getattr(pkg, name)
    for sub in _CONTRACT_SUBMODULES:
        try:
            mod = importlib.import_module(sub)
        except ImportError:
            continue
        if hasattr(mod, name):
            return getattr(mod, name)
    pytest.fail(
        "chronos.contracts must expose %r (package root or one of %s)"
        % (name, _CONTRACT_SUBMODULES)
    )


def _field_names(cls):
    """Declared field names for dataclass / pydantic v1+v2 / attrs / NamedTuple."""
    import dataclasses

    try:
        if dataclasses.is_dataclass(cls):
            return [f.name for f in dataclasses.fields(cls)]
    except (TypeError, AttributeError):
        pass
    model_fields = getattr(cls, "model_fields", None)
    if isinstance(model_fields, dict) and len(model_fields) > 0:
        return list(model_fields.keys())
    raw_v1 = cls.__dict__.get("__fields__")
    if isinstance(raw_v1, dict) and len(raw_v1) > 0:
        return list(raw_v1.keys())
    attrs_attrs = getattr(cls, "__attrs_attrs__", None)
    if attrs_attrs is not None:
        return [a.name for a in attrs_attrs]
    nt_fields = getattr(cls, "_fields", None)
    if isinstance(nt_fields, tuple) and len(nt_fields) > 0:
        return list(nt_fields)
    annotations = {}
    for klass in getattr(cls, "__mro__", (cls,)):
        own = klass.__dict__.get("__annotations__")
        if isinstance(own, dict):
            for key in own:
                if key not in annotations:
                    annotations[key] = True
    return list(annotations.keys())


def test_nodekind_values():
    """NodeKind members are project|task|subtask (Chronos.md §4.1)."""
    cls = _lookup("NodeKind")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["NodeKind"])


def test_nodestatus_values():
    """NodeStatus members are active|done|archived (Chronos.md §4.1)."""
    cls = _lookup("NodeStatus")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["NodeStatus"])


def test_eventkind_values():
    """EventKind members are focus|class|break|review|admin (Chronos.md §4.2)."""
    cls = _lookup("EventKind")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["EventKind"])


def test_seriesstate_values():
    """SeriesState is active|retired|cancelled (Chronos.md §4.4; not B1 ACTIVE/PAUSED/DONE)."""
    cls = _lookup("SeriesState")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["SeriesState"])


def test_timermode_values():
    """TimerMode members are stopwatch|timer|pomodoro (Chronos.md §4.7)."""
    cls = _lookup("TimerMode")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["TimerMode"])


def test_timerphase_values():
    """TimerPhase members are focus|break, pomodoro only (Chronos.md §4.7)."""
    cls = _lookup("TimerPhase")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["TimerPhase"])


def test_reminderstate_values():
    """ReminderState is pending|sent|cancelled (Chronos.md §4.6)."""
    cls = _lookup("ReminderState")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["ReminderState"])


def test_bucketlevel_values():
    """BucketLevel members are Y|M|W|D (Chronos.md §4.3)."""
    cls = _lookup("BucketLevel")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["BucketLevel"])


def test_reviewtier_values():
    """ReviewTier members are hard|medium|easy|custom (Chronos.md §4.4)."""
    cls = _lookup("ReviewTier")
    assert set(m.value for m in cls) == set(EXPECTED_ENUM_VALUES["ReviewTier"])


def test_enums_round_trip_through_constructor():
    """Every enum value survives Enum(value).value (Chronos.md §4; errors Layer 2)."""
    for name, values in EXPECTED_ENUM_VALUES.items():
        cls = _lookup(name)
        for value in values:
            assert cls(value).value == value
        assert len(list(cls)) == len(values)


def test_models_exist_for_every_entity():
    """contracts exposes all 10 §4 models (Chronos.md §4; phase-1-core Interface)."""
    for name in EXPECTED_MODEL_FIELDS:
        cls = _lookup(name)
        assert isinstance(cls, type)


def test_node_fields():
    """Node carries the §4.1 columns (Chronos.md §4.1)."""
    names = _field_names(_lookup("Node"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["Node"] if f not in names]
    assert missing == []


def test_tag_and_nodetag_fields():
    """Tag / NodeTag carry the §4.1 columns (Chronos.md §4.1)."""
    tag_names = _field_names(_lookup("Tag"))
    missing_tag = [f for f in EXPECTED_MODEL_FIELDS["Tag"] if f not in tag_names]
    assert missing_tag == []
    link_names = _field_names(_lookup("NodeTag"))
    missing_link = [f for f in EXPECTED_MODEL_FIELDS["NodeTag"] if f not in link_names]
    assert missing_link == []


def test_event_fields():
    """Event carries the §4.2 columns incl. bucket_id (Chronos.md §4.2)."""
    names = _field_names(_lookup("Event"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["Event"] if f not in names]
    assert missing == []


def test_bucket_fields():
    """Bucket carries the §4.3 columns (Chronos.md §4.3)."""
    names = _field_names(_lookup("Bucket"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["Bucket"] if f not in names]
    assert missing == []


def test_reviewseries_fields():
    """ReviewSeries carries the §4.4 columns (Chronos.md §4.4)."""
    names = _field_names(_lookup("ReviewSeries"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["ReviewSeries"] if f not in names]
    assert missing == []


def test_schedule_fields():
    """Schedule carries the §4.5 columns (Chronos.md §4.5)."""
    names = _field_names(_lookup("Schedule"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["Schedule"] if f not in names]
    assert missing == []


def test_reminder_fields():
    """Reminder carries the §4.6 columns (Chronos.md §4.6)."""
    names = _field_names(_lookup("Reminder"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["Reminder"] if f not in names]
    assert missing == []


def test_timersession_fields():
    """TimerSession carries the §4.7 columns (Chronos.md §4.7)."""
    names = _field_names(_lookup("TimerSession"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["TimerSession"] if f not in names]
    assert missing == []


def test_auditentry_fields():
    """AuditEntry carries the §4.7 audit columns (Chronos.md §4.7)."""
    names = _field_names(_lookup("AuditEntry"))
    missing = [f for f in EXPECTED_MODEL_FIELDS["AuditEntry"] if f not in names]
    assert missing == []


def test_node_has_no_bucket_id():
    """bucket_id lives on events, never on nodes (decisions.md bucket_id ruling)."""
    names = _field_names(_lookup("Node"))
    assert "bucket_id" not in names


def _tool_names(schemas):
    if isinstance(schemas, dict):
        return list(schemas.keys()), list(schemas.values())
    if isinstance(schemas, (list, tuple)) and len(schemas) > 0:
        names = []
        for item in schemas:
            if isinstance(item, dict):
                names.append(item.get("name"))
            else:
                names.append(getattr(item, "name", None))
        return names, list(schemas)
    pytest.fail("TOOL_SCHEMAS must be a dict or non-empty list (Chronos.md §5.5)")


def test_tool_schemas_cover_27_tools():
    """TOOL_SCHEMAS names exactly the 27 §5.5 tools (Chronos.md §5.5; API.md MCP)."""
    schemas = _lookup("TOOL_SCHEMAS")
    names, _ = _tool_names(schemas)
    assert set(names) == set(EXPECTED_TOOLS)
    assert len(names) == 27


def test_tool_schemas_each_have_shape():
    """Every tool schema has a name plus description/parameters (Chronos.md §5.5)."""
    schemas = _lookup("TOOL_SCHEMAS")
    names, values = _tool_names(schemas)
    assert set(names) == set(EXPECTED_TOOLS)
    for name, item in zip(names, values):
        if isinstance(item, dict):
            keys = set(item.keys())
            has_shape = (
                "description" in keys
                or "parameters" in keys
                or "input_schema" in keys
                or "inputSchema" in keys
                or "schema" in keys
            )
            assert has_shape
        else:
            assert getattr(item, "name", None) == name


def _assert_is_protocol(obj, name):
    is_proto = getattr(obj, "_is_protocol", False) is True
    assert isinstance(obj, type)
    assert is_proto


def test_core_protocols_exist():
    """Clock/IdGen/Embedder/Notifier/SearchBackend Protocols exist (phase-1-core Interface)."""
    for name in ("Clock", "IdGen", "Embedder", "Notifier", "SearchBackend"):
        _assert_is_protocol(_lookup(name), name)


def test_repo_protocols_exist():
    """Repo protocols exist alongside the core five (Chronos.md §2.1; phase-1-core Interface)."""
    pkg = _contracts_pkg()
    candidates = []
    for sub in ("chronos.contracts",) + _CONTRACT_SUBMODULES:
        try:
            mod = importlib.import_module(sub)
        except ImportError:
            continue
        for attr in dir(mod):
            if "Repo" in attr or "Store" in attr:
                obj = getattr(mod, attr)
                if isinstance(obj, type) and getattr(obj, "_is_protocol", False) is True:
                    candidates.append(attr)
    assert len(set(candidates)) >= 2


def _contracts_py_files():
    spec = importlib.util.find_spec("chronos.contracts")
    if spec is None or not spec.submodule_search_locations:
        pytest.fail("chronos.contracts package location unknown (Chronos.md §2.1)")
    pkgdir = spec.submodule_search_locations[0]
    found = {}
    for entry in os.listdir(pkgdir):
        if entry.endswith(".py"):
            found[entry[:-3]] = os.path.join(pkgdir, entry)
    assert len(found) > 0
    return found


def test_contracts_import_graph_is_acyclic():
    """chronos/contracts/ is an import DAG with no cycles (Chronos.md §2.1)."""
    files = _contracts_py_files()
    edges = {mod: set() for mod in files}
    external = set()
    for mod, path in files.items():
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "chronos.contracts" or alias.name.startswith("chronos.contracts."):
                        tail = alias.name.split(".")[-1]
                        if tail in edges and tail != mod:
                            edges[mod].add(tail)
                    elif alias.name == "chronos" or alias.name.startswith("chronos."):
                        external.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    if node.module:
                        tail = node.module.split(".")[-1]
                        if tail in edges and tail != mod:
                            edges[mod].add(tail)
                    else:
                        for alias in node.names:
                            if alias.name in edges and alias.name != mod:
                                edges[mod].add(alias.name)
                elif node.module:
                    if node.module == "chronos.contracts" or node.module.startswith("chronos.contracts."):
                        tail = node.module.split(".")[-1]
                        if tail in edges and tail != mod:
                            edges[mod].add(tail)
                    elif node.module == "chronos" or node.module.startswith("chronos."):
                        external.add(node.module)
    visiting = set()
    visited = set()
    cycle = []

    def visit(node, stack):
        if node in visited:
            return False
        if node in visiting:
            cycle.append(stack[stack.index(node):] + [node])
            return True
        visiting.add(node)
        for dep in edges[node]:
            if visit(dep, stack + [dep]):
                return True
        visiting.discard(node)
        visited.add(node)
        return False

    for mod in edges:
        if visit(mod, [mod]):
            break
    assert cycle == []


def test_contracts_import_only_stdlib_and_self():
    """contracts/ imports nothing from sibling modules (Chronos.md §2.1 boundaries)."""
    files = _contracts_py_files()
    outside = set()
    for mod, path in files.items():
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "chronos" or alias.name.startswith("chronos."):
                        if alias.name != "chronos.contracts" and not alias.name.startswith("chronos.contracts."):
                            outside.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    if node.module == "chronos" or node.module.startswith("chronos."):
                        if node.module != "chronos.contracts" and not node.module.startswith("chronos.contracts."):
                            outside.add(node.module)
    assert outside == set()
