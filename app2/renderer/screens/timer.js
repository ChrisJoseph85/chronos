window.Chronos.screens.timer = {
  mode: "countdown",
  init(el, ctx) {
    this.ctx = ctx;
    el.innerHTML = `<div class="card"><h3>Timer</h3><div class="row" id="t-modes">
        <button data-m="countdown">Countdown</button><button data-m="stopwatch">Stopwatch</button>
        <button data-m="pomodoro">Pomodoro</button>
        <label><input type="checkbox" id="t-strict"> Strict</label></div>
      <div class="row"><button id="t-start">Start</button><button id="t-stop">Stop</button>
        <button id="t-void" class="ghost">Void</button><span id="t-state">idle</span></div></div>
      <div class="card"><h3>Breakdown</h3><div id="t-drill"></div></div>
      <div class="ai-mount"></div>`;
    el.querySelectorAll("#t-modes button").forEach((b) => b.addEventListener("click", () => {
      this.mode = b.dataset.m;
      el.querySelectorAll("#t-modes button").forEach((x) => x.classList.toggle("active", x === b));
    }));
    el.querySelector("#t-start").addEventListener("click", () => this.start(el));
    el.querySelector("#t-stop").addEventListener("click", () => this.stop(el, false));
    el.querySelector("#t-void").addEventListener("click", () => this.stop(el, true));
    this.drill(ctx, el);
  },
  async start(el) {
    const r = await this.ctx.api.timerStart(this.mode, el.querySelector("#t-strict").checked);
    el.querySelector("#t-state").textContent = r.ok ? "running" : "server down";
    if (r.ok) this.ctx.notify("Timer started", this.mode, "timer");
    else this.ctx.banner("Timer: server unreachable.");
  },
  async stop(el, voided) {
    const r = await this.ctx.api.timerStop(voided);
    el.querySelector("#t-state").textContent = r.ok ? (voided ? "voided" : "stopped") : "server down";
    if (r.ok) this.ctx.notify(voided ? "Session voided" : "Timer stopped", this.mode, "timer");
  },
  async drill(ctx, el) {
    const box = el.querySelector("#t-drill");
    const r = await ctx.api.breakdown();
    if (!r.ok) return;
    box.innerHTML = "";
    for (const row of r.rows) {
      const b = document.createElement("button");
      b.className = "ghost"; b.textContent = `${row.label}: ${row.total}`;
      b.addEventListener("click", () => alert(JSON.stringify(row.detail ?? row)));
      box.appendChild(b);
    }
  },
};
