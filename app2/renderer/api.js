// Lazy fetch wrapper. NEVER called at import. Every method try/catch → {ok:false}.
window.ChronosApi = (() => {
  const prefs = () => {
    try { return JSON.parse(localStorage.getItem("chronos-prefs") ?? "{}"); } catch { return {}; }
  };
  async function req(path, opts = {}) {
    const p = prefs();
    if (!p.serverUrl) return { ok: false, down: true };
    try {
      const r = await fetch(p.serverUrl + path, {
        ...opts,
        headers: { ...(opts.headers ?? {}), ...(p.key ? { Authorization: `Bearer ${p.key}` } : {}) },
      });
      if (!r.ok) return { ok: false, status: r.status };
      return { ok: true, ...(await r.json().catch(() => ({}))) };
    } catch { return { ok: false, down: true }; }
  }
  const j = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return {
    prefs,
    health: () => req("/api/health"),
    listNodes: (day) => req(`/api/nodes?day=${day ?? ""}`),
    createNode: (title) => req("/api/nodes", j({ title })),
    timerStart: (mode, strict) => req("/api/timer/start", j({ mode, strict })),
    timerStop: (voided) => req("/api/timer/stop", j({ void: !!voided })),
    breakdown: () => req("/api/stats/breakdown"),
    briefing: () => req("/api/briefing"),
    ask: (q) => req("/api/briefing/ask", j({ question: q })),
    stats: () => req("/api/stats"),
    providers: () => req("/api/providers"),
    providersReorder: (ids) => req("/api/providers/reorder", j({ ids })),
    providerAdd: (name) => req("/api/providers", j({ name })),
    keyAdd: (id, key) => req(`/api/providers/${id}/keys`, j({ key })),
    keyDelete: (id, kid) => req(`/api/providers/${id}/keys/${kid}`, { method: "DELETE" }),
    voice: (text) => req("/api/voice", j({ text })),
  };
})();
