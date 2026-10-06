"""W1 Planner: month grid + day agenda AND projects tree + tags in one window.

Tap a slot/day -> propose via `say` -> accept/reject card.
Reads: GET /api/events?from&to, GET /api/nodes?parent, WS patch.
"""
from gi.repository import Adw, GLib, Gtk

from ..notify import proposal_text
from ..state import AppState  # noqa: F401  (type clarity)


class PlannerWindow(Adw.ApplicationWindow):
    def __init__(self, app, client, state, ws):
        super().__init__(application=app, title="Chronos Planner",
                         default_width=1100, default_height=700)
        self.client = client
        self.state = state
        self.ws = ws
        self._pending_proposal = None

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Planner", subtitle="calendar + projects"))
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
        self.cal = Gtk.Calendar()
        self.cal.connect("day-selected", self._on_day)
        left.append(self.cal)
        left.append(Gtk.Label(label="Agenda", xalign=0))
        self.agenda = Gtk.ListBox()
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
        self.say_entry = Gtk.Entry(placeholder_text="say something (text box instead of voice)…")
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

    # -- data -------------------------------------------------------------
    def selected_date(self):
        dt = self.cal.get_date()
        return f"{dt.get_year():04d}-{dt.get_month():02d}-{dt.get_day_of_month():02d}"

    def refresh(self):
        def work():
            try:
                day = self.selected_date()
                events = self.client.events(f"{day}T00:00:00+00:00", f"{day}T23:59:00+00:00")
                nodes = self.client.nodes()
                GLib.idle_add(self._render, events or [], nodes or [])
            except Exception as e:
                GLib.idle_add(self._toast, f"refresh failed: {e}")
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _render(self, events, nodes):
        while (row := self.agenda.get_first_child()) is not None:
            self.agenda.remove(row)
        for ev in events:
            self.agenda.append(Gtk.Label(
                label=f"{ev.get('from', '?')} {ev.get('title', '')}", xalign=0))
        self.state.events = events
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

    def _on_day(self, _cal):
        self.refresh()

    def _toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=msg))

    # -- say + proposal card ----------------------------------------------
    def _on_say(self, _w):
        text = self.say_entry.get_text().strip()
        if text:
            self._send_say(text)

    def _on_propose(self, _w):
        self._send_say(f"schedule something on {self.selected_date()}")

    def _send_say(self, text):
        def work():
            try:
                res = self.client.say(text)
                GLib.idle_add(self._after_say, res or {})
            except Exception as e:
                GLib.idle_add(self._toast, f"say failed: {e}")
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
