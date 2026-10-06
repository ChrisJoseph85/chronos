window.Chronos.screens.briefing = {
  init(el, ctx) {
    el.innerHTML = `<div class="card"><h3>Briefing</h3><div id="b-text">Loading…</div></div>
      <div class="card"><h3>Ask</h3><div class="row"><input id="b-q" placeholder="Question…" style="flex:1">
      <button id="b-ask">Ask</button></div><div id="b-a"></div></div><div class="ai-mount"></div>`;
    this.load(ctx, el);
    const ask = async () => {
      const q = el.querySelector("#b-q").value;
      const r = await ctx.api.ask(q);
      el.querySelector("#b-a").textContent = r.ok ? (r.answer ?? "done") : "server unreachable.";
      if (r.ok) ctx.notify("Briefing answer ready", q.slice(0, 80), "briefing");
      else ctx.banner("Briefing: server unreachable.");
    };
    el.querySelector("#b-ask").addEventListener("click", ask);
    el.querySelector("#b-q").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
  },
  async load(ctx, el) {
    const r = await ctx.api.briefing();
    el.querySelector("#b-text").textContent = r.ok ? (r.briefing ?? "empty") : "server unreachable — no briefing.";
  },
};
