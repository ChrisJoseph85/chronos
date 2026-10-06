"""W2 Timer+Log: timer card AND time log in one window.

Timer: mode seg stopwatch|timer|pomodoro, target picker, strict toggle,
presets incl 25/5x4, live elapsed incl. remote-started sessions, 409 handling.
Log: per-node totals + breakdown drill project->children->tasks; locally
recorded voided stops shown struck-through. Clean stop keeps;
user-marked-distracted stop sends void:true.
"""
import time

from gi.repository import Adw, GLib, Gtk, Pango

from ..state import build_stop_body, format_ms, session_elapsed_ms, summarize_breakdown
from ..transport import ServerDown, TimerConflict

BUILTIN_PRESETS = [("25/5x4", 25, 5, 4), ("50/10", 50, 10, 1)]


class TimerLogWindow(Adw.ApplicationWindow):
    def __init__(self, app, client, state):
        super().__init__(application=app, title="Chronos Timer+Log",
                         default_width=760, default_height=640)
        self.client = client
        self.state = state
        self.mode = "stopwatch"
        self._tick_id = None
        self._local_stops = []  # [{label, ms, voided}] — voided rendered struck-through

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12); box.set_margin_bottom(12)
        box.set_margin_start(12); box.set_margin_end(12)
        toolbar.set_content(box)

        # -- timer card ----------------------------------------------------
        card = Adw.PreferencesGroup(title="Timer")
        box.append(card)
        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.mode_btns = {}
        first = None
        for m in ("stopwatch", "timer", "pomodoro"):
            b = Gtk.ToggleButton(label=m)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._on_mode, m)
            self.mode_btns[m] = b
            mode_row.append(b)
        self.mode_btns["stopwatch"].set_active(True)
        card.add(mode_row) if hasattr(card, "add") else box.append(mode_row)

        target_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        target_row.append(Gtk.Label(label="Target (min):"))
        self.target_spin = Gtk.SpinButton.new_with_range(1, 480, 1)
        self.target_spin.set_value(25)
        target_row.append(self.target_spin)
        self.strict = Gtk.Switch(valign=Gtk.Align.CENTER)
        target_row.append(Gtk.Label(label="Strict (void on violation):"))
        target_row.append(self.strict)
        box.append(target_row)

        preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        preset_row.append(Gtk.Label(label="Preset:"))
        self.preset_names = [p[0] for p in BUILTIN_PRESETS]
        self.presets = Gtk.DropDown.new_from_strings(self.preset_names)
        self.presets.connect("notify::selected", self._on_preset)
        preset_row.append(self.presets)
        box.append(preset_row)

        label_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label_row.append(Gtk.Label(label="Label:"))
        self.label_entry = Gtk.Entry(placeholder_text="what are you timing?", hexpand=True)
        label_row.append(self.label_entry)
        box.append(label_row)

        self.elapsed = Gtk.Label(label="--:--")
        self.elapsed.add_css_class("title-1")
        box.append(self.elapsed)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.start_btn = Gtk.Button(label="Start")
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.connect("clicked", self._on_start)
        btn_row.append(self.start_btn)
        self.stop_btn = Gtk.Button(label="Stop (keep)")
        self.stop_btn.connect("clicked", self._on_stop_clean)
        btn_row.append(self.stop_btn)
        self.void_btn = Gtk.Button(label="Stop as distracted (void)")
        self.void_btn.add_css_class("destructive-action")
        self.void_btn.connect("clicked", self._on_stop_void)
        btn_row.append(self.void_btn)
        box.append(btn_row)
        self.status = Gtk.Label(label="idle", xalign=0)
        box.append(self.status)

        # -- log ------------------------------------------------------------
        box.append(Gtk.Separator())
        box.append(Gtk.Label(label="Time log (totals + breakdown drill)", xalign=0))
        self.summary = Gtk.Label(label="", xalign=0, wrap=True)
        box.append(self.summary)
        self.back_btn = Gtk.Button(label="← up")
        self.back_btn.connect("clicked", self._on_up)
        box.append(self.back_btn)
        self.log_store = Gtk.ListStore(str, str, str)  # title, total, node_id
        self.log_view = Gtk.TreeView(model=self.log_store)
        for i, name in (("Node", 0), ("Total", 1)):
            self.log_view.append_column(Gtk.TreeViewColumn(name, Gtk.CellRendererText(), text=i))
        self.log_view.connect("row-activated", self._on_drill)
        scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=160)
        scroll.set_child(self.log_view)
        box.append(scroll)
        box.append(Gtk.Label(label="This window's stops (voided struck-through)", xalign=0))
        self.stops = Gtk.ListBox()
        box.append(self.stops)

        self._start_tick()
        self.refresh_remote()

    # -- helpers ------------------------------------------------------------
    def _toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=msg))

    def target_ms(self):
        return int(self.target_spin.get_value() * 60 * 1000)

    def strict_on(self):
        s = self.strict.get_state() if hasattr(self.strict, "get_state") else self.strict.get_active()
        return bool(s)

    def _on_mode(self, btn, mode):
        if btn.get_active():
            self.mode = mode

    def _on_preset(self, dd, _pspec):
        idx = dd.get_selected()
        if idx < len(BUILTIN_PRESETS):
            _name, focus, _brk, _cyc = BUILTIN_PRESETS[idx]
            self.target_spin.set_value(focus)
            if self.mode == "stopwatch":
                self.mode_btns["timer"].set_active(True)

    # -- timer actions -------------------------------------------------------
    def _on_start(self, _w):
        try:
            sess = self.client.timer_start(
                self.label_entry.get_text() or "untitled",
                mode=self.mode,
                target_ms=self.target_ms() if self.mode != "stopwatch" else None)
        except TimerConflict as e:
            self.status.set_text("409: session already running elsewhere — attached")
            self._toast("timer already running; showing live session")
            self.refresh_remote()
            return
        except (ServerDown, Exception) as e:
            self._toast(f"start failed: {e}")
            return
        self.state.timer_session = sess
        self.status.set_text(f"running: {sess.get('label', '')}")

    def _stop(self, distracted):
        body = build_stop_body("desktop", distracted=distracted)  # void:true iff distracted
        try:
            sess = self.client.timer_stop(source=body["source"], void=body["void"])
        except (ServerDown, Exception) as e:
            self._toast(f"stop failed: {e}")
            return
        self._record_local_stop(sess, voided=bool((sess or {}).get("voided", distracted)))
        self.state.timer_session = None
        self.status.set_text("idle")

    def _on_stop_clean(self, _w):
        self._stop(distracted=False)

    def _on_stop_void(self, _w):
        self._stop(distracted=True)

    def _record_local_stop(self, sess, voided):
        sess = sess or {}
        ms = session_elapsed_ms(sess, int(time.time() * 1000)) if sess.get("start_ms") else 0
        self._local_stops.append({"label": sess.get("label", "?"), "ms": ms, "voided": voided})
        label = Gtk.Label(xalign=0)
        text = f"{sess.get('label', '?')} — {format_ms(ms)}"
        if voided:
            label.set_markup(f"<s>{GLib.markup_escape_text(text)}</s> (voided)")
        else:
            label.set_text(text)
        self.stops.append(label)

    # -- live elapsed incl. remote sessions -----------------------------------
    def _start_tick(self):
        def tick():
            sess = self.state.timer_session
            if sess:
                now = int(time.time() * 1000)
                self.elapsed.set_text(format_ms(session_elapsed_ms(sess, now)))
            return True
        self._tick_id = GLib.timeout_add_seconds(1, tick)

    def refresh_remote(self):
        """Pick up sessions started on other devices (remote-started)."""
        def work():
            try:
                sess = self.client.timer_get()
            except Exception:
                return
            if sess:
                self.state.timer_session = sess
                GLib.idle_add(self.status.set_text,
                              f"running (remote): {sess.get('label', '')}")
        import threading
        threading.Thread(target=work, daemon=True).start()

    # -- log: totals + breakdown drill ----------------------------------------
    def refresh_log(self, node_id=None):
        def work():
            try:
                summary = self.client.timer_summary(node_id) if node_id else None
                rows = []
                if node_id:
                    import datetime
                    today = datetime.date.today().isoformat()
                    rows = self.client.timer_breakdown(
                        node_id, f"{today}T00:00:00+00:00", f"{today}T23:59:00+00:00") or []
                GLib.idle_add(self._render_log, summary or {}, rows, node_id)
            except Exception as e:
                GLib.idle_add(self._toast, f"log failed: {e}")
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _render_log(self, summary, rows, node_id):
        agg = summarize_breakdown(rows)
        self.summary.set_text(
            f"node={summary.get('node_total_ms', '?')}ms "
            f"descendants={summary.get('descendant_total_ms', '?')}ms "
            f"project={summary.get('project_total_ms', '?')}ms "
            f"| breakdown total {format_ms(agg['total_ms'])}")
        self.log_store.clear()
        self._current_node = node_id
        for r in agg["rows"]:
            self.log_store.append([r.get("title", ""), format_ms(r.get("total_ms", 0)),
                                   r.get("node_id", "")])

    def _on_drill(self, view, path, _col):
        node_id = self.log_store[path][2]
        if node_id:
            self.refresh_log(node_id)

    def _on_up(self, _w):
        self.refresh_log(None)
