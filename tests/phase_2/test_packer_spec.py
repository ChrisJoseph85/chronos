"""Phase 2 context-packer spec tests — Chronos.md §5.6 + decisions (Phase 2: 5).

Spec-only contract. Implementation surface pinned here:

  chronos.ai.pipeline.packer.ContextPacker
      __init__(*, token_ceiling, top_n=8)
      .pack(*, identity, preferences, hard_blocks, now_iso,
            ancestors, semantic_hits, keyword_hits, day_events, utterance)
          hit:      {"title": str, "relative": str}   (titles + relative dates only)
          day_event: {"title": str, "start_iso": str}  (absolute ISO-8601)
      -> PackedContext with:
          .section_order  list[str], first == "identity"
          .prefix_text    str (stable prefix: identity + hard blocks + prefs + now)
          .prompt_text    str (full assembled prompt)
          .now_iso        str (echo of the current time placed in the prefix)
          .utterance      str (echo, verbatim)
          .shown_items    list[{"title", "relative"}]
          .dropped        list[str] section names cut, lowest-priority first
          .total_checked  int
          .shown          int
          .estimated_tokens int (character estimate: len(prompt_text) // 4)
          .summary()      str, exactly "checked <N> tasks, showing <M>"

Priority order (§5.6): identity/prefs (1), ancestors (2), semantic+keyword (3),
±1d events (4), utterance verbatim last (5). No network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import socket
import urllib.request

import pytest

SPEC = "docs/server/Chronos.md §5.6"

NOW_ISO = "2026-08-04T12:00:00+00:00"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network blocked in phase-2 tests: inject fakes (%s)" % SPEC)

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


# ---------------------------------------------------------------- helpers

def _load_packer():
    try:
        from chronos.ai.pipeline.packer import ContextPacker
        return ContextPacker
    except Exception as exc:
        pytest.fail("%s: missing chronos.ai.pipeline.packer.ContextPacker (%s)" % (SPEC, exc))


def _base_kwargs(**over):
    kw = {
        "identity": "Chronos student scheduler",
        "preferences": "prefers mornings",
        "hard_blocks": "school Mon-Fri 08:00-15:00",
        "now_iso": NOW_ISO,
        "ancestors": ["Degree", "Databases"],
        "semantic_hits": [],
        "keyword_hits": [],
        "day_events": [],
        "utterance": "schedule DB review tomorrow 4pm for 45 mins",
    }
    kw.update(over)
    return kw


def _hits(n):
    return [{"title": "task-%02d" % i, "relative": "in %d days" % i} for i in range(n)]


# ---------------------------------------------------------------- tests

def test_stable_prefix_first_includes_current_time():
    """§5.6(1)+phase doc: stable prefix placed first; current time is in the prefix."""
    Packer = _load_packer()
    p = Packer(token_ceiling=4000, top_n=8).pack(**_base_kwargs())
    assert p.section_order[0] == "identity", \
        "%s: first section must be 'identity', got %r" % (SPEC, p.section_order[0])
    assert p.now_iso == NOW_ISO, "%s: packer must echo the current time, got %r" % (SPEC, p.now_iso)
    assert p.prompt_text[0:len(p.prefix_text)] == p.prefix_text, \
        "%s: prompt must start with the stable prefix" % SPEC


def test_ancestor_chain_second():
    """§5.6(2): the target node's ancestor chain comes second."""
    Packer = _load_packer()
    p = Packer(token_ceiling=4000, top_n=8).pack(**_base_kwargs())
    assert p.section_order[1] == "ancestors", \
        "%s: second section must be 'ancestors', got %r" % (SPEC, p.section_order[1:2])


def test_semantic_keyword_top_n_titles_and_relative_dates():
    """§5.6(3): semantic+keyword results capped at top N, titles + relative dates."""
    Packer = _load_packer()
    p = Packer(token_ceiling=4000, top_n=8).pack(**_base_kwargs(semantic_hits=_hits(20), keyword_hits=_hits(10)))
    assert p.total_checked == 30, "%s: must record 30 candidates checked, got %r" % (SPEC, p.total_checked)
    assert p.shown == 8, "%s: must show top 8, got %r" % (SPEC, p.shown)
    assert len(p.shown_items) == 8, "%s: shown_items length must be 8" % SPEC
    for item in p.shown_items:
        assert set(item.keys()) <= {"title", "relative"}, \
            "%s: hits carry titles + relative dates only, got %r" % (SPEC, sorted(item.keys()))


