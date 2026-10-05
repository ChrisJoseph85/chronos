"""Phase 1 pure scheduling tests (Chronos.md §4.4, §4.5, §4.7, §6, §7; API.md).

PURE core logic: this module imports no DB layer (no sqlite3, no chronos.db).
Each test resolves its hook from chronos.core.scheduling by canonical name
(the failure message names the expected signature) and pins spec behaviour:
half-open overlap, first-free-minute push with requested+actual slots, 1-minute
grid snap, bounded series payloads, schedule blocking, tier offsets, timezone
round-trip, and timer rollup rules.
"""

import ast
import datetime
import importlib
import importlib.util

import pytest

MIN = 60_000
T0 = 1785712800000  # 2026-08-04 10:00 UTC in epoch ms (Tuesday, mid-year)


def _sched():
    try:
        return importlib.import_module("chronos.core.scheduling")
    except ImportError:
        pytest.fail(
            "chronos.core.scheduling missing "
            "(Chronos.md §6; phase-1-core Part 1.5: pure scheduling logic, "
            "no DB, no framework imports). Implement overlap push, grid snap, "
            "series expansion, schedule blocking, tier offsets, tz helpers, "
            "timer rollup helpers there."
        )


def _pick(mod, names, purpose):
    for name in names:
        if hasattr(mod, name):
            return getattr(mod, name)
    pytest.fail(
        "chronos.core.scheduling must expose one of %s for %s "
        "(Chronos.md §6; phase-1-core Behaviour/Scheduling)" % (names, purpose)
    )


def _quadruple(result, req_start, req_end):
    """Extract (requested_start, requested_end, actual_start, actual_end)."""
    if isinstance(result, dict):
        keys = result.keys()
        rs = _first_present(result, keys, ("requested_start_ms", "requested_start", "req_start_ms", "req_start"))
        re_ = _first_present(result, keys, ("requested_end_ms", "requested_end", "req_end_ms", "req_end"))
        as_ = _first_present(result, keys, ("actual_start_ms", "actual_start", "start_ms", "start"))
        ae = _first_present(result, keys, ("actual_end_ms", "actual_end", "end_ms", "end"))
        if rs is not None and re_ is not None and as_ is not None and ae is not None:
            return (rs, re_, as_, ae)
    else:
        rs = _first_attr(result, ("requested_start_ms", "requested_start", "req_start_ms", "req_start"))
        re_ = _first_attr(result, ("requested_end_ms", "requested_end", "req_end_ms", "req_end"))
        as_ = _first_attr(result, ("actual_start_ms", "actual_start", "start_ms", "start"))
        ae = _first_attr(result, ("actual_end_ms", "actual_end", "end_ms", "end"))
        if rs is not None and re_ is not None and as_ is not None and ae is not None:
            return (rs, re_, as_, ae)
    if isinstance(result, (list, tuple)) and len(result) == 4:
        return (result[0], result[1], result[2], result[3])
    if isinstance(result, (list, tuple)) and len(result) == 2:
        return (req_start, req_end, result[0], result[1])
    pytest.fail(
        "Overlap resolver must return requested+actual slots "
        "(Chronos.md §6: response carries both). Got: %r" % (result,)
    )


def _first_present(mapping, keys, names):
    for name in names:
        if name in keys:
            return mapping[name]
    return None


def _first_attr(obj, names):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _resolve(mod, req_start, req_end, busy):
    fn = _pick(
        mod,
        ("resolve_overlap", "find_first_free_slot", "push_to_free_minute",
         "first_free_minute", "resolve_conflict"),
        "overlap push",
    )
    return _quadruple(fn(req_start, req_end, busy), req_start, req_end)


def test_overlap_pushes_to_first_free_minute():
    """Overlap pushes to the first free minute satisfying duration (Chronos.md §6)."""
    mod = _sched()
    busy = [(T0, T0 + 60 * MIN)]
    rs, re_, as_, ae = _resolve(mod, T0 + 30 * MIN, T0 + 60 * MIN, busy)
    assert (rs, re_) == (T0 + 30 * MIN, T0 + 60 * MIN)
    assert (as_, ae) == (T0 + 60 * MIN, T0 + 90 * MIN)


def test_result_carries_requested_and_actual():
    """Resolver returns both requested and actual slots (Chronos.md §6)."""
    mod = _sched()
    busy = [(T0, T0 + 60 * MIN)]
    rs, re_, as_, ae = _resolve(mod, T0 + 30 * MIN, T0 + 60 * MIN, busy)
    assert rs == T0 + 30 * MIN
    assert re_ == T0 + 60 * MIN
    assert (as_, ae) != (rs, re_)


