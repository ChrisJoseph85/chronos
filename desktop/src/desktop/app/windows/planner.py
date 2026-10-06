"""W1 Planner: month grid + day agenda AND projects tree + tags in one window.

Tap a slot/day -> propose via `say` -> accept/reject card.
Reads: GET /api/events?from&to, GET /api/nodes?parent, WS patch.
"""
from __future__ import annotations

import calendar
import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..notify import proposal_text
from ..state import AppState  # noqa: F401  (type clarity)

WEEKDAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# -- pure calendar/agenda logic (GTK-free, unit-tested) ----------------------
def month_title(year, month):
    """Properly capitalized month label, e.g. 'October 2026'."""
    return f"{calendar.month_name[int(month)]} {int(year)}"


def shift_month(year, month, delta):
    """Shift (year, month) by delta months; handles year rollover."""
    idx = (int(year) * 12 + (int(month) - 1)) + int(delta)
    return (idx // 12, idx % 12 + 1)


def month_grid(year, month):
    """Weeks (Mon-first) of datetime.date covering the month, padded."""
    return calendar.Calendar(firstweekday=0).monthdatescalendar(int(year), int(month))


def month_range_iso(year, month):
    """(from_iso, to_iso) covering the viewed month for GET /api/events."""
    last = calendar.monthrange(int(year), int(month))[1]
    return (f"{int(year):04d}-{int(month):02d}-01T00:00:00+00:00",
            f"{int(year):04d}-{int(month):02d}-{last:02d}T23:59:00+00:00")


def _ev_from(ev):
    ev = ev or {}
    return ev.get("from") or ev.get("start") or ev.get("from_iso") or ""


def event_day_key(ev):
    """YYYY-MM-DD of an event, or '' when unknown."""
    return str(_ev_from(ev))[:10] if _ev_from(ev) else ""


def build_markers(events):
    """Day -> event count (drives per-day markers; >1 = multi-event day)."""
    markers = {}
    for ev in events or []:
        day = event_day_key(ev)
        if day:
            markers[day] = markers.get(day, 0) + 1
    return markers


def sort_agenda(events):
    """Time-ordered agenda (stable; untimed sink, then title)."""
    return sorted(list(events or []),
                  key=lambda e: (str(_ev_from(e)) or "~~~~", str((e or {}).get("title") or "")))


def event_time_label(ev):
    from_iso = str(_ev_from(ev))
    return from_iso[11:16] if len(from_iso) >= 16 else "--:--"


def event_kind_label(ev):
    kind = str((ev or {}).get("kind") or "event").strip()
    return kind[:1].upper() + kind[1:] if kind else "Event"


def prefill_for_event(ev, date_str=None):
    """Say-box prefill for a tapped agenda event (capitalized)."""
    title = str((ev or {}).get("title") or "untitled").strip() or "untitled"
    day = date_str or event_day_key(ev)
    at = event_time_label(ev)
    if day and at != "--:--":
        return f"Schedule '{title}' on {day} at {at}"
    if day:
        return f"Schedule '{title}' on {day}"
    return f"Schedule '{title}'"


def event_detail_text(ev):
    ev = ev or {}
    title = ev.get("title") or "untitled"
    return (f"{event_time_label(ev)}  {title} [{event_kind_label(ev)}]"
            f"\n{(_ev_from(ev) or '').strip()}")


class PlannerWindow(Adw.ApplicationWindow):
    def __init__(self, app, client, state, ws):
        super().__init__(application=app, title="Chronos Planner",
                         default_width=1100, default_height=700)
        self.client = client
        self.state = state
        self.ws = ws
        self._pending_proposal = None

        today = datetime.date.today()
        self.view_year, self.view_month = today.year, today.month
        self.selected_day = today
        self._month_events = []
        self._agenda_events = []
        self._day_buttons = {}  # iso -> Gtk.Button

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Planner", subtitle="Calendar + Projects"))
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)
        toolbar.add_top_bar(header)

        main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        main.set_margin_top(12); main.set_margin_bottom(12)
        main.set_margin_start(12); main.set_margin_end(12)
        toolbar.set_content(main)

        # -- left: calendar + agenda -------------------------------------
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_size_request(380, -1)
        main.append(left)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.prev_btn = Gtk.Button(label="‹ Prev")
        self.prev_btn.connect("clicked", self._on_prev)
        nav.append(self.prev_btn)
        self.month_label = Gtk.Label(label="", hexpand=True, xalign=1)
        self.month_label.add_css_class("title-3")
        nav.append(self.month_label)
        self.today_btn = Gtk.Button(label="Today")
        self.today_btn.connect("clicked", self._on_today)
        nav.append(self.today_btn)
        self.next_btn = Gtk.Button(label="Next ›")
        self.next_btn.connect("clicked", self._on_next)
        nav.append(self.next_btn)
        left.append(nav)

        dow = Gtk.Grid(column_spacing=4)
        dow.set_column_homogeneous(True)
        for i, name in enumerate(WEEKDAY_HEADERS):
            lab = Gtk.Label(label=name, xalign=1)
            lab.add_css_class("dim-label")
            dow.attach(lab, i, 0, 1, 1)
        left.append(dow)

        self.grid = Gtk.Grid(column_spacing=4, row_spacing=4)
        self.grid.set_column_homogeneous(True)
        left.append(self.grid)

        left.append(Gtk.Label(label="Agenda", xalign=0))
        self.agenda = Gtk.ListBox()
        self.agenda.connect("row-activated", self._on_agenda_tap)
        agenda_scroll = Gtk.ScrolledWindow(vexpand=True)
        agenda_scroll.set_child(self.agenda)
        left.append(agenda_scroll)
        self.propose_btn = Gtk.Button(label="Propose into selected slot (say)")
        self.propose_btn.connect("clicked", self._on_propose)
        left.append(self.propose_btn)

        # -- right: projects tree + tags ---------------------------------
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.set_hexpand(True)
        main.append(right)
        right.append(Gtk.Label(label="Projects → subprojects → tasks → subtasks", xalign=0))
        self.store = Gtk.TreeStore(str, str, str)  # title, node_id, kind
        self.tree = Gtk.TreeView(model=self.store)
        for i, name in (("Title", 0), ("Kind", 2)):
            col = Gtk.TreeViewColumn(name, Gtk.CellRendererText(), text=i)
            self.tree.append_column(col)
        tree_scroll = Gtk.ScrolledWindow(vexpand=True)
        tree_scroll.set_child(self.tree)
        right.append(tree_scroll)
        right.append(Gtk.Label(label="Tags", xalign=0))
        self.tags = Gtk.FlowBox(max_children_per_line=12, selection_mode=Gtk.SelectionMode.NONE)
        right.append(self.tags)

        # -- bottom: say box + proposal card ------------------------------
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right.append(bottom)
        say_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.say_entry = Gtk.Entry(placeholder_text="Say something (text box instead of voice)…")
        self.say_entry.connect("activate", self._on_say)
        say_row.append(self.say_entry)
        say_btn = Gtk.Button(label="Say")
        say_btn.connect("clicked", self._on_say)
        say_row.append(say_btn)
        bottom.append(say_row)

        self.card = Adw.Bin()
        card_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.card_msg = Gtk.Label(wrap=True, hexpand=True, xalign=0)
        card_box.append(self.card_msg)
        accept = Gtk.Button(label="Accept")
        accept.add_css_class("suggested-action")
        accept.connect("clicked", self._on_accept)
        card_box.append(accept)
        reject = Gtk.Button(label="Reject")
        reject.connect("clicked", self._on_reject)
        card_box.append(reject)
        self.card.set_child(card_box)
        self.card.set_visible(False)
        bottom.append(self.card)

        self._redraw_grid()
        self.refresh()

    # -- data -------------------------------------------------------------
    def selected_date(self):
        return self.selected_day.isoformat()

    @staticmethod
    def prefill_for_tap(ev, date_str=None):
        return prefill_for_event(ev, date_str)

    def refresh(self):
        view = (self.view_year, self.view_month)
        day = self.selected_date()

        def work():
            try:
                m_from, m_to = month_range_iso(*view)
                month_events = self.client.events(m_from, m_to)
                events = self.client.events(f"{day}T00:00:00+00:00", f"{day}T23:59:00+00:00")
                nodes = self.client.nodes()
                GLib.idle_add(self._render_all, events or [], nodes or [], month_events or [])
            except Exception as e:
                GLib.idle_add(self._toast, f"Refresh failed: {e}")
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _render_all(self, day_events, nodes, month_events):
        self._month_events = list(month_events)
        self._redraw_grid()  # grid only: no full-window flicker
        self._render_agenda(day_events)
        self._render_nodes(nodes)

    def _render(self, events, nodes):
        """Compat wrapper: day agenda + nodes (grid markers refreshed too)."""
        self._render_agenda(events)
        self._render_nodes(nodes)

    # -- month grid (redraw grid only on paging) ---------------------------
    def _redraw_grid(self):
        markers = build_markers(self._month_events)
        today_iso = datetime.date.today().isoformat()
        sel_iso = self.selected_day.isoformat()
        self.month_label.set_text(month_title(self.view_year, self.view_month))
        child = self.grid.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt
        self._day_buttons.clear()
        for r, week in enumerate(month_grid(self.view_year, self.view_month)):
            for c, day in enumerate(week):
                iso = day.isoformat()
                n = markers.get(iso, 0)
                label = f"{day.day}\n{'•' if n == 1 else f'•×{n}' if n else ''}".rstrip("\n")
                btn = Gtk.Button(label=label)
                btn.set_has_frame(False)
                if day.month != self.view_month:
                    btn.add_css_class("dim-label")
                    btn.set_opacity(0.45)
                if iso == today_iso:
                    btn.add_css_class("suggested-action")  # today highlight
                if iso == sel_iso:
                    btn.add_css_class("opaque")  # selected-day ring
                btn.connect("clicked", self._on_day_tapped, day)
                self.grid.attach(btn, c, r, 1, 1)
                self._day_buttons[iso] = btn

    def _page(self, delta):
        self.view_year, self.view_month = shift_month(self.view_year, self.view_month, delta)
        self._redraw_grid()  # smooth paging: grid only, then markers fill in
        self.refresh()

    def _on_prev(self, _w):
        self._page(-1)

    def _on_next(self, _w):
        self._page(1)

    def _on_today(self, _w):
        today = datetime.date.today()
        self.view_year, self.view_month = today.year, today.month
        self.selected_day = today
        self._redraw_grid()
        self.refresh()

    def _on_day_tapped(self, _btn, day):
        self.selected_day = day
        if (day.year, day.month) != (self.view_year, self.view_month):
            self.view_year, self.view_month = day.year, day.month
        self._redraw_grid()  # selected ring moves; grid only
        self.refresh()

    def _on_day(self, _cal=None):
        self.refresh()

    # -- agenda: time-ordered, kind chips, tap -> detail + say prefill -----
    def _render_agenda(self, events):
        self._agenda_events = sort_agenda(events)
        self.state.events = list(events or [])
        child = self.agenda.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.agenda.remove(child)
            child = nxt
        if not self._agenda_events:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label="No events — enjoy the quiet.", xalign=0))
            row.set_activatable(False)
            self.agenda.append(row)
            return
        for ev in self._agenda_events:
            row = Gtk.ListBoxRow()
            row._event = ev
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(4); box.set_margin_bottom(4)
            box.set_margin_start(8); box.set_margin_end(8)
            time_lab = Gtk.Label(label=event_time_label(ev), xalign=0)
            time_lab.add_css_class("monospace")
            box.append(time_lab)
            title_lab = Gtk.Label(label=str(ev.get("title") or "Untitled"),
                                  hexpand=True, xalign=0, wrap=True)
            box.append(title_lab)
            kind_lab = Gtk.Label(label=event_kind_label(ev), xalign=1)
            kind_lab.add_css_class("dim-label")
            box.append(kind_lab)
            row.set_child(box)
            row.set_tooltip_text(event_detail_text(ev))
            self.agenda.append(row)

    def _on_agenda_tap(self, _box, row):
        ev = getattr(row, "_event", None)
        if not ev:
            return
        self.say_entry.set_text(self.prefill_for_tap(ev, self.selected_date()))
        self._toast(event_detail_text(ev))

    # -- projects tree + tags (unchanged) -----------------------------------
    def _render_nodes(self, nodes):
        self.store.clear()
        tags = set()
        for n in nodes:
            self.store.append(None, [n.get("title", ""), n.get("id", ""), n.get("kind", "")])
            for t in n.get("tags", []) or []:
                tags.add(t)
        while (chip := self.tags.get_first_child()) is not None:
            self.tags.remove(chip)
        for t in sorted(tags):
            self.tags.append(Gtk.Label(label=f"#{t}"))
        self.state.nodes = nodes

    def _toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=msg))

    # -- say + proposal card ----------------------------------------------
    def _on_say(self, _w):
        text = self.say_entry.get_text().strip()
        if text:
            self._send_say(text)

    def _on_propose(self, _w):
        self._send_say(f"Schedule something on {self.selected_date()}")

    def _send_say(self, text):
        def work():
            try:
                res = self.client.say(text)
                GLib.idle_add(self._after_say, res or {})
            except Exception as e:
                GLib.idle_add(self._toast, f"Say failed: {e}")
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _after_say(self, res):
        pid = res.get("proposal_id")
        if pid:
            self._pending_proposal = pid
            self.state.proposals[pid] = res
            self.card_msg.set_text(res.get("message") or f"proposal {pid}")
            self.card.set_visible(True)
            title, body = proposal_text(res)
            self._toast(f"{title}: {body[:80]}")
        else:
            self._toast(res.get("message") or "done")

    def show_proposal(self, proposal):
        """Called from WS proposal frames."""
        pid = (proposal or {}).get("proposal_id")
        if not pid:
            return
        self._pending_proposal = pid
        self.state.proposals[pid] = proposal
        self.card_msg.set_text(proposal.get("message") or f"proposal {pid}")
        self.card.set_visible(True)

    def _ws_decide(self, verb):
        if not self._pending_proposal:
            return
        pid = self._pending_proposal
        self._pending_proposal = None
        self.card.set_visible(False)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.ws.send({verb: pid}))
                return
        except RuntimeError:
            pass
        self.ws.queue({verb: pid})  # flushed on (re)connect

    def _on_accept(self, _w):
        self._ws_decide("accept")

    def _on_reject(self, _w):
        self._ws_decide("reject")
