import { ChronosClient, getStoredKey, KEY_STORAGE, BASE_STORAGE, HOSTS_STORAGE, SayResponse, needsProposal, decideStopVoid, stopPayload } from "./api";
import { orderHosts, rememberHost, withPort, DEFAULT_PORT } from "./discovery";
import { summarizeBreakdown, fmtDur } from "./breakdown";
import { renderProvidersSafe, ProviderEntry } from "./providers";

const app = document.getElementById("app")!;
const banner = document.getElementById("health-banner")!;
const voicebar = document.getElementById("voicebar")!;

function base(): string { return localStorage.getItem(BASE_STORAGE) || `http://127.0.0.1:${DEFAULT_PORT}`; }
function client(): ChronosClient | null {
  const k = getStoredKey();
  if (!k) return null;
  return new ChronosClient(base(), k);
}
function cached<T>(k: string): T | null {
  try { const v = localStorage.getItem("chronos.cache." + k); return v ? JSON.parse(v) as T : null; } catch { return null; }
}
function saveCache(k: string, v: unknown): void {
  try { localStorage.setItem("chronos.cache." + k, JSON.stringify(v)); } catch { /* ignore */ }
}

let serverUp = true;
async function healthGate(): Promise<void> {
  const c = client();
  if (!c) { banner.className = "down"; banner.textContent = "No instance key — set it in Settings."; serverUp = false; return; }
  const probe = await c.probe(3000);
  serverUp = probe === "ok";
  banner.className = serverUp ? "ok" : "down";
  banner.textContent = serverUp ? "Server reachable." : "Server down — cached read-only mode.";
}

function voiceBar(): void {
  voicebar.innerHTML = "";
  const inp = document.createElement("input");
  inp.placeholder = "Ask Chronos… (text)";
  inp.style.flex = "1";
  const btn = document.createElement("button");
  btn.textContent = "Send";
  const msg = document.createElement("span");
  msg.className = "muted";
  // Mic via MediaRecorder -> /api/voice only when available; else text-only note.
  const micSupported = typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices;
  const mic = document.createElement("button");
  mic.textContent = micSupported ? "Mic" : "Mic N/A (text-only)";
  mic.disabled = !micSupported;
  if (micSupported) {
    mic.onclick = async () => {
      msg.textContent = "Recording… click again to stop.";
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.start();
      mic.onclick = async () => {
        rec.stop();
        await new Promise((r) => (rec.onstop = r as () => void));
        stream.getTracks().forEach((t) => t.stop());
        const c = client();
        if (!c) { msg.textContent = "Set key first."; voiceBar(); return; }
        const fd = new FormData();
        fd.append("audio", new Blob(chunks, { type: rec.mimeType || "audio/webm" }), "clip.webm");
        const res = await fetch(c.base.replace(/\/+$/, "") + "/api/voice", {
          method: "POST", headers: { "X-Chronos-Key": getStoredKey()! }, body: fd,
        });
        const j = await res.json();
        inp.value = String(j.transcript || "");
        msg.textContent = "Transcribed — press Send.";
        voiceBar();
      };
    };
  }
  btn.onclick = async () => {
    const c = client();
    if (!c) { msg.textContent = "Set key first."; return; }
    const r = await c.say(inp.value);
    handleSay(r, msg);
  };
  voicebar.append(inp, btn, mic, msg);
}

function handleSay(r: SayResponse, msg: HTMLElement): void {
  if (needsProposal(r)) {
    msg.innerHTML = `Proposal ${r.proposal_id}: ${r.message || ""} <button id="acc">Accept</button> <button id="rej">Reject</button>`;
    const wsProto = base().startsWith("https") ? "wss" : "ws";
    const wsUrl = base().replace(/^http/, "ws") + "/ws?key=" + encodeURIComponent(getStoredKey()!);
    void wsProto;
    const sock = new WebSocket(wsUrl);
    sock.onopen = () => {
      document.getElementById("acc")!.onclick = () => sock.send(JSON.stringify({ accept: true, proposal_id: r.proposal_id }));
      document.getElementById("rej")!.onclick = () => sock.send(JSON.stringify({ reject: true, proposal_id: r.proposal_id }));
    };
    sock.onmessage = (e) => { msg.textContent = "Server: " + String(e.data).slice(0, 200); sock.close(); route(); };
  } else {
    msg.textContent = r.message || (r.committed ? "Committed." : "Done.");
    route();
  }
}