def test_push_is_deterministic():
    """Same inputs always yield the same pushed slot (Chronos.md §6)."""
    mod = _sched()
    busy = [(T0, T0 + 60 * MIN), (T0 + 90 * MIN, T0 + 120 * MIN)]
    first = _resolve(mod, T0 + 30 * MIN, T0 + 60 * MIN, busy)
    second = _resolve(mod, T0 + 30 * MIN, T0 + 60 * MIN, busy)
    assert first == second


def test_touching_endpoints_do_not_conflict():
    """Half-open [from,to): an event starting when one ends is free (API.md Errors)."""
    mod = _sched()
    busy = [(T0, T0 + 60 * MIN)]
    rs, re_, as_, ae = _resolve(mod, T0 + 60 * MIN, T0 + 90 * MIN, busy)
    assert (as_, ae) == (rs, re_)


def test_grid_snaps_to_minute():
    """Start/end snap to the 1-minute grid (Chronos.md §7.2)."""
    mod = _sched()
    snap = _pick(mod, ("snap_to_minute", "snap_to_grid", "snap_ms"), "grid snap")
    assert snap(T0 + 30_500) == T0 + 60_000
    assert snap(T0) == T0
    assert snap(T0 + 59_999) == T0 + 60_000


def test_resolver_output_on_grid():
    """Pushed slots land on minute boundaries (Chronos.md §7.2)."""
    mod = _sched()
    busy = [(T0, T0 + 60 * MIN)]
    _, _, as_, ae = _resolve(mod, T0 + 30 * MIN + 45_000, T0 + 60 * MIN + 45_000, busy)
    assert as_ % MIN == 0
    assert ae % MIN == 0


def test_negative_duration_rejected():
    """A negative (or zero) duration is rejected, never accepted (phase-1-core Behaviour)."""
    mod = _sched()
    for names in (("validate_duration", "check_duration", "ensure_positive_duration",
                   "validate_duration_ms", "validate_slot"),):
        found = None
        for name in names:
            if hasattr(mod, name):
                found = getattr(mod, name)
                break
        if found is not None:
            with pytest.raises((ValueError, AssertionError)):
                found(T0 + 60 * MIN, T0)
            return
    with pytest.raises((ValueError, AssertionError)):
        _resolve(mod, T0 + 60 * MIN, T0, [])


def test_paused_schedule_does_not_block():
    """paused schedules do not block (Chronos.md §4.5; phase-1-core Behaviour)."""
    mod = _sched()
    fn = _pick(mod, ("is_schedule_blocking", "schedule_blocks", "is_blocking"),
               "schedule blocking")
    assert fn({"hard_block": 1, "paused": 1}) is False


def test_non_hard_block_schedule_does_not_block():
    """Non-hard_block schedules do not block (Chronos.md §4.5; phase-1-core Behaviour)."""
    mod = _sched()
    fn = _pick(mod, ("is_schedule_blocking", "schedule_blocks", "is_blocking"),
               "schedule blocking")
    assert fn({"hard_block": 0, "paused": 0}) is False
    assert fn({"hard_block": 1, "paused": 0}) is True


def test_tier_offsets():
    """Default tiers: hard 1,2,4,8,16 / medium 3,7,15,30 / easy 10,30,90 (Chronos.md §4.4)."""
    mod = _sched()
    if hasattr(mod, "TIER_OFFSETS"):
        mapping = getattr(mod, "TIER_OFFSETS")
        assert mapping["hard"] == [1, 2, 4, 8, 16]
        assert mapping["medium"] == [3, 7, 15, 30]
        assert mapping["easy"] == [10, 30, 90]
        return
    fn = _pick(mod, ("tier_offsets", "offsets_for_tier", "default_offsets"),
               "tier offsets")
    assert list(fn("hard")) == [1, 2, 4, 8, 16]
    assert list(fn("medium")) == [3, 7, 15, 30]
    assert list(fn("easy")) == [10, 30, 90]


def _series_payloads(mod, tier="hard", anchor="anchor-1", series="series-1"):
    fn = _pick(mod, ("build_series_events", "plan_series", "expand_series",
                     "series_events"), "series expansion")
    try:
        return list(fn(tier, anchor, series, T0))
    except TypeError:
        pass
    try:
        return list(fn({"tier": tier, "anchor_node_id": anchor,
                        "series_id": series, "anchor_ms": T0}))
    except TypeError as exc:
        pytest.fail(
            "Series builder must accept (tier, anchor id, series id, anchor ms) "
            "or a mapping with those keys (Chronos.md §4.4). Last error: %s" % (exc,)
        )


def _payload_field(payload, names):
    if isinstance(payload, dict):
        for name in names:
            if name in payload:
                return payload[name]
        return None
    for name in names:
        if hasattr(payload, name):
            return getattr(payload, name)
    return None


def test_series_payloads_carry_lineage():
    """Each review event carries series_id/review_index/derived_from (Chronos.md §4.4)."""
    mod = _sched()
    payloads = _series_payloads(mod)
    assert len(payloads) == 5
    for index, payload in enumerate(payloads, start=1):
        assert _payload_field(payload, ("series_id",)) == "series-1"
        assert _payload_field(payload, ("review_index", "index")) == index
        assert _payload_field(payload, ("derived_from", "anchor_node_id")) == "anchor-1"


