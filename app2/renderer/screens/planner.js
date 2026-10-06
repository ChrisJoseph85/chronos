// Screen contract: window.Chronos.screens.<name> = {init(el, ctx), onShow?}
// ctx = {api, notify(title,body,kind), aiRow(el,screen), prefs(), banner(msg?)}
window.Chronos = window.Chronos || { screens: {} };

window.Chronos.screens.planner = {
  init(el, ctx) {
    el.innerHTML = `<div class="cols"><div class="card"><h3>Calendar</h3><div class="cal" id="p-cal"></div></div>
      <div class="card"><h3>Nodes</h3><div class="tree" id="p-tree"></div><div id="p-tags"></div></div></div>
      <div class="ai-mount"></div>`;
    const cal = el.querySelector("#p-cal");
    const now = new Date();
    const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    for (let d = 1; d <= days; d++) {
      const c = document.createElement("div");
      c.textContent = d;
      if (d === now.getDate()) c.classList.add("sel");
      c.addEventListener("click", async () => {
        cal.querySelectorAll("div").forEach((x) => x.classList.remove("sel"));
        c.classList.add("sel");
        await this.loadDay(ctx, el, d);
      });
      cal.appendChild(c);
    }
    this.loadDay(ctx, el, now.getDate());
  },
  async loadDay(ctx, el, day) {
    const tree = el.querySelector("#p-tree");
    const tags = el.querySelector("#p-tags");
    const r = await ctx.api.listNodes(day);
    if (!r.ok) { ctx.banner("Planner: server unreachable — showing cached view."); return; }
    ctx.banner(null);
    tree.innerHTML = "";
    const seen = new Set();
    for (const n of r.nodes) {
      const d = document.createElement("div");
      d.textContent = n.title;
      d.addEventListener("click", () => ctx.go("timer", { node: n.id }));
      tree.appendChild(d);
      (n.tags || []).forEach((t) => seen.add(t));
    }
    tags.innerHTML = "";
    for (const t of seen) {
      const s = document.createElement("span");
      s.className = "chip"; s.textContent = t;
      s.addEventListener("click", () => s.classList.toggle("on"));
      tags.appendChild(s);
    }
  },
};