def test_day_events_limited_to_plus_minus_one_day():
    """§5.6(4): ±1 day of events for conflict checking."""
    Packer = _load_packer()
    events = [
        {"title": "two-days-ago", "start_iso": "2026-08-02T11:00:00+00:00"},
        {"title": "yesterday", "start_iso": "2026-08-03T12:00:00+00:00"},
        {"title": "now", "start_iso": "2026-08-04T12:00:00+00:00"},
        {"title": "tomorrow", "start_iso": "2026-08-05T08:00:00+00:00"},
        {"title": "in-two-days", "start_iso": "2026-08-06T13:00:00+00:00"},
    ]
    p = Packer(token_ceiling=4000, top_n=8).pack(**_base_kwargs(day_events=events))
    titles = [e["title"] for e in p.day_events_included] if hasattr(p, "day_events_included") else None
    assert titles is not None, "%s: PackedContext must expose day_events_included" % SPEC
    assert len(titles) == 3, "%s: exactly the ±1d window (3 of 5) must be kept, got %r" % (SPEC, titles)
    assert titles == ["yesterday", "now", "tomorrow"], \
        "%s: window contents wrong, got %r" % (SPEC, titles)


def test_utterance_verbatim_last():
    """§5.6(5): the user's utterance verbatim, last."""
    Packer = _load_packer()
    utterance = "schedule DB review tomorrow 4pm for 45 mins"
    p = Packer(token_ceiling=4000, top_n=8).pack(**_base_kwargs(utterance=utterance))
    assert p.utterance == utterance, "%s: utterance must round-trip verbatim" % SPEC
    assert p.prompt_text[len(p.prompt_text) - len(utterance):] == utterance, \
        "%s: prompt must end with the verbatim utterance" % SPEC


def test_overflow_drops_lowest_priority_first():
    """§5.6: overflow drops from the lowest priority upward (identity never cut)."""
    Packer = _load_packer()
    p = Packer(token_ceiling=60, top_n=8).pack(**_base_kwargs(
        semantic_hits=_hits(20),
        day_events=[{"title": "e", "start_iso": "2026-08-04T10:00:00+00:00"}],
    ))
    assert len(p.dropped) >= 1, "%s: tiny ceiling must force drops" % SPEC
    assert "identity" not in p.dropped, "%s: stable prefix must never be dropped" % SPEC
    assert "utterance" not in p.dropped, "%s: verbatim utterance must never be dropped" % SPEC
    assert p.prompt_text[len(p.prompt_text) - len(p.utterance):] == p.utterance, \
        "%s: utterance must survive overflow" % SPEC


def test_packer_records_cuts_for_ui():
    """§5.6: the packer records what it cut — 'checked 30 tasks, showing 8'."""
    Packer = _load_packer()
    p = Packer(token_ceiling=4000, top_n=8).pack(**_base_kwargs(semantic_hits=_hits(30)))
    assert p.total_checked == 30, "%s: total_checked must be 30" % SPEC
    assert p.shown == 8, "%s: shown must be 8" % SPEC
    assert p.summary() == "checked 30 tasks, showing 8", \
        "%s: summary mismatch, got %r" % (SPEC, p.summary())


def test_token_ceiling_respected_with_char_estimate():
    """§5.6 + ruling 5: per-turn token ceiling; packing estimate is len(text)//4."""
    Packer = _load_packer()
    p = Packer(token_ceiling=4000, top_n=8).pack(**_base_kwargs(semantic_hits=_hits(5)))
    assert p.estimated_tokens == len(p.prompt_text) // 4, \
        "%s: estimate must be len(text)//4, got %r" % (SPEC, p.estimated_tokens)
    assert p.estimated_tokens <= 4000, "%s: prompt exceeds its token ceiling" % SPEC
