window.Chronos.screens.settings = {
  init(el, ctx) {
    const p = ctx.api.prefs();
    el.innerHTML = `<div class="card"><h3>Server</h3><div class="row">
        <input id="s-url" placeholder="http://host:8080" value="${p.serverUrl ?? ""}" style="flex:1">
        <input id="s-key" type="password" placeholder="instance key" value="${p.key ?? ""}" style="flex:1">
        <button id="s-save">Save</button><button id="s-find" class="ghost">Auto-find</button></div>
        <div id="s-health">unknown</div></div>
      <div class="card"><h3>Providers</h3><div id="s-prov"></div>
        <div class="row"><input id="s-pname" placeholder="provider name"><button id="s-padd">Add</button></div></div>
      <div class="card"><h3>App</h3><div class="row">
        <label><input type="checkbox" id="s-auto" ${ctx.autostart ? "checked" : ""}> Start on login</label></div>
        <div class="row" id="s-notif"></div></div>
      <div class="ai-mount"></div>`;
    el.querySelector("#s-save").addEventListener("click", async () => {
      ctx.savePrefs({
        serverUrl: el.querySelector("#s-url").value.trim(),
        key: el.querySelector("#s-key").value,
      });
      const r = await ctx.api.health();
      el.querySelector("#s-health").textContent = r.ok ? "connected" : "unreachable";
      if (!r.ok) ctx.banner("Settings: server unreachable — check URL/key.");
      else ctx.banner(null);
    });
    el.querySelector("#s-find").addEventListener("click", async () => {
      const found = await window.ChronosDiscover.find(ctx.api.prefs().key);
      el.querySelector("#s-health").textContent = found ?? "not found on LAN";
      if (found) { ctx.savePrefs({ serverUrl: found }); el.querySelector("#s-url").value = found; }
    });
    el.querySelector("#s-padd").addEventListener("click", async () => {
      const name = el.querySelector("#s-pname").value.trim();
      if (!name) return;
      const r = await ctx.api.providerAdd(name);
      if (r.ok) this.loadProviders(ctx, el); else ctx.banner("Providers: server unreachable.");
    });
    el.querySelector("#s-auto").addEventListener("change", (e) => ctx.setAutostart(e.target.checked));
    const cats = ["timer", "reminder", "briefing", "proposal"];
    const nb = el.querySelector("#s-notif");
    for (const c of cats) {
      const lab = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.checked = (ctx.prefs().notify ?? {})[c] !== false;
      cb.addEventListener("change", () => ctx.setNotify(c, cb.checked));
      lab.append(cb, ` ${c}`);
      nb.appendChild(lab);
    }
    this.loadProviders(ctx, el);
  },
  async loadProviders(ctx, el) {
    const box = el.querySelector("#s-prov");
    const r = await ctx.api.providers();
    if (!r.ok) { box.textContent = "server unreachable."; return; }
    box.innerHTML = "";
    for (const pv of r.providers ?? []) {
      const d = document.createElement("div");
      d.className = "row";
      d.innerHTML = `<b>${pv.name}</b><button class="ghost">+ key</button>`;
      d.querySelector("button").addEventListener("click", async () => {
        const k = prompt("Paste key (never shown again):");
        if (k) await ctx.api.keyAdd(pv.id, k);
      });
      box.appendChild(d);
    }
  },
};
