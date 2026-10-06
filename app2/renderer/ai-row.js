// AI row mounted on EVERY screen: mic button + text input.
window.ChronosAiRow = {
  mount(host, ctx, screen) {
    host.innerHTML = `<div class="ai-row"><button class="mic" title="Voice">🎤</button>
      <input placeholder="Ask AI…" aria-label="Ask AI"><button class="send">➤</button></div>
      <div class="ai-out"></div>`;
    const input = host.querySelector("input");
    const out = host.querySelector(".ai-out");
    const send = async (text) => {
      if (!text.trim()) return;
      const r = await ctx.api.ask(`[${screen}] ${text}`);
      out.textContent = r.ok ? (r.answer ?? "done") : "server unreachable — AI unavailable.";
      if (!r.ok) {
        host.querySelector(".mic").disabled = true;
        ctx.banner("AI: server unreachable.");
      }
    };
    host.querySelector(".send").addEventListener("click", () => send(input.value));
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(input.value); });
    host.querySelector(".mic").addEventListener("click", async () => {
      const r = await ctx.api.voice("");
      out.textContent = r.ok ? "listening… (server transcribes)" : "mic unavailable — server unreachable.";
      if (!r.ok) ctx.banner("Voice: server unreachable.");
    });
  },
};
