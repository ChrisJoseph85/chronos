"""Settings dialog: server URL + key, providers add/reorder, focus defaults.

Keys are NEVER shown: the instance-key entry is password-mode and write-only;
provider key VALUES are POSTed once and never retrieved (API returns key_ids
only). Provider order (position) = failover order; reorder via Up/Down.
"""
from gi.repository import Adw, Gtk


class SettingsDialog(Adw.PreferencesWindow):
    def __init__(self, app, client, state, parent=None):
        super().__init__(application=app, title="Chronos Settings",
                         default_width=560, default_height=600)
        if parent is not None:
            self.set_transient_for(parent)
        self.client = client
        self.state = state

        page = Adw.PreferencesPage(title="General")
        self.add(page)

        # -- server ------------------------------------------------------
        server = Adw.PreferencesGroup(title="Server")
        page.add(server)
        self.url_entry = Gtk.Entry(text=client.base_url)
        url_row = Adw.ActionRow(title="Server URL")
        url_row.add_suffix(self.url_entry)
        server.add(url_row)
        self.key_entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD,
                                   placeholder_text="(unchanged)")
        key_row = Adw.ActionRow(title="Instance key (never shown)")
        key_row.add_suffix(self.key_entry)
        server.add(key_row)
        save_btn = Gtk.Button(label="Save connection")
        save_btn.connect("clicked", self._on_save_connection)
        conn_row = Adw.ActionRow(title="Apply")
        conn_row.add_suffix(save_btn)
        server.add(conn_row)

        # -- providers ---------------------------------------------------
        prov = Adw.PreferencesGroup(title="Providers (order = failover order)")
        page.add(prov)
        self.prov_list = Gtk.ListBox()
        prov_row = Adw.ActionRow()
        prov_row.set_child(self.prov_list)
        prov.add(prov_row)
        add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.f_group = Gtk.DropDown.new_from_strings(["stt", "text", "embeddings"])
        self.f_name = Gtk.Entry(placeholder_text="name")
        self.f_url = Gtk.Entry(placeholder_text="base_url https://…")
        add_btn = Gtk.Button(label="Add provider")
        add_btn.connect("clicked", self._on_add_provider)
        for w in (self.f_group, self.f_name, self.f_url, add_btn):
            add_row.append(w)
        add_holder = Adw.ActionRow()
        add_holder.set_child(add_row)
        prov.add(add_holder)

        # -- focus shield default -----------------------------------------
        focus = Adw.PreferencesGroup(title="Focus shield (desktop)")
        page.add(focus)
        self.strict_row = Adw.SwitchRow(title="Strict by default (void on violation)",
                                        subtitle="Sessions started here only; no app blocking on Linux v1")
        self.strict_row.set_active(bool(state.strict_default))
        self.strict_row.connect("notify::active", self._on_strict)
        focus.add(self.strict_row)

        self.refresh_providers()

    # -- connection -------------------------------------------------------
    def _on_save_connection(self, _w):
        from ..state import save_key
        url = self.url_entry.get_text().strip().rstrip("/")
        if url:
            self.client.base_url = url
            self.state.base_url = url
        key = self.key_entry.get_text()
        if key:
            save_key(key)  # libsecret preferred, 0600-file fallback
            self.client.set_key(key)
            self.key_entry.set_text("")  # never keep it on screen
        self.add_toast("connection saved")

    def add_toast(self, msg):
        tw = self.get_first_child()
        while tw is not None and not isinstance(tw, Adw.ToastOverlay):
            tw = tw.get_first_child()
        if tw is not None:
            tw.add_toast(Adw.Toast(title=msg))

    # -- providers ----------------------------------------------------------
    def refresh_providers(self):
        while (row := self.prov_list.get_first_child()) is not None:
            self.prov_list.remove(row)
        try:
            data = self.client.providers() or {}
        except Exception:
            return
        for group in ("stt", "text", "embeddings"):
            for entry in data.get(group, []) or []:
                self.prov_list.append(self._provider_row(group, entry))

    def _provider_row(self, group, entry):
        pid = entry.get("id")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label=f"[{group}] {entry.get('name', pid)} "
                                   f"(keys: {entry.get('key_count', 0)})",
                             hexpand=True, xalign=0))
        up = Gtk.Button(label="↑")
        up.connect("clicked", self._on_move, group, pid, -1)
        row.append(up)
        down = Gtk.Button(label="↓")
        down.connect("clicked", self._on_move, group, pid, +1)
        row.append(down)
        key_btn = Gtk.Button(label="+ key")
        key_btn.connect("clicked", self._on_add_key, pid)
        row.append(key_btn)
        rm = Gtk.Button(label="✕")
        rm.connect("clicked", self._on_del_provider, pid)
        row.append(rm)
        return row

    def _on_add_provider(self, _w):
        groups = ["stt", "text", "embeddings"]
        group = groups[self.f_group.get_selected()]
        try:
            self.client.providers_add(group, self.f_name.get_text().strip(),
                                      self.f_url.get_text().strip())
        except Exception:
            pass
        self.refresh_providers()

    def _on_move(self, _w, group, pid, delta):
        # Reorder = PUT position (failover order). Read current list for index.
        try:
            data = self.client.providers() or {}
            entries = data.get(group, []) or []
            idx = next(i for i, e in enumerate(entries) if e.get("id") == pid)
            self.client.providers_update(pid, position=max(0, idx + delta))
        except Exception:
            pass
        self.refresh_providers()

    def _on_del_provider(self, _w, pid):
        try:
            self.client.providers_delete(pid)
        except Exception:
            pass
        self.refresh_providers()

    def _on_add_key(self, _w, pid):
        dlg = Gtk.Dialog(title="Add provider key (typed value never shown again)",
                         transient_for=self, modal=True)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        entry = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD)
        dlg.get_content_area().append(entry)
        dlg.show()
        def done(d, resp):
            if resp == Gtk.ResponseType.OK and entry.get_text():
                try:
                    self.client.providers_add_key(pid, entry.get_text())
                except Exception:
                    pass
            entry.set_text("")
            d.destroy()
            self.refresh_providers()
        dlg.connect("response", done)

    def _on_strict(self, row, _pspec):
        self.state.strict_default = bool(row.get_active())
        try:
            self.client.settings_update({"desktop_strict_default": self.state.strict_default})
        except Exception:
            pass
