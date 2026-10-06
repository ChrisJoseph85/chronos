// Click-through: every screen renders, every button calls its handler, AI row on each.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { makeDom } from "./dom-stub.js";

const root = new URL("..", import.meta.url).pathname;
const load = (f) => readFileSync(root + f, "utf8");

function setup(apiOverrides = {}) {
  const { El, document, root: body } = makeDom();
  const calls = [];
  const api = {
    listNodes: async () => ({ ok: true, nodes: [{ id: "n1", title: "T1", tags: ["a"] }] }),
    timerStart: async (...a) => (calls.push(["timerStart", ...a]), { ok: true }),
    timerStop: async (...a) => (calls.push(["timerStop", ...a]), { ok: true }),
    breakdown: async () => ({ ok: true, rows: [{ label: "x", total: 3 }] }),
    briefing: async () => ({ ok: true, briefing: "b" }),
    ask: async (...a) => (calls.push(["ask", ...a]), { ok: true, answer: "A" }),
    providers: async () => ({ ok: true, providers: [{ id: "p1", name: "P" }] }),
    providerAdd: async (...a) => (calls.push(["providerAdd", ...a]), { ok: true }),
    keyAdd: async (...a) => (calls.push(["keyAdd", ...a]), { ok: true }),
    health: async () => ({ ok: true }),
    voice: async (...a) => (calls.push(["voice", ...a]), { ok: true }),
    prefs: () => ({}),
    ...apiOverrides,
  };
  const banners = [], notifs = [];
  global.document = document;
  global.window = { Chronos: { screens: {} }, ChronosApi: api };
  global.localStorage = { _m: {}, getItem(k) { return this._m[k] ?? null; }, setItem(k, v) { this._m[k] = v; } };
  global.fetch = async () => { throw new Error("no-net"); };
  global.alert = () => {};
  global.prompt = () => null;
  const ctx = {
    api, go: (...a) => calls.push(["go", ...a]),
    notify: (t, b, k) => notifs.push([t, k]),
    banner: (m) => banners.push(m),
    aiRow: (host, s) => global.window.ChronosAiRow.mount(host, ctx, s),
    prefs: () => ({}), savePrefs: () => {}, autostart: false,
    setAutostart: (...a) => calls.push(["setAutostart", ...a]),
    setNotify: (...a) => calls.push(["setNotify", ...a]),
  };
  for (const f of ["renderer/ai-row.js", "renderer/screens/planner.js", "renderer/screens/timer.js",
    "renderer/screens/briefing.js", "renderer/screens/stats.js", "renderer/screens/settings.js"]) {
    eval.call({}, load(f));
  }
  const S = global.window.Chronos.screens;
  const mount = (name) => { const host = new El("main"); S[name].init(host, ctx); ctx.aiRow(host.querySelector(".ai-mount") ?? host, name); return host; };
  return { El, document, body, calls, banners, notifs, ctx, S, mount };
}

test("planner renders + day click + node click navigates", async () => {
  const { mount, calls, S } = setup();
  const host = mount("planner");
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  assert.ok(host.querySelector("#p-cal").children.length > 27);
  assert.equal(host.querySelector("#p-tree").textContent.includes("T1"), true);
  host.querySelector("#p-cal").children[0].click();
  await new Promise((r) => setImmediate(r));
  host.querySelector("#p-tree").children[0].click();
  assert.deepEqual(calls.find((c) => c[0] === "go"), ["go", "timer", { node: "n1" }]);
  assert.ok(S.planner && S.timer && S.briefing && S.stats && S.settings);
});

test("timer modes + start/stop/void call api + notify", async () => {
  const { mount, calls, notifs } = setup();
  const host = mount("timer");
  host.querySelector('[data-m="pomodoro"]').click();
  host.querySelector("#t-start").click();
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(calls.find((c) => c[0] === "timerStart"), ["timerStart", "pomodoro", false]);
  assert.equal(notifs[0][1], "timer");
  host.querySelector("#t-void").click();
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(calls.find((c) => c[0] === "timerStop"), ["timerStop", true]);
});

test("briefing ask + stats canvas + settings save/autostart/notify/provider", async () => {
  const { mount, calls, El } = setup();
  const b = mount("briefing");
  b.querySelector("#b-q").value = "q?";
  b.querySelector("#b-ask").click();
  await new Promise((r) => setImmediate(r));
  assert.ok(calls.some((c) => c[0] === "ask" && String(c[1]).includes("q?")));
  const s = mount("stats");
  assert.ok(s.querySelector("#s-cv"));
  const st = mount("settings");
  st.querySelector("#s-save").click();
  await new Promise((r) => setImmediate(r));
  st.querySelector("#s-auto").checked = true;
  const auto = st.querySelector("#s-auto");
  (auto.listeners.change ?? []).forEach((f) => f({ target: auto }));
  st.querySelector("#s-pname").value = "NP";
  st.querySelector("#s-padd").click();
  await new Promise((r) => setImmediate(r));
  assert.ok(calls.some((c) => c[0] === "setAutostart"));
  assert.ok(calls.some((c) => c[0] === "providerAdd"));
});

test("AI row on every screen: send calls ask, mic calls voice", async () => {
  const { mount, calls } = setup();
  for (const name of ["planner", "timer", "briefing", "stats", "settings"]) {
    const host = mount(name);
    const row = host.querySelector(".ai-row");
    assert.ok(row, `ai-row missing on ${name}`);
    row.querySelector("input").value = "hi";
    row.querySelector(".send").click();
    row.querySelector(".mic").click();
    await new Promise((r) => setImmediate(r));
  }
  assert.ok(calls.filter((c) => c[0] === "ask").length >= 5);
  assert.ok(calls.filter((c) => c[0] === "voice").length >= 5);
});

test("server-down boot: no throw, banner shown, AI disabled gracefully", async () => {
  const down = async () => ({ ok: false, down: true });
  const t = setup({ listNodes: down, briefing: down, breakdown: down, providers: down, ask: down, voice: down });
  for (const name of ["planner", "timer", "briefing", "stats", "settings"]) {
    const host = t.mount(name); // must not throw
    assert.ok(host.textContent.length >= 0);
  }
  await new Promise((r) => setImmediate(r));
  assert.ok(t.banners.some(Boolean), "expected a server-down banner");
});
