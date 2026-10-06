"""W3 Bar: compact always-on-top action bar.

Shows timer state + elapsed + start/stop + enlarge button (opens W2).
Ship a Hyprland float rule as a docs snippet only (install.sh prints it).
"""
import time

from gi.repository import GLib, Gtk

from ..state import format_ms, session_elapsed_ms


class BarWindow(Gtk.Window):
    def __init__(self, app, client, state, on_enlarge):
        super().__init__(application=app, title="Chronos Bar",
                         default_width=340, default_height=52,
                         resizable=False)
        self.client = client
        self.state = state
        self._on_enlarge = on_enlarge
        self.set_keep_above(True)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(6); row.set_margin_bottom(6)
        row.set_margin_start(10); row.set_margin_end(10)
        self.set_child(row)

        self.dot = Gtk.Label(label="●")
        row.append(self.dot)
        self.info = Gtk.Label(label="idle", hexpand=True, xalign=0)
        row.append(self.info)
        self.toggle_btn = Gtk.Button(label="Start")
        self.toggle_btn.connect("clicked", self._on_toggle)
        row.append(self.toggle_btn)
        self.enlarge_btn = Gtk.Button.new_from_icon_name("window-maximize-symbolic")
        self.enlarge_btn.set_tooltip_text("Enlarge → open Timer+Log (W2)")
        self.enlarge_btn.connect("clicked", self._on_enlarge_btn)
        row.append(self.enlarge_btn)

        GLib.timeout_add_seconds(1, self._tick)

    def _tick(self):
        sess = self.state.timer_session
        if sess:
            now = int(time.time() * 1000)
            self.info.set_text(f"{sess.get('label', 'running')} {format_ms(session_elapsed_ms(sess, now))}")
            self.toggle_btn.set_label("Stop")
            self.dot.set_text("▶")
        else:
            self.info.set_text("idle")
            self.toggle_btn.set_label("Start")
            self.dot.set_text("●")
        return True

    def _on_toggle(self, _w):
        try:
            if self.state.timer_session:
                self.client.timer_stop(source="desktop-bar")
                self.state.timer_session = None
            else:
                self.state.timer_session = self.client.timer_start("bar session")
        except Exception:
            pass  # bar stays silent; W2 shows errors

    def _on_enlarge_btn(self, _w):
        if self._on_enlarge:
            self._on_enlarge()