def test_series_single_call_returns_all():
    """One call yields all events with sequential review_index (Chronos.md §4.4)."""
    mod = _sched()
    payloads = _series_payloads(mod, tier="medium")
    assert len(payloads) == 4
    indexes = [_payload_field(p, ("review_index", "index")) for p in payloads]
    assert indexes == [1, 2, 3, 4]


def test_timezone_round_trip():
    """Local wall time → UTC → local preserves the instant (Chronos.md §7.1)."""
    mod = _sched()
    to_utc = _pick(mod, ("local_to_utc_ms", "wall_to_utc_ms", "to_utc_ms",
                          "local_to_utc", "wall_to_utc"), "wall→UTC")
    to_local = _pick(mod, ("utc_to_local_iso", "to_local_iso", "utc_to_wall",
                            "utc_to_local", "render_local"), "UTC→wall")
    zone = "America/New_York"
    wall = "2026-07-15T16:00:00"
    utc_ms = to_utc(wall, zone)
    assert isinstance(utc_ms, int)
    back = to_local(utc_ms, zone)
    assert isinstance(back, str)
    assert datetime.datetime.fromisoformat(back).replace(tzinfo=None).isoformat() == wall


def test_timezone_uses_instance_zone_not_utc():
    """A non-UTC zone converts differently from UTC (Chronos.md §7.1; no hardcoded UTC)."""
    mod = _sched()
    to_utc = _pick(mod, ("local_to_utc_ms", "wall_to_utc_ms", "to_utc_ms",
                          "local_to_utc", "wall_to_utc"), "wall→UTC")
    wall = "2026-01-15T12:00:00"
    assert to_utc(wall, "America/New_York") != to_utc(wall, "UTC")


def _timer_args(mode_name, phase_name):
    try:
        enums = importlib.import_module("chronos.contracts")
    except ImportError:
        enums = None
    if enums is not None and hasattr(enums, "TimerMode"):
        try:
            mode = getattr(enums, "TimerMode")(mode_name)
        except ValueError:
            mode = mode_name
    else:
        mode = mode_name
    phase = phase_name
    if enums is not None and hasattr(enums, "TimerPhase") and phase_name is not None:
        try:
            phase = getattr(enums, "TimerPhase")(phase_name)
        except ValueError:
            phase = phase_name
    return mode, phase


def test_stopwatch_counts_even_with_target():
    """Stopwatch time counts; any target sent to it is ignored (Chronos.md §4.7)."""
    mod = _sched()
    fn = _pick(mod, ("counts_toward_total", "counts_for_totals", "include_in_totals",
                     "is_work_time"), "timer rollup")
    mode, phase = _timer_args("stopwatch", None)
    assert fn(mode, phase) is True


def test_pomodoro_break_excluded():
    """Pomodoro breaks are excluded from work totals (Chronos.md §4.7)."""
    mod = _sched()
    fn = _pick(mod, ("counts_toward_total", "counts_for_totals", "include_in_totals",
                     "is_work_time"), "timer rollup")
    focus_mode, focus_phase = _timer_args("pomodoro", "focus")
    break_mode, break_phase = _timer_args("pomodoro", "break")
    assert fn(focus_mode, focus_phase) is True
    assert fn(break_mode, break_phase) is False


def test_early_stop_focus_not_completed_cycle():
    """A focus phase stopped early is not a completed cycle (Chronos.md §4.7)."""
    mod = _sched()
    fn = _pick(mod, ("is_cycle_complete", "is_completed_cycle", "cycle_complete",
                     "focus_completed"), "cycle completion")
    mode, phase = _timer_args("pomodoro", "focus")
    assert fn(mode, phase, elapsed_ms=60_000, target_ms=1_500_000) is False
    assert fn(mode, phase, elapsed_ms=1_500_000, target_ms=1_500_000) is True


def test_core_scheduling_has_no_db_imports():
    """chronos/core/ is pure: no sqlite3 / chronos.db imports (Chronos.md §13)."""
    spec = importlib.util.find_spec("chronos.core.scheduling")
    if spec is None or spec.origin is None:
        pytest.fail("chronos.core.scheduling module not found (Chronos.md §13)")
    with open(spec.origin, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=spec.origin)
    banned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3" or alias.name.startswith("sqlite3."):
                    banned.add(alias.name)
                if alias.name == "chronos.db" or alias.name.startswith("chronos.db."):
                    banned.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                if node.module == "sqlite3" or node.module.startswith("sqlite3."):
                    banned.add(node.module)
                if node.module == "chronos.db" or node.module.startswith("chronos.db."):
                    banned.add(node.module)
    assert banned == set()
