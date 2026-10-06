// Chronos Electron renderer (vanilla, no framework).
// Loaded from DISK via main.loadFile — no web server, no remote code.
// Secrets (server URL, instance key) live in localStorage only.
import { Api, normalizeBaseUrl, DEFAULT_SERVER_URL } from "./api.js";
import {
  formatDuration, formatMsLong, buildNodeTree, collectTags, monthCells,
  dayRangeMs, monthRangeMs, scaleBars, eventsByDay, clampFraction,
} from "./logic.js";
import { candidates, scan, DEFAULT_DISCOVERY_PORT } from "../../main/discovery.js";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- config (localStorage ONLY — never userData JSON, never main) ----------
const CFG_KEY = "chronos.cfg.v1";
function loadCfg() {
  let c = {};
  try { c = JSON.parse(localStorage.getItem(CFG_KEY) || "{}"); } catch { c = {}; }
  return {
    serverUrl: c.serverUrl || DEFAULT_SERVER_URL,
    key: c.key || "",
    discoveryPort: c.discoveryPort || DEFAULT_DISCOVERY_PORT,
    strict: c.strict !== false,
    notif: { timer: true, reminder: true, briefing: false, proposal: false, ...(c.notif || {}) },
    view: c.view || "planner",
    ...c,
  };
}
let cfg = loadCfg();
function saveCfg() { localStorage.setItem(CFG_KEY, JSON.stringify(cfg)); }

const api = () => new Api({ baseUrl: cfg.serverUrl, key: cfg.key });

// ---------- userData-backed store via preload (fallback: localStorage) ----------
const bridge = window.chronos || null;
const udStore = {
  async get(k) {
    if (bridge) { try { return await bridge.storeGet(k); } catch { /* fall through */ } }
    try { return JSON.parse(localStorage.getItem("chronos.ud." + k) ?? "null"); } catch { return null; }
  },
  async set(k, v) {
    if (bridge) { try { await bridge.storeSet(k, v); return; } catch { /* fall through */ } }
    localStorage.setItem("chronos.ud." + k, JSON.stringify(v));
  },
  async panel(k, f) {
    if (bridge) { try { return await bridge.panelSet(k, f); } catch { /* fall through */ } }
    const all = JSON.parse(localStorage.getItem("chronos.ud.panels") || "{}");
    all[k] = f; localStorage.setItem("chronos.ud.panels", JSON.stringify(all));
    return f;
  },
};

// ---------- health ----------
let serverUp = false;
let apiClient = api();
function setBanner() {
  const b = $("#health-banner");
  if (serverUp) {
    b.className = "health ok hidden";
    document.body.classList.remove("has-banner");
  } else {
    b.className = "health";
    b.textContent = `⚠ Server unreachable at ${cfg.serverUrl} — check Settings. Voice + actions disabled until reconnect.`;
    document.body.classList.add("has-banner");
  }
  const mic = $("#airow .mic");
  if (mic) { mic.disabled = !serverUp; mic.title = serverUp ? "Voice note" : "Server offline"; }
}
async function checkHealth() {
  try {
    await apiClient.health({ timeoutMs: 6000 });
    serverUp = true;
  } catch { serverUp = false; }
  setBanner();
  return serverUp;
}

// ---------- notifications ----------
const seenReminders = new Set();
async function notify(category, title, body) {
  if (!cfg.notif[category]) return;
  try {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") await Notification.requestPermission();
    if (Notification.permission === "granted") new Notification(title, { body: String(body || "").slice(0, 200) });
  } catch { /* headless / denied -> ignore */ }
}
async function pollReminders() {
  if (!serverUp || !cfg.notif.reminder) return;
  try {
    const items = await apiClient.reminders();
    for (const r of items || []) {
      if (r.id && !seenReminders.has(r.id)) {
        seenReminders.add(r.id);
        notify("reminder", "Reminder", r.title || r.text || r.id);
      }
    }
  } catch { /* next tick */ }
}

// ---------- toast ----------
function toast(msg, kind = "") {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
  t.className = `toast ${kind}`;
  t.textContent = msg;
  clearTimeout(t._h);
  t._h = setTimeout(() => t.remove(), 3500);
}

