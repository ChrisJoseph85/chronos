window.Chronos.screens.stats = {
  init(el, ctx) {
    el.innerHTML = `<div class="card"><h3>Stats</h3><canvas id="s-cv" width="600" height="220"></canvas></div>
      <div class="card"><h3>Breakdown</h3><div id="s-rows"></div></div><div class="ai-mount"></div>`;
    this.load(ctx, el);
  },
  async load(ctx, el) {
    const r = await ctx.api.breakdown();
    const box = el.querySelector("#s-rows");
    if (!r.ok) { box.textContent = "server unreachable."; return; }
    const rows = r.rows ?? [];
    box.innerHTML = rows.map((x) => `<div>${x.label}: ${x.total}</div>`).join("");
    const cv = el.querySelector("#s-cv");
    if (!cv.getContext) return;
    const c = cv.getContext("2d");
    const max = Math.max(1, ...rows.map((x) => Number(x.total) || 0));
    rows.forEach((x, i) => {
      const h = 180 * ((Number(x.total) || 0) / max);
      c.fillStyle = "#3b4a6b";
      c.fillRect(20 + i * 60, 200 - h, 40, h);
    });
  },
};
