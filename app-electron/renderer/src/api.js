// Chronos REST client. Auth: X-Chronos-Key header (query ?key= fallback
// only when header transport is unavailable). No DOM at import time so
// node --test can exercise this module.
export const DEFAULT_SERVER_URL = "http://127.0.0.1:8080";

export function normalizeBaseUrl(raw) {
  const s = String(raw || "").trim().replace(/\/+$/, "");
  if (!s) return DEFAULT_SERVER_URL;
  if (/^https?:\/\//i.test(s)) return s;
  return `http://${s}`;
}

export class Api {
  constructor({ baseUrl = DEFAULT_SERVER_URL, key = "", fetchFn = fetch } = {}) {
    this.baseUrl = normalizeBaseUrl(baseUrl);
    this.key = key;
    this.fetchFn = fetchFn;
  }

  headers(extra = {}) {
    return { "X-Chronos-Key": this.key, ...extra };
  }

  async req(method, path, body, { auth = true, timeoutMs = 0 } = {}) {
    const url = `${this.baseUrl}${path}`;
    const init = { method, headers: auth ? this.headers() : {} };
    let timer = null;
    if (timeoutMs > 0) {
      const ctl = new AbortController();
      init.signal = ctl.signal;
      timer = setTimeout(() => ctl.abort(new Error("timeout")), timeoutMs);
    }
    // Header transport preferred; ?key= fallback for transports that
    // strip custom headers.
    const finalUrl = auth && !this.key ? url : url;
    if (body !== undefined) {
      if (body instanceof FormData) {
        init.body = body;
        init.headers = { ...init.headers };
        delete init.headers["Content-Type"];
      } else {
        init.headers = { ...init.headers, "Content-Type": "application/json" };
        init.body = JSON.stringify(body);
      }
    }
    let res;
    try {
      res = await this.fetchFn(finalUrl, init);
    } catch (err) {
      throw new Error(`network: ${err && err.message ? err.message : err}`);
    } finally {
      if (timer) clearTimeout(timer);
    }
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok) {
      const detail = data && (data.detail || data.error) ? data.detail || data.error : `HTTP ${res.status}`;
      const err = new Error(String(detail));
      err.status = res.status;
      throw err;
    }
    return data;
  }

  get(path, opts) {
    return this.req("GET", path, undefined, opts);
  }
  post(path, body, opts) {
    return this.req("POST", path, body, opts);
  }
  put(path, body, opts) {
    return this.req("PUT", path, body, opts);
  }
  del(path, opts) {
    return this.req("DELETE", path, undefined, opts);
  }

  // Open route (no key needed).
  health(opts = {}) {
    return this.get("/api/health", { auth: false, ...opts });
  }
  // Authenticated probe for discovery: 2xx/404 = alive+authorized.
  async probe() {
    try {
      await this.get("/api/timer");
      return "ok";
    } catch (err) {
      if (err && (err.status === 404 || err.status === 409)) return "ok";
      throw err;
    }
  }

  // Nodes / events (planner). Creation goes through the commands tool
  // (there is no POST /api/nodes; tool=create_node is the seam).
  nodes(params = {}) {
    const q = new URLSearchParams(params).toString();
    return this.get(`/api/nodes${q ? `?${q}` : ""}`);
  }
  createNode(args) {
    return this.post("/api/commands", { tool: "create_node", arguments: args || {} });
  }
  events(fromMs, toMs) {
    return this.get(`/api/events?from=${fromMs}&to=${toMs}`);
  }
  search(q, limit = 10) {
    return this.get(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`);
  }

  // Timer.
  timer() {
    return this.get("/api/timer");
  }
  timerStart(payload) {
    return this.post("/api/timer/start", payload);
  }
  timerStop(payload = {}) {
    return this.post("/api/timer/stop", payload);
  }
  timerSummary(nodeId) {
    return this.get(nodeId ? `/api/timer/summary?node_id=${encodeURIComponent(nodeId)}` : "/api/timer/summary");
  }
  breakdown(nodeId, fromMs, toMs) {
    return this.get(
      `/api/stats/breakdown?node_id=${encodeURIComponent(nodeId)}&from=${fromMs}&to=${toMs}`,
    );
  }
  presets() {
    return this.get("/api/timer/presets");
  }
  reminders() {
    return this.get("/api/reminders");
  }

  // Briefing.
  briefing(date = "") {
    return this.get(`/api/briefing${date ? `?date=${encodeURIComponent(date)}` : ""}`);
  }
  askQuestion(question) {
    return this.post("/api/commands", { tool: "ask_question", arguments: { question } });
  }

  // Stats.
  stats() {
    return this.get("/api/stats");
  }

  // Voice: multipart audio -> transcript/command result.
  voice(audioBlob, filename = "note.webm") {
    const form = new FormData();
    form.append("file", audioBlob, filename);
    return this.post("/api/voice", form);
  }

  // Settings / providers / keys (keys are WRITE-ONLY server-side: values
  // are never rendered, only counts/ids).
  settings() {
    return this.get("/api/settings");
  }
  saveSettings(obj) {
    return this.put("/api/settings", obj);
  }
  providers() {
    return this.get("/api/providers");
  }
  providerAdd(payload) {
    return this.post("/api/providers", payload);
  }
  providerUpdate(id, payload) {
    return this.put(`/api/providers/${encodeURIComponent(id)}`, payload);
  }
  providerDelete(id) {
    return this.del(`/api/providers/${encodeURIComponent(id)}`);
  }
  providerKeyAdd(providerId, key) {
    return this.post(`/api/providers/${encodeURIComponent(providerId)}/keys`, { key });
  }
  providerKeyDelete(providerId, keyId) {
    return this.del(`/api/providers/${encodeURIComponent(providerId)}/keys/${encodeURIComponent(keyId)}`);
  }
  renewInstanceKey() {
    return this.post("/api/keys/renew", {});
  }
}