// ---------- splitter ----------
async function makeSplitter(el, key, paneA, paneB) {
  const saved = clampFraction(await udStore.get("panels").then((p) => (p && p[key]) || 0.5));
  const apply = (f) => {
    paneA.style.flex = `1 1 ${f * 100}%`;
    paneB.style.flex = `1 1 ${(1 - f) * 100}%`;
  };
  apply(saved);
  let frac = saved;
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const horiz = window.innerWidth <= 760;
    const move = (ev) => {
      const r = el.parentElement.getBoundingClientRect();
      frac = horiz
        ? clampFraction((ev.clientY - r.top) / r.height)
        : clampFraction((ev.clientX - r.left) / r.width);
      apply(frac);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      udStore.panel(key, frac);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
}
const splitDiv = (key) => { const d = document.createElement("div"); d.className = "splitter"; d.dataset.key = key; return d; };

// ---------- AI row (every screen: mic -> /api/voice, text -> contextual) ----------
let mediaRecorder = null, audioChunks = [], recordingCtx = null;
function mountAiRow(ctxLabel, onText, onVoiceText) {
  $("#airow")?.remove();
  const bar = document.createElement("div");
  bar.id = "airow";
  const mic = document.createElement("button");
  mic.className = "btn mic"; mic.textContent = "🎤"; mic.title = "Voice note";
  mic.disabled = !serverUp;
  const input = document.createElement("input");
  input.type = "text"; input.placeholder = `Ask / add — ${ctxLabel} (Enter to send)`;
  input.setAttribute("aria-label", "AI input");
  const send = document.createElement("button");
  send.className = "btn primary"; send.textContent = "Send";
  const status = document.createElement("span");
  status.className = "muted small";

  const doText = async () => {
    const v = input.value.trim();
    if (!v) return;
    if (!serverUp) { toast("Server offline", "bad"); return; }
    input.value = "";
    status.textContent = "…";
    try { await onText(v); status.textContent = ""; }
    catch (err) { status.textContent = ""; toast(`Send failed: ${err.message}`, "bad"); }
  };
  send.onclick = doText;
  input.onkeydown = (e) => { if (e.key === "Enter") doText(); };

  mic.onclick = async () => {
    if (mediaRecorder) { mediaRecorder.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      recordingCtx = { onVoiceText, status };
      mediaRecorder.ondataavailable = (e) => { if (e.data.size) audioChunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        const rec = mediaRecorder; mediaRecorder = null;
        mic.classList.remove("live"); mic.textContent = "🎤";
        rec.stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(audioChunks, { type: rec.mimeType || "audio/webm" });
        status.textContent = "transcribing…";
        try {
          const res = await apiClient.voice(blob);
          const text = res && (res.text || res.transcript || res.result || JSON.stringify(res));
          status.textContent = "";
          toast(`Voice: ${String(text).slice(0, 120)}`);
          await recordingCtx.onVoiceText(String(text || ""));
        } catch (err) { status.textContent = ""; toast(`Voice failed: ${err.message}`, "bad"); }
      };
      mediaRecorder.start();
      mic.classList.add("live"); mic.textContent = "⏹";
    } catch { toast("Microphone unavailable", "bad"); }
  };

  bar.append(mic, input, send, status);
  document.body.appendChild(bar);
  if (bridge) document.body.classList.toggle("sb-collapsed", $("#sidebar").classList.contains("collapsed"));
}

// ---------- shared: node options datalist ----------
async function nodeOptions() {
  try { return (await apiClient.nodes()) || []; }
  catch { return []; }
}
function nodeSelect(id, nodes, onchange) {
  const sel = document.createElement("select");
  sel.innerHTML = `<option value="">— no node —</option>` +
    nodes.map((n) => `<option value="${esc(n.id)}">${esc(n.title || n.id)}</option>`).join("");
  if (id) sel.value = id;
  if (onchange) sel.onchange = () => onchange(sel.value);
  return sel;
}

// ============================ VIEWS ============================
const view = () => $("#view");
let cleanup = () => {};

// ----- Planner: calendar + node tree + tags -----
async function renderPlanner() {
  const v = view(); v.innerHTML = "";
  const head = document.createElement("div"); head.className = "view-head";
  const now = new Date();
  let Y = now.getFullYear(), M = now.getMonth() + 1, selDay = now.getDate();
  let nodes = [], tags = [], tagFilter = "", selectedId = null;

  const panes = document.createElement("div"); panes.className = "panes";
  const pCal = document.createElement("div"); pCal.className = "pane";
  const pTree = document.createElement("div"); pTree.className = "pane";
  const pDet = document.createElement("div"); pDet.className = "pane";
  const s1 = splitDiv("planner-a"), s2 = splitDiv("planner-b");
  panes.append(pCal, s1, pTree, s2, pDet);
  v.append(head, panes);
  makeSplitter(s1, "planner-a", pCal, pTree);
  makeSplitter(s2, "planner-b", pTree, pDet);

  const headHtml = () => {
    head.innerHTML = `<h2>Planner</h2><div class="spacer"></div>
      <button class="btn" data-act="prev">‹</button>
      <strong>${Y}-${String(M).padStart(2, "0")}</strong>
      <button class="btn" data-act="next">›</button>
      <button class="btn" data-act="reload">Reload</button>`;
    head.querySelector('[data-act="prev"]').onclick = () => { M--; if (M < 1) { M = 12; Y--; } draw(); };
    head.querySelector('[data-act="next"]').onclick = () => { M++; if (M > 12) { M = 1; Y++; } draw(); };
    head.querySelector('[data-act="reload"]').onclick = draw;
  };

  async function draw() {
    headHtml();
    nodes = await nodeOptions();
    tags = collectTags(nodes);
    let counts = new Map();
    try {
      const [from, to] = monthRangeMs(Y, M);
      counts = eventsByDay(await apiClient.events(from, to));
    } catch { /* offline: bare calendar */ }
    // calendar
    const todayK = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${now.getDate()}`;
    let html = `<table class="cal"><tr><th>Mo<th>Tu<th>We<th>Th<th>Fr<th>Sa<th>Su</tr><tr>`;
    let col = 0;
    for (const d of monthCells(Y, M, 1)) {
      if (col % 7 === 0 && col > 0) html += "</tr><tr>";
      col++;
      if (!d) { html += "<td></td>"; continue; }
      const k = `${Y}-${String(M).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const n = counts.get(k) || 0;
      html += `<td data-day="${d}" class="${k === todayK ? "today" : ""} ${d === selDay ? "sel" : ""}">${d}${n ? ` <span class="dot">${n}</span>` : ""}</td>`;
    }
    html += "</tr></table>";
    pCal.innerHTML = `<h3>Calendar</h3>${html}`;
    pCal.querySelectorAll("td[data-day]").forEach((td) => {
      td.onclick = () => { selDay = Number(td.dataset.day); draw(); };
    });
    // tree + tags
    const tree = buildNodeTree(nodes.filter((n) => !tagFilter || (JSON.stringify(n.tags || "") + (n.title || "")).includes(tagFilter)));
    const renderTree = (list) => `<ul class="tree">${list.map((n) =>
      `<li><span class="node ${n.id === selectedId ? "sel" : ""}" data-id="${esc(n.id)}"><span class="kind">${esc(n.kind || "node")}</span>${esc(n.title || n.id)}</span>${n.children.length ? renderTree(n.children) : ""}</li>`).join("")}</ul>`;
    pTree.innerHTML = `<h3>Nodes</h3>
      <div class="row"><select id="tagf"><option value="">all tags</option>${tags.map((t) => `<option ${t === tagFilter ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></div>
      ${renderTree(tree)}`;
    pTree.querySelector("#tagf").onchange = (e) => { tagFilter = e.target.value; draw(); };
    pTree.querySelectorAll(".node").forEach((el) => { el.onclick = () => { selectedId = el.dataset.id; draw(); }; });
    // detail
    const sel = nodes.find((n) => n.id === selectedId);
    let det = `<h3>Detail</h3><p class="muted">Select a node. Day: ${Y}-${M}-${selDay}</p>`;
    if (sel) {
      det = `<h3>${esc(sel.title || sel.id)}</h3>
        <p><span class="kind">${esc(sel.kind || "node")}</span><span class="muted small">${esc(sel.id)}</span></p>
        ${sel.notes ? `<p>${esc(sel.notes)}</p>` : ""}
        <div class="row"><button class="btn" id="sumBtn">Timer summary</button>
        <button class="btn" id="toTimer">Open in Timer</button></div><div id="sumOut"></div>`;
    }
    pDet.innerHTML = det;
    if (sel) {
      pDet.querySelector("#sumBtn").onclick = async () => {
        try {
          const s = await apiClient.timerSummary(sel.id);
          pDet.querySelector("#sumOut").innerHTML =
            `<p>Node: <strong>${formatMsLong(s.node_total_ms)}</strong><br>Descendants: <strong>${formatMsLong(s.descendant_total_ms)}</strong><br>Project: <strong>${formatMsLong(s.project_total_ms)}</strong></p>`;
        } catch (err) { toast(`Summary failed: ${err.message}`, "bad"); }
      };
      pDet.querySelector("#toTimer").onclick = () => switchView("timer", { nodeId: sel.id });
    }
  }

  mountAiRow("planner — text creates a node", async (text) => {
    const res = await apiClient.createNode({ title: text, parent_id: selectedId || undefined });
    toast("Node created"); draw();
    return res;
  }, async (text) => {
    if (!text) return;
    await apiClient.createNode({ title: text, parent_id: selectedId || undefined });
    toast("Voice node created"); draw();
  });
  await draw();
}

// ----- Timer+Log: 3 modes, strict toggle, breakdown drill -----
async function renderTimer(preset = {}) {
  const v = view(); v.innerHTML = "";
  const panes = document.createElement("div"); panes.className = "panes";
  const pCtl = document.createElement("div"); pCtl.className = "pane";
  const pLog = document.createElement("div"); pLog.className = "pane";
  const sp = splitDiv("timer-a");
  panes.append(pCtl, sp, pLog);
  v.append(panes);
  makeSplitter(sp, "timer-a", pCtl, pLog);

  const nodes = await nodeOptions();
  let mode = "stopwatch", nodeId = preset.nodeId || "", running = null, tickH = null;

  const head = document.createElement("div"); head.className = "view-head";
  head.innerHTML = `<h2>Timer + Log</h2><div class="spacer"></div>
    <label class="small"><input type="checkbox" id="strict" ${cfg.strict ? "checked" : ""}> Strict shield</label>`;
  v.prepend(head);
  head.querySelector("#strict").onchange = (e) => { cfg.strict = e.target.checked; saveCfg(); drawCtl(); };

  async function refresh() {
    try { running = await apiClient.timer(); } catch { running = null; }
    drawCtl();
  }

  function drawCtl() {
    const strict = cfg.strict;
    pCtl.innerHTML = `<h3>Control</h3>
      <div class="row" role="tablist">
        ${["stopwatch", "countdown", "pomodoro"].map((m) => `<button class="btn ${m === mode ? "primary" : ""}" data-mode="${m}">${m}</button>`).join("")}
      </div>
      <div class="row" style="margin-top:8px"><label>Label <input type="text" id="tLabel" value="timer" style="width:130px"></label></div>
      <div class="row" style="margin-top:8px"><label>Node </label><span id="nodePick"></span></div>
      ${mode === "countdown" ? `<div class="row" style="margin-top:8px"><label>Minutes <input type="number" id="tMin" value="25" min="1" style="width:70px"></label></div>` : ""}
      ${mode === "pomodoro" ? `<div class="row" style="margin-top:8px"><label>Focus <input type="number" id="tF" value="25" style="width:60px"></label> Break <input type="number" id="tB" value="5" style="width:60px"></label> Cycles <input type="number" id="tC" value="4" style="width:60px"></label></div>` : ""}
      <div class="row" style="margin-top:10px" id="tBtns"></div>
      <div id="tLive" style="font-size:28px;margin-top:8px">—</div>
      <p class="muted small">Strict shield ${strict ? "ON — stop needs confirm, discard voids elapsed (audited)" : "off — plain stop"}.</p>`;
    pCtl.querySelectorAll("[data-mode]").forEach((b) => { b.onclick = () => { mode = b.dataset.mode; drawCtl(); }; });
    pCtl.querySelector("#nodePick").append(nodeSelect(nodeId, nodes, (x) => { nodeId = x; }));
    const btns = pCtl.querySelector("#tBtns");
    if (!running) {
      const s = document.createElement("button"); s.className = "btn primary"; s.textContent = "Start";
      s.onclick = startTimer; s.disabled = !serverUp; btns.append(s);
    } else {
      const stop = document.createElement("button"); stop.className = "btn"; stop.textContent = "Stop & save";
      stop.onclick = () => stopTimer(false); btns.append(stop);
      if (strict) {
        const d = document.createElement("button"); d.className = "btn danger"; d.textContent = "Discard (void)";
        d.onclick = () => stopTimer(true); btns.append(d);
      }
    }
    tick();
  }

  async function startTimer() {
    const label = pCtl.querySelector("#tLabel").value || "timer";
    const payload = { mode, label, node_id: nodeId || undefined, source: "electron" };
    if (mode === "countdown") payload.target_ms = (Number(pCtl.querySelector("#tMin").value) || 25) * 60000;
    if (mode === "pomodoro") {
      payload.target_ms = (Number(pCtl.querySelector("#tF").value) || 25) * 60000;
      payload.phase = "focus";
    }
    try {
      running = await apiClient.timerStart(payload);
      notify("timer", "Timer started", `${mode} — ${label}`);
      drawCtl();
    } catch (err) { toast(`Start failed: ${err.message}`, "bad"); }
  }
  async function stopTimer(voidIt) {
    if (cfg.strict && !voidIt && !confirm("Stop and save this session?")) return;
    if (voidIt && !confirm("Discard elapsed time? (void, audited)")) return;
    try {
      const res = await apiClient.timerStop({ void: voidIt, source: "electron" });
      running = null;
      notify("timer", voidIt ? "Timer discarded" : "Timer stopped",
        formatMsLong((res.ended_at || Date.now()) - (res.started_at || Date.now())));
      drawCtl(); drawLog();
    } catch (err) { toast(`Stop failed: ${err.message}`, "bad"); }
  }
  function tick() {
    const el = pCtl.querySelector("#tLive");
    if (!el) return;
    if (!running) { el.textContent = "—"; return; }
    const elapsed = Date.now() - Number(running.started_at || Date.now());
    el.textContent = formatDuration(elapsed) + (running.target_ms ? ` / ${formatDuration(running.target_ms)}` : "");
  }

  async function drawLog() {
    pLog.innerHTML = `<h3>Log & breakdown drill</h3><div class="row"><span id="rootPick"></span>
      <button class="btn" id="bLoad">Load today</button></div><div id="bOut"></div><div id="sumOut"></div>`;
    pLog.querySelector("#rootPick").append(nodeSelect(nodeId, nodes, (x) => { nodeId = x; }));
    const drill = async (root) => {
      const now = new Date(); const [from, to] = dayRangeMs(now.getFullYear(), now.getMonth() + 1, now.getDate());
      try {
        const rows = await apiClient.breakdown(root, from, to);
        const scaled = scaleBars((rows || []).map((r) => ({ label: r.title, value: r.total_ms, id: r.node_id })));
        pLog.querySelector("#bOut").innerHTML = scaled.length ? scaled.map((r) =>
          `<div class="bar"><span class="bl" title="${esc(r.label)}">${esc(r.label)}</span><span class="bt"><span class="bf" style="display:block;width:${r.pct}%"></span></span><span class="bv">${formatMsLong(r.value)}</span><button class="btn" data-drill="${esc(r.id)}">drill</button></div>`,
        ).join("") : `<p class="muted">No child totals.</p>`;
        pLog.querySelectorAll("[data-drill]").forEach((b) => { b.onclick = () => drill(b.dataset.drill); });
        const s = await apiClient.timerSummary(root);
        pLog.querySelector("#sumOut").innerHTML =
          `<p class="small">Node <strong>${formatMsLong(s.node_total_ms)}</strong> · Descendants <strong>${formatMsLong(s.descendant_total_ms)}</strong> · Project <strong>${formatMsLong(s.project_total_ms)}</strong></p>`;
      } catch (err) { toast(`Breakdown failed: ${err.message}`, "bad"); }
    };
    pLog.querySelector("#bLoad").onclick = () => nodeId ? drill(nodeId) : toast("Pick a node first");
    try {
      const presets = await apiClient.presets();
      if (Array.isArray(presets) && presets.length)
        pLog.querySelector("#sumOut").innerHTML = `<p class="muted small">Presets: ${presets.map((p) => esc(`${p.focus_minutes || 25}/${p.break_minutes || 5}×${p.cycles || 4}`)).join(" · ")}</p>`;
    } catch { /* optional */ }
  }

  mountAiRow("timer — text creates a node", async (text) => {
    await apiClient.createNode({ title: text, parent_id: nodeId || undefined });
    toast("Logged as node");
  }, async (text) => {
    if (!text) return;
    await apiClient.createNode({ title: text, parent_id: nodeId || undefined });
    toast("Voice note logged");
  });
  await refresh();
  await drawLog();
  tickH = setInterval(async () => { try { running = await apiClient.timer(); } catch { /* keep */ } tick(); }, 2000);
  cleanup = () => clearInterval(tickH);
}

// ----- Briefing -----
async function renderBriefing() {
  const v = view(); v.innerHTML = "";
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  v.innerHTML = `<div class="view-head"><h2>Briefing</h2><div class="spacer"></div>
    <input type="date" id="bDate" value="${iso}"><button class="btn" id="bLoad">Load</button></div>
    <div class="card" id="bBody"><p class="muted">Loading…</p></div>
    <div class="card"><h3>Ask a question</h3>
      <div class="row"><input type="text" id="bQ" style="flex:1" placeholder="e.g. What should I focus on today?"><button class="btn primary" id="bAsk">Ask</button></div>
      <div id="bAns" style="margin-top:8px"></div></div>`;

  const load = async () => {
    const date = v.querySelector("#bDate").value || iso;
    const body = v.querySelector("#bBody");
    try {
      const b = await apiClient.briefing(date);
      notify("briefing", "Briefing ready", date);
      if (b && typeof b === "object") {
        body.innerHTML = Object.entries(b).map(([k, val]) => {
          const items = Array.isArray(val) ? val.map((i) => `<li>${esc(typeof i === "string" ? i : JSON.stringify(i))}</li>`).join("") : `<p>${esc(typeof val === "string" ? val : JSON.stringify(val))}</p>`;
          return `<h3>${esc(k)}</h3>${Array.isArray(val) ? `<ul>${items}</ul>` : items}`;
        }).join("");
      } else body.innerHTML = `<p>${esc(String(b))}</p>`;
    } catch (err) { body.innerHTML = `<p class="bad-t">Load failed: ${esc(err.message)}</p>`; }
  };
  const ask = async (q) => {
    const out = v.querySelector("#bAns");
    out.innerHTML = `<p class="muted">…</p>`;
    try {
      const res = await apiClient.askQuestion(q);
      out.innerHTML = `<p>${esc(res && (res.answer || res.question || JSON.stringify(res)))}</p>`;
    } catch (err) { out.innerHTML = `<p class="bad-t">Ask failed: ${esc(err.message)}</p>`; }
  };
  v.querySelector("#bLoad").onclick = load;
  v.querySelector("#bAsk").onclick = () => { const q = v.querySelector("#bQ").value.trim(); if (q) ask(q); };
  v.querySelector("#bQ").onkeydown = (e) => { if (e.key === "Enter") v.querySelector("#bAsk").click(); };
  mountAiRow("briefing — text asks a question", ask, ask);
  await load();
}

// ----- Stats: charts (hand-drawn SVG/div bars, no deps) -----
async function renderStats() {
  const v = view(); v.innerHTML = `<div class="view-head"><h2>Stats</h2><div class="spacer"></div><button class="btn" id="sRel">Reload</button></div><div id="sBody"><p class="muted">Loading…</p></div>`;
  const draw = async () => {
    const body = v.querySelector("#sBody");
    try {
      const [stats, nodes] = await Promise.all([apiClient.stats(), nodeOptions()]);
      const counts = (stats && stats.counts) || {};
      const byKind = {};
      for (const n of nodes || []) byKind[n.kind || "node"] = (byKind[n.kind || "node"] || 0) + 1;
      const kindBars = scaleBars(Object.entries(byKind).map(([label, value]) => ({ label, value })));
      // events per day, last 7 days
      const days = [];
      for (let i = 6; i >= 0; i--) {
        const d = new Date(); d.setDate(d.getDate() - i);
        days.push([d, ...dayRangeMs(d.getFullYear(), d.getMonth() + 1, d.getDate())]);
      }
      const ev = await apiClient.events(days[0][1], Date.now());
      const perDay = days.map(([d, from, to]) => ({
        label: `${d.getMonth() + 1}/${d.getDate()}`,
        value: (ev || []).filter((e) => Number(e.start_ms) >= from && Number(e.start_ms) < to).length,
      }));
      const dayBars = scaleBars(perDay);
      let timerHtml = "";
      try {
        const s = await apiClient.timerSummary();
        timerHtml = `<div class="card"><h3>Tracked time (all)</h3><p style="font-size:22px">${formatMsLong(s.project_total_ms)}</p></div>`;
      } catch { timerHtml = `<div class="card"><p class="muted">Timer totals unavailable.</p></div>`; }
      const bars = (rows, unit) => rows.map((r) =>
        `<div class="bar"><span class="bl">${esc(r.label)}</span><span class="bt"><span class="bf" style="display:block;width:${r.pct}%"></span></span><span class="bv">${unit === "ms" ? formatMsLong(r.value) : esc(r.value)}</span></div>`).join("");
      body.innerHTML = `
        <div class="grid2">
          <div class="card"><h3>Counts</h3>${Object.entries(counts).map(([k, x]) => `<div class="bar"><span class="bl">${esc(k)}</span><span class="bt"></span><span class="bv">${esc(x)}</span></div>`).join("") || '<p class="muted">none</p>'}
          ${(stats && stats.streaks) ? `<p class="small muted">Streak current ${esc(stats.streaks.current)} · best ${esc(stats.streaks.best)}</p>` : ""}</div>
          ${timerHtml}
        </div>
        <div class="card"><h3>Nodes by kind</h3>${bars(kindBars)}</div>
        <div class="card"><h3>Events per day (7d)</h3>${bars(dayBars)}</div>`;
    } catch (err) { body.innerHTML = `<p class="bad-t">Stats failed: ${esc(err.message)}</p>`; }
  };
  v.querySelector("#sRel").onclick = draw;
  mountAiRow("stats — text searches nodes", async (text) => {
    const res = await apiClient.search(text);
    toast(`Search: ${Array.isArray(res) ? res.length : 0} hit(s)`);
  }, async () => {});
  await draw();
}

// ----- Settings -----
async function renderSettings() {
  const v = view(); v.innerHTML = `<div class="view-head"><h2>Settings</h2></div><div id="setBody"></div>`;
  const body = v.querySelector("#setBody");
  const keyState = cfg.key ? "saved (hidden)" : "not set";

  body.innerHTML = `
    <div class="card"><h3>Server</h3>
      <div class="row"><label style="flex:1">URL <input type="text" id="sUrl" value="${esc(cfg.serverUrl)}" style="width:260px"></label>
      <label>Instance key <input type="password" id="sKey" placeholder="${esc(keyState)}" autocomplete="off" style="width:200px"></label></div>
      <div class="row" style="margin-top:8px"><button class="btn primary" id="sSave">Save</button>
      <button class="btn" id="sTest">Test connection</button><span id="sTestOut" class="small muted"></span></div>
      <div class="row" style="margin-top:8px"><label>Discovery port <input type="number" id="sPort" value="${esc(cfg.discoveryPort)}" style="width:80px"></label>
      <label>Subnet base <input type="text" id="sSub" placeholder="e.g. 192.168.1 (optional)" style="width:150px"></label>
      <button class="btn" id="sFind">Auto-find server</button><span id="sFindOut" class="small muted"></span></div>
      <p class="small muted">Auto-find order: 127.0.0.1 → LAN /24 on the discovery port (default 693), same as the Android app. Auth probe uses the SAVED key only.</p>
    </div>
    <div class="card"><h3>Providers</h3><div id="provList"><p class="muted">Loading…</p></div>
      <div class="row" style="margin-top:8px">
        <select id="pGroup"><option value="text">text</option><option value="stt">stt</option><option value="embeddings">embeddings</option></select>
        <input type="text" id="pName" placeholder="name" style="width:130px">
        <input type="text" id="pBase" placeholder="https://…/v1" style="width:200px">
        <input type="text" id="pModel" placeholder="model" style="width:130px">
        <button class="btn" id="pAdd">Add provider</button></div>
      <p class="small muted">Order (↑↓) = failover order. Keys are write-only: values are never displayed.</p></div>
    <div class="card"><h3>App</h3>
      <div class="row"><label><input type="checkbox" id="aStart"> Launch at login (hidden --autostart)</label>
      <span id="aStartNote" class="small muted"></span></div>
      <div class="row" style="margin-top:8px"><span class="small">Notifications:</span>
        ${["timer", "reminder", "briefing", "proposal"].map((c) => `<label class="small"><input type="checkbox" data-notif="${c}" ${cfg.notif[c] ? "checked" : ""}> ${c}</label>`).join("")}
      </div>
      <div class="row" style="margin-top:8px"><button class="btn danger" id="kRenew">Rotate instance key</button>
      <span class="small muted">POST /api/keys/renew — new key shown once.</span></div>
      <div id="kNew"></div></div>`;

  body.querySelector("#sSave").onclick = () => {
    cfg.serverUrl = normalizeBaseUrl(body.querySelector("#sUrl").value);
    const k = body.querySelector("#sKey").value.trim();
    if (k) cfg.key = k;
    cfg.discoveryPort = Number(body.querySelector("#sPort").value) || DEFAULT_DISCOVERY_PORT;
    saveCfg(); apiClient = api();
    toast("Saved"); checkHealth();
  };
  body.querySelector("#sTest").onclick = async () => {
    const out = body.querySelector("#sTestOut");
    out.textContent = "…";
    try {
      const h = await api().get("/api/health", { auth: false });
      await api().probe();
      out.innerHTML = `<span class="ok-t">OK</span> <span class="muted">${esc(h.version || "")}</span>`;
    } catch (err) { out.innerHTML = `<span class="bad-t">${esc(err.message)}</span>`; }
  };
  body.querySelector("#sFind").onclick = async () => {
    const out = body.querySelector("#sFindOut");
    const port = Number(body.querySelector("#sPort").value) || DEFAULT_DISCOVERY_PORT;
    const sub = body.querySelector("#sSub").value.trim();
    // Local IP hint: subnet base (192.168.1 -> 192.168.1.50) or host part
    // of the current server URL when it is a LAN address.
    let localIp = null;
    if (/^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(sub)) localIp = `${sub}.50`;
    else {
      try {
        const h = new URL(cfg.serverUrl).hostname;
        if (/^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h)) localIp = h;
      } catch { /* ignore */ }
    }
    out.textContent = `scanning ${candidates(localIp).length} hosts…`;
    const fetchFn = async (url, { headers = {}, timeoutMs = 1500 } = {}) => {
      const ctl = new AbortController();
      const t = setTimeout(() => ctl.abort(), timeoutMs);
      try {
        const res = await fetch(url, { headers, signal: ctl.signal });
        return { ok: res.ok, status: res.status, json: () => res.json() };
      } finally { clearTimeout(t); }
    };
    const found = await scan({
      localIp, key: cfg.key, port, timeoutMs: 900, fetchFn,
      onProgress: (h) => { out.textContent = `probing ${h}…`; },
    });
    if (found) {
      cfg.serverUrl = found; saveCfg(); apiClient = api();
      body.querySelector("#sUrl").value = found;
      out.innerHTML = `<span class="ok-t">found ${esc(found)}</span>`;
      checkHealth();
    } else out.innerHTML = `<span class="warn-t">no authorized server found</span>`;
  };

  // providers
  const provList = body.querySelector("#provList");
  const loadProv = async () => {
    try {
      const grouped = await apiClient.providers();
      const groups = grouped && typeof grouped === "object" ? grouped : { providers: grouped };
      const entries = [];
      for (const [g, list] of Object.entries(groups)) for (const p of list || []) entries.push({ ...p, _group: g });
      if (!entries.length) { provList.innerHTML = `<p class="muted">No providers.</p>`; return; }
      provList.innerHTML = entries.map((p, i) =>
        `<div class="row" style="border-top:1px solid var(--line);padding:6px 0">
          <strong>${esc(p.name || p.id)}</strong><span class="kind">${esc(p._group)}</span>
          <span class="muted small">${esc(p.base_url || "")} ${esc(p.model || "")} · keys: ${esc(p.key_count ?? p.keys?.length ?? "?")}</span>
          <div class="spacer"></div>
          <button class="btn" data-up="${i}" ${i === 0 ? "disabled" : ""}>↑</button>
          <button class="btn" data-dn="${i}" ${i === entries.length - 1 ? "disabled" : ""}>↓</button>
          <input type="password" data-keyin="${esc(p.id)}" placeholder="new key" autocomplete="off" style="width:120px">
          <button class="btn" data-keyadd="${esc(p.id)}">+key</button>
          <button class="btn" data-keydel="${esc(p.id)}">del key</button>
          <button class="btn danger" data-del="${esc(p.id)}">delete</button>
        </div>`).join("");
      const move = async (idx, dir) => {
        const p = entries[idx];
        await apiClient.providerUpdate(p.id, { position: idx + dir });
        loadProv();
      };
      provList.querySelectorAll("[data-up]").forEach((b) => { b.onclick = () => move(Number(b.dataset.up), -1).catch((e) => toast(e.message, "bad")); });
      provList.querySelectorAll("[data-dn]").forEach((b) => { b.onclick = () => move(Number(b.dataset.dn), 1).catch((e) => toast(e.message, "bad")); });
      provList.querySelectorAll("[data-del]").forEach((b) => {
        b.onclick = async () => { if (confirm("Delete provider?")) { await apiClient.providerDelete(b.dataset.del); loadProv(); } };
      });
      provList.querySelectorAll("[data-keyadd]").forEach((b) => {
        b.onclick = async () => {
          const inp = provList.querySelector(`[data-keyin="${b.dataset.keyadd}"]`);
          if (!inp.value) { toast("Type a key first"); return; }
          await apiClient.providerKeyAdd(b.dataset.keyadd, inp.value);
          inp.value = ""; toast("Key added (never displayed)"); loadProv();
        };
      });
      provList.querySelectorAll("[data-keydel]").forEach((b) => {
        b.onclick = async () => {
          const keyId = prompt("Key id to delete:");
          if (!keyId) return;
          await apiClient.providerKeyDelete(b.dataset.keydel, keyId);
          toast("Key deleted"); loadProv();
        };
      });
    } catch (err) { provList.innerHTML = `<p class="bad-t">${esc(err.message)}</p>`; }
  };
  body.querySelector("#pAdd").onclick = async () => {
    try {
      await apiClient.providerAdd({
        group: body.querySelector("#pGroup").value,
        name: body.querySelector("#pName").value.trim() || undefined,
        base_url: body.querySelector("#pBase").value.trim(),
        model: body.querySelector("#pModel").value.trim() || undefined,
      });
      toast("Provider added"); loadProv();
    } catch (err) { toast(`Add failed: ${err.message}`, "bad"); }
  };
  await loadProv();

  // autostart + notifications + rotation
  const aStart = body.querySelector("#aStart");
  if (bridge) {
    try { aStart.checked = await bridge.autostartGet(); }
    catch { body.querySelector("#aStartNote").textContent = "(unavailable)"; }
    aStart.onchange = async () => {
      try { await bridge.autostartSet(aStart.checked); toast(aStart.checked ? "Autostart on" : "Autostart off"); }
      catch (err) { toast(`Autostart failed: ${err.message}`, "bad"); aStart.checked = !aStart.checked; }
    };
  } else {
    aStart.disabled = true;
    body.querySelector("#aStartNote").textContent = "(desktop bridge unavailable — browser preview)";
  }
  body.querySelectorAll("[data-notif]").forEach((c) => {
    c.onchange = () => { cfg.notif[c.dataset.notif] = c.checked; saveCfg(); };
  });
  body.querySelector("#kRenew").onclick = async () => {
    if (!confirm("Rotate the instance key? Other devices will be logged out.")) return;
    try {
      const res = await apiClient.renewInstanceKey();
      cfg.key = res.new_key; saveCfg(); apiClient = api();
      body.querySelector("#kNew").innerHTML =
        `<p class="warn-t">New key (shown once, already saved locally): <code>${esc(res.new_key)}</code></p>`;
    } catch (err) { toast(`Rotation failed: ${err.message}`, "bad"); }
  };

  mountAiRow("settings — text creates a node", async (text) => {
    await apiClient.createNode({ title: text });
    toast("Note saved as node");
  }, async () => {});
}

// ============================ shell ============================
const VIEWS = { planner: renderPlanner, timer: renderTimer, briefing: renderBriefing, stats: renderStats, settings: renderSettings };

async function switchView(name, arg) {
  cleanup(); cleanup = () => {};
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  cfg.view = name; saveCfg();
  try { await VIEWS[name](arg); }
  catch (err) { view().innerHTML = `<p class="bad-t">View failed: ${esc(err.message)}</p>`; }
  view().dataset.ready = "1";
}

async function init() {
  // sidebar collapse (persisted in userData JSON, mirrored locally)
  const sb = $("#sidebar");
  const stored = await udStore.get("sidebarCollapsed");
  if (stored ?? cfg.sidebarCollapsed) sb.classList.add("collapsed");
  const syncCollapse = () => {
    const c = sb.classList.contains("collapsed");
    document.body.classList.toggle("sb-collapsed", c);
    $("#collapse").textContent = c ? "▶" : "◀";
    udStore.set("sidebarCollapsed", c);
  };
  $("#collapse").onclick = () => { sb.classList.toggle("collapsed"); syncCollapse(); };
  syncCollapse();

  document.querySelectorAll("#nav button").forEach((b) => { b.onclick = () => switchView(b.dataset.view); });

  apiClient = api();
  setBanner();
  await checkHealth();
  setInterval(checkHealth, 10000);
  setInterval(pollReminders, 60000);
  await switchView(VIEWS[cfg.view] ? cfg.view : "planner");
}

document.addEventListener("DOMContentLoaded", init);