// ---- Views ----
async function planner(): Promise<void> {
  const c = client();
  const now = new Date();
  const y = now.getFullYear(), m = now.getMonth();
  const first = new Date(y, m, 1);
  const startDay = first.getDay();
  let html = `<h2>Planner</h2><div class="grid">`;
  for (let i = 0; i < 42; i++) {
    const d = new Date(y, m, 1 - startDay + i);
    const iso = d.toISOString().slice(0, 10);
    const today = iso === now.toISOString().slice(0, 10) ? " today" : "";
    html += `<div class="${today.trim()}">${d.getDate()}</div>`;
  }
  html += `</div><div id="agenda"></div><div id="tree"></div>`;
  app.innerHTML = html;
  const agenda = document.getElementById("agenda")!;
  const tree = document.getElementById("tree")!;
  if (!c) { agenda.textContent = "Set key in Settings."; return; }
  try {
    const from = new Date(y, m, 1).toISOString(), to = new Date(y, m + 1, 1).toISOString();
    const [events, nodes] = await Promise.all([
      c.get<unknown[]>(`/api/events?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
      c.get<Record<string, unknown>[]>(`/api/nodes`),
    ]);
    saveCache("events", events); saveCache("nodes", nodes);
    renderPlannerLists(events as { title?: string }[], nodes as { id: string; title?: string; kind?: string; parent_id?: string | null; tags?: string[] }[]);
  } catch {
    serverUp = false;
    const events = cached<unknown[]>("events") || [];
    const nodes = cached<Record<string, unknown>[]>("nodes") || [];
    agenda.innerHTML = `<p class="muted">Offline — cached read-only.</p>`;
    renderPlannerLists(events as { title?: string }[], nodes as { id: string; title?: string; kind?: string; parent_id?: string | null; tags?: string[] }[]);
  }
  function renderPlannerLists(events: { title?: string }[], nodes: { id: string; title?: string; kind?: string; parent_id?: string | null; tags?: string[] }[]): void {
    agenda.innerHTML = `<h3>Agenda (${events.length})</h3><ul>${events.map((e) => `<li>${e.title || "(event)"}</li>`).join("")}</ul>`;
    const projects = nodes.filter((n) => n.kind === "project");
    const byParent = new Map<string, typeof nodes>();
    for (const n of nodes) {
      const p = String(n.parent_id || "");
      if (!byParent.has(p)) byParent.set(p, []);
      byParent.get(p)!.push(n);
    }
    tree.innerHTML = `<h3>Projects → Tasks</h3>` + (projects.length === 0 ? `<p class="muted">No projects.</p>` : projects.map((p) =>
      `<div class="card"><b>${p.title || p.id}</b> ${(p.tags || []).map((t: string) => `<span class="muted">#${t}</span>`).join(" ")}<ul>${(byParent.get(String(p.id)) || []).map((t) => `<li>${t.title || t.id} ${(t.tags || []).map((x: string) => `#${x}`).join(" ")}</li>`).join("")}</ul></div>`).join(""));
  }
}

async function timerView(): Promise<void> {
  const c = client();
  app.innerHTML = `<h2>Timer + Log</h2>
    <div class="card"><label>Mode <select id="mode"><option value="stopwatch">stopwatch</option><option value="countdown">countdown</option><option value="pomodoro">pomodoro</option></select></label>
    <label>Target (min) <input id="target" type="number" value="25" min="1"/></label>
    <label>Label <input id="label" value="focus"/></label>
    <label>Node <input id="node" placeholder="node_id (optional)"/></label>
    <label><input id="strict" type="checkbox"/> strict</label>
    <button id="start">Start</button> <button id="stop">Stop (keep)</button> <button id="void">Void after attempt</button>
    <div id="live" class="muted"></div><div id="msg"></div></div>
    <div class="card"><h3>Presets</h3><div id="presets"></div><input id="pname" placeholder="name"/><input id="pfocus" type="number" value="25"/><button id="padd">Add preset</button></div>
    <div class="card"><h3>Breakdown drill</h3><input id="bnode" placeholder="node_id"/><button id="bgo">Load</button><div id="bout"></div></div>`;
  const live = document.getElementById("live")!;
  const msg = document.getElementById("msg")!;
  let tick: number | undefined;
  let stoppedOnce = false;
  async function refresh(): Promise<void> {
    if (!c) { live.textContent = "Set key in Settings."; return; }
    try {
      const s = await c.get<{ id?: string; started_at?: string; label?: string } | null>(`/api/timer`);
      if (s && s.id) {
        const t0 = new Date(String(s.started_at)).getTime();
        const tickFn = () => { live.textContent = `RUNNING ${s.label || ""} — ${Math.max(0, Math.floor((Date.now() - t0) / 1000))}s (incl. remote sessions)`; };
        tickFn();
        window.clearInterval(tick);
        tick = window.setInterval(tickFn, 1000);
      } else live.textContent = "No session running.";
    } catch { live.textContent = "Timer unavailable (offline)."; }
  }
  await refresh();
  window.onbeforeunload = () => window.clearInterval(tick);
  if (!c) return;
  try {
    const presets = await c.get<{ name: string; focus_minutes: number }[]>(`/api/timer/presets`);
    document.getElementById("presets")!.innerHTML = presets.map((p) => `<span class="muted">${p.name} ${p.focus_minutes}m</span>`).join(" · ");
  } catch { /* offline */ }
  document.getElementById("start")!.onclick = async () => {
    const mode = (document.getElementById("mode") as HTMLSelectElement).value;
    const mins = Number((document.getElementById("target") as HTMLInputElement).value || 25);
    const label = (document.getElementById("label") as HTMLInputElement).value;
    const node_id = (document.getElementById("node") as HTMLInputElement).value || undefined;
    const body: Record<string, unknown> = { label, mode, source: "web", target_ms: mode === "stopwatch" ? undefined : mins * 60000 };
    if (node_id) body.node_id = node_id;
    try { await c.post(`/api/timer/start`, body); stoppedOnce = false; msg.textContent = "Started."; }
    catch (e) { msg.textContent = String((e as Error).message).includes("conflict") ? "409: a timer is already running." : String(e); }
    await refresh();
  };
  const doStop = async (wantVoid: boolean) => {
    const doVoid = decideStopVoid(stoppedOnce || wantVoid, wantVoid);
    try {
      await c.post(`/api/timer/stop`, stopPayload("web", doVoid));
      msg.textContent = doVoid ? "Stopped + voided (elapsed discarded)." : "Stopped — time kept.";
      stoppedOnce = true;
    } catch (e) { msg.textContent = String(e); }
    await refresh();
  };
  document.getElementById("stop")!.onclick = () => void doStop(false);
  document.getElementById("void")!.onclick = () => {
    if (!window.confirm("Void this session? Elapsed time is discarded.")) return;
    void doStop(true);
  };
  document.getElementById("padd")!.onclick = async () => {
    const name = (document.getElementById("pname") as HTMLInputElement).value || "custom";
    const focus_minutes = Number((document.getElementById("pfocus") as HTMLInputElement).value || 25);
    await c.post(`/api/timer/presets`, { name, focus_minutes, break_minutes: 5, cycles: 4 });
    msg.textContent = "Preset added.";
  };
  document.getElementById("bgo")!.onclick = async () => {
    const node_id = (document.getElementById("bnode") as HTMLInputElement).value;
    if (!node_id) return;
    const to = new Date().toISOString();
    const from = new Date(Date.now() - 7 * 864e5).toISOString();
    const rows = await c.get<{ node_id: string; title: string; kind: string; total_ms: number }[]>(`/api/stats/breakdown?node_id=${encodeURIComponent(node_id)}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
    const s = summarizeBreakdown(rows);
    document.getElementById("bout")!.innerHTML = `<p>Total ${fmtDur(s.total_ms)}</p><ul>${s.rows.map((r) => `<li>${r.title} — ${fmtDur(r.total_ms)} (${r.pct.toFixed(1)}%)</li>`).join("")}</ul>`;
  };
}

async function briefing(): Promise<void> {
  const c = client();
  app.innerHTML = `<h2>Briefing</h2><div id="b"></div>`;
  const el = document.getElementById("b")!;
  if (!c) { el.textContent = "Set key in Settings."; return; }
  try {
    const today = new Date().toISOString().slice(0, 10);
    const b = await c.get<{ date: string; unallocated_tasks?: unknown[]; rollover?: unknown[]; due_reviews?: unknown[]; question?: string | null }>(`/api/briefing?date=${today}`);
    saveCache("briefing", b);
    el.innerHTML = `<div class="card"><b>${b.date}</b><ul><li>unallocated: ${(b.unallocated_tasks || []).length}</li><li>rollover: ${(b.rollover || []).length}</li><li>reviews: ${(b.due_reviews || []).length}</li></ul></div>` +
      (b.question ? `<div class="card"><b>Question</b><p>${b.question}</p></div>` : `<p class="muted">No question today.</p>`);
  } catch {
    const b = cached<{ date: string; question?: string | null }>("briefing");
    el.innerHTML = `<p class="muted">Offline — cached read-only.</p>` + (b ? `<div class="card">${b.date}: ${b.question || "no question"}</div>` : `<p>No cache.</p>`);
  }
}

async function stats(): Promise<void> {
  const c = client();
  app.innerHTML = `<h2>Stats</h2><div id="s"></div>`;
  const el = document.getElementById("s")!;
  if (!c) { el.textContent = "Set key in Settings."; return; }
  try {
    const s = await c.get<unknown>(`/api/stats`);
    saveCache("stats", s);
    el.innerHTML = `<pre>${JSON.stringify(s, null, 2)}</pre>`;
  } catch {
    const s = cached("stats");
    el.innerHTML = `<p class="muted">Offline — cached read-only.</p><pre>${JSON.stringify(s, null, 2)}</pre>`;
  }
}

async function settings(): Promise<void> {
  const remembered: string[] = JSON.parse(localStorage.getItem(HOSTS_STORAGE) || "[]");
  app.innerHTML = `<h2>Settings</h2>
    <div class="card"><h3>Server discovery</h3><p class="muted">Browsers cannot scan the LAN. Order: 127.0.0.1 first, then manual host, then remembered. Probe = /api/health (open) + saved key only, 3s timeout.</p>
    <label>Manual host <input id="host" placeholder="192.168.1.10"/></label>
    <label>Base URL <input id="sbase" style="width:320px" value="${base()}"/></label>
    <button id="probe">Probe ordered hosts</button><div id="hosts"></div></div>
    <div class="card"><h3>Auth</h3><label>Server URL <input id="base" style="width:320px" value="${base()}"/></label>
    <label>Instance key <input id="key" type="password" value="${getStoredKey() || ""}"/></label>
    <button id="save">Save</button><p class="muted">Key is stored in localStorage (XSS caveat: any script on this origin can read it — see README). Key is sent via X-Chronos-Key header and never logged.</p></div>
    <div class="card"><h3>Provider management</h3><div id="plist"></div>
    <input id="pgroup" placeholder="group (stt|text|embeddings)"/><input id="pname2" placeholder="name"/><input id="purl" placeholder="base_url"/><input id="pmodel" placeholder="model"/><button id="padd2">Add provider</button>
    <div><input id="kid" placeholder="provider id"/><input id="kval" placeholder="key value" type="password"/><button id="kadd">Add key (write-only)</button></div>
    <p class="muted">Keys are write-only: the list shows key_ids/key_count only, values are never displayed or stored client-side.</p></div>`;
  const renderHosts = (probed: { url: string; ok: boolean }[]) => {
    document.getElementById("hosts")!.innerHTML = probed.map((h) => `<div>${h.ok ? "✅" : "❌"} ${h.url}</div>`).join("");
  };
  document.getElementById("probe")!.onclick = async () => {
    const manual = (document.getElementById("host") as HTMLInputElement).value || null;
    const ordered = orderHosts(manual, remembered);
    const out: { url: string; ok: boolean }[] = [];
    for (const u of ordered) {
      try {
        const r = await fetch(u.replace(/\/+$/, "") + "/api/health", { signal: AbortSignal.timeout(3000) });
        out.push({ url: u, ok: r.ok });
      } catch { out.push({ url: u, ok: false }); }
    }
    renderHosts(out);
    const firstOk = out.find((h) => h.ok);
    if (firstOk) {
      (document.getElementById("sbase") as HTMLInputElement).value = firstOk.url;
      (document.getElementById("base") as HTMLInputElement).value = firstOk.url;
      localStorage.setItem(HOSTS_STORAGE, JSON.stringify(rememberHost(remembered, firstOk.url)));
    }
  };
  document.getElementById("save")!.onclick = () => {
    localStorage.setItem(BASE_STORAGE, (document.getElementById("base") as HTMLInputElement).value.trim());
    localStorage.setItem(KEY_STORAGE, (document.getElementById("key") as HTMLInputElement).value.trim());
    localStorage.setItem(HOSTS_STORAGE, JSON.stringify(rememberHost(remembered, (document.getElementById("base") as HTMLInputElement).value.trim())));
    void healthGate().then(route);
  };
  const c = client();
  const plist = document.getElementById("plist")!;
  async function loadProviders(): Promise<void> {
    if (!c) { plist.textContent = "Set key first."; return; }
    try {
      const g = await c.get<{ stt: ProviderEntry[]; text: ProviderEntry[]; embeddings: ProviderEntry[] }>(`/api/providers`);
      const all = [...(g.stt || []), ...(g.text || []), ...(g.embeddings || [])];
      plist.innerHTML = renderProvidersSafe(all) + all.map((e) =>
        `<div><span class="muted">${e.id}</span> <button data-up="${e.id}">↑</button> <button data-down="${e.id}">↓</button> <button data-del="${e.id}">delete</button></div>`).join("");
      plist.querySelectorAll("button").forEach((btn) => {
        const id = btn.getAttribute("data-del") || btn.getAttribute("data-up") || btn.getAttribute("data-down");
        if (!id) return;
        btn.onclick = async () => {
          if (btn.hasAttribute("data-del")) await c.del(`/api/providers/${id}`);
          else {
            const dir = btn.hasAttribute("data-up") ? -1 : 1;
            const idx = all.findIndex((e) => String(e.id) === String(id));
            await c.put(`/api/providers/${id}`, { position: (all[idx].position ?? idx) + dir });
          }
          await loadProviders();
        };
      });
    } catch { plist.textContent = "Providers unavailable (offline or no key)."; }
  }
  await loadProviders();
  document.getElementById("padd2")!.onclick = async () => {
    if (!c) return;
    await c.post(`/api/providers`, {
      group: (document.getElementById("pgroup") as HTMLInputElement).value,
      name: (document.getElementById("pname2") as HTMLInputElement).value,
      base_url: (document.getElementById("purl") as HTMLInputElement).value,
      model: (document.getElementById("pmodel") as HTMLInputElement).value || undefined,
    });
    await loadProviders();
  };
  document.getElementById("kadd")!.onclick = async () => {
    if (!c) return;
    const pid = (document.getElementById("kid") as HTMLInputElement).value;
    const kval = (document.getElementById("kval") as HTMLInputElement).value;
    await c.post(`/api/providers/${pid}/keys`, { key: kval });
    (document.getElementById("kval") as HTMLInputElement).value = "";
    await loadProviders();
  };
  void withPort;
}

function route(): void {
  const h = location.hash || "#/planner";
  if (h.startsWith("#/timer")) void timerView();
  else if (h.startsWith("#/briefing")) void briefing();
  else if (h.startsWith("#/stats")) void stats();
  else if (h.startsWith("#/settings")) void settings();
  else void planner();
}
window.addEventListener("hashchange", route);
voiceBar();
void healthGate().then(route);
