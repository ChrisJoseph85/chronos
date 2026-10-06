// Boot: sidebar nav, screen switching, AI-row mount, prefs, banner.
// Runs AFTER all screen scripts. No network at boot.
(() => {
  const prefs = () => {
    try { return JSON.parse(localStorage.getItem("chronos-prefs") ?? "{}"); } catch { return {}; }
  };
  const savePrefs = (patch) => {
    localStorage.setItem("chronos-prefs", JSON.stringify({ ...prefs(), ...patch }));
  };
  const banner = (msg) => {
    const b = document.getElementById("banner");
    if (!msg) { b.classList.add("hidden"); document.body.classList.remove("has-banner"); return; }
    b.textContent = msg; b.classList.remove("hidden"); document.body.classList.add("has-banner");
  };
  const ctx = {
    api: window.ChronosApi,
    notify: (t, body, kind) => window.chronos?.notify(t, body, kind),
    aiRow: (host, screen) => window.ChronosAiRow.mount(host, ctx, screen),
    prefs, savePrefs, banner,
    autostart: (prefs().autostart ?? false),
    setAutostart: (on) => savePrefs({ autostart: on }),
    setNotify: (cat, on) => savePrefs({ notify: { ...(prefs().notify ?? {}), [cat]: on } }),
    go: (name) => show(name),
  };
  const order = ["planner", "timer", "briefing", "stats", "settings"];
  const mounted = {};
  function show(name) {
    const host = document.getElementById("screen");
    host.innerHTML = "";
    document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("active", b.dataset.screen === name));
    const s = window.Chronos.screens[name];
    if (!s) { host.textContent = "missing screen: " + name; return; }
    s.init(host, ctx);
    mounted[name] = true;
    host.querySelectorAll(".ai-mount").forEach((m) => ctx.aiRow(m, name));
    if (s.onShow) s.onShow(host, ctx);
  }
  document.querySelectorAll(".nav").forEach((b) => b.addEventListener("click", () => show(b.dataset.screen)));
  document.getElementById("collapse").addEventListener("click", () => {
    const sb = document.getElementById("sidebar");
    sb.classList.toggle("collapsed");
    savePrefs({ sidebar: sb.classList.contains("collapsed") ? "icons" : "full" });
  });
  if ((prefs().sidebar ?? "full") === "icons") document.getElementById("sidebar").classList.add("collapsed");
  // Splitter drag (persist width %).
  const split = document.getElementById("splitter");
  split.addEventListener("mousedown", () => {
    const move = (e) => {
      const w = Math.min(280, Math.max(56, e.clientX));
      document.getElementById("sidebar").style.width = w + "px";
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      savePrefs({ panels: { side: document.getElementById("sidebar").style.width } });
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });
  const saved = prefs().panels?.side;
  if (saved) document.getElementById("sidebar").style.width = saved;
  show("planner");
  window.ChronosBoot = { show, ctx, order };
})();
