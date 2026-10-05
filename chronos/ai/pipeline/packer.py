"""Context packer: priority-ordered assembly under a token ceiling.

Priority (§5.6): identity/prefs (1), ancestors (2), semantic+keyword (3),
±1d events (4), utterance verbatim last (5). Packing estimate len//4.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PackedContext:
    section_order: list
    prefix_text: str
    prompt_text: str
    now_iso: str
    utterance: str
    shown_items: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    total_checked: int = 0
    shown: int = 0
    estimated_tokens: int = 0
    day_events_included: list = field(default_factory=list)

    def summary(self):
        return "checked %d tasks, showing %d" % (self.total_checked, self.shown)


def _parse_iso(value):
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


class ContextPacker:
    def __init__(self, *, token_ceiling, top_n=8):
        self.token_ceiling = token_ceiling
        self.top_n = top_n

    def pack(self, *, identity, preferences, hard_blocks, now_iso,
             ancestors, semantic_hits, keyword_hits, day_events, utterance):
        semantic_hits = list(semantic_hits or [])
        keyword_hits = list(keyword_hits or [])
        ancestors = list(ancestors or [])
        day_events = list(day_events or [])

        combined = list(semantic_hits) + list(keyword_hits)
        total_checked = len(combined)
        shown_items = [{"title": h.get("title"), "relative": h.get("relative")}
                       for h in combined[:self.top_n]]
        shown = len(shown_items)

        now_dt = _parse_iso(now_iso)
        window = []
        if now_dt is not None:
            now_day = now_dt.date()
            for event in day_events:
                dt = _parse_iso(event.get("start_iso", ""))
                if dt is None:
                    continue
                if abs((dt.date() - now_day).days) <= 1:
                    window.append(event)
        else:
            window = list(day_events)

        prefix_text = (
            "identity: %s\npreferences: %s\nhard blocks: %s\nnow: %s"
            % (identity, preferences, hard_blocks, now_iso)
        )
        sections = {
            "identity": prefix_text,
            "ancestors": "ancestors: %s" % (" > ".join(ancestors) if ancestors else "none"),
            "hits": "\n".join(
                "task: %s (%s)" % (h["title"], h["relative"]) for h in shown_items
            ) or "hits: none",
            "day_events": "\n".join("event: %(title)s at %(start_iso)s" % e for e in window) or "events: none",
            "utterance": utterance,
        }
        order = ["identity", "ancestors", "hits", "day_events", "utterance"]
        drop_order = ["day_events", "hits", "ancestors"]

        dropped = []
        kept = list(order)
        prompt = "\n\n".join(sections[s] for s in kept)
        while len(prompt) // 4 > self.token_ceiling:
            dropped_any = False
            for name in drop_order:
                if name in kept:
                    kept.remove(name)
                    dropped.append(name)
                    dropped_any = True
                    break
            if not dropped_any:
                break
            prompt = "\n\n".join(sections[s] for s in kept)

        return PackedContext(
            section_order=kept,
            prefix_text=prefix_text,
            prompt_text=prompt,
            now_iso=now_iso,
            utterance=utterance,
            shown_items=shown_items,
            dropped=dropped,
            total_checked=total_checked,
            shown=shown,
            estimated_tokens=len(prompt) // 4,
            day_events_included=window,
        )
