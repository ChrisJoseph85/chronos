// Main-process logic: autostart, store, discovery, notify validation.
import { test } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { isAutostartLaunch, linuxDesktopEntry, setAutostartLinux } from "../main/autostart.js";
import { loadStore, saveStore } from "../main/store.js";
import { discoveryTargets, DISCOVERY_PORT } from "../main/discovery.js";
import { isValidNotify } from "../main/main.js";

test("autostart flag + linux entry user-level only", () => {
  assert.equal(isAutostartLaunch(["x", "--autostart"]), true);
  assert.equal(isAutostartLaunch(["x"]), false);
  const e = linuxDesktopEntry("/a/Chronos.AppImage");
  assert.ok(e.includes("--autostart") && e.includes("/a/Chronos.AppImage"));
  const writes = [];
  const f = { writeFileSync: (p, c) => writes.push([p, c]), unlinkSync: (p) => writes.push(["rm", p]) };
  const fp = setAutostartLinux(true, "/home/u", f, "/a/x");
  assert.equal(fp, path.join("/home/u", ".config", "autostart", "chronos.desktop"));
  setAutostartLinux(false, "/home/u", f);
  assert.deepEqual(writes[1][0], "rm");
});

test("store round-trip, corrupt fallback, secrets never persisted", () => {
  const fs = { files: {}, readFileSync(p) { if (!(p in this.files)) throw new Error("no"); return this.files[p]; }, writeFileSync(p, c) { this.files[p] = c; }, mkdirSync() {} };
  saveStore("/u", { bounds: { w: 1 }, sidebar: "icons", key: "SECRET", serverUrl: "http://x" }, fs);
  const raw = Object.values(fs.files)[0];
  assert.ok(!raw.includes("SECRET"), "secret leaked to disk");
  assert.deepEqual(Object.keys(loadStore("/u", fs)).sort(), ["bounds", "sidebar", "serverUrl"].sort());
  fs.files = { [Object.keys(fs.files)[0]]: "{broken" };
  assert.deepEqual(loadStore("/u", fs), {});
});

test("discovery targets: localhost first, port 693", () => {
  assert.equal(DISCOVERY_PORT, 693);
  const { port, targets } = discoveryTargets();
  assert.equal(port, 693);
  assert.equal(targets[0], "127.0.0.1");
  assert.ok(targets.length > 200);
});

test("notify validation rejects empty/oversize", () => {
  assert.equal(isValidNotify({ title: "t", body: "b" }), true);
  assert.equal(isValidNotify({ title: "  ", body: "b" }), false);
  assert.equal(isValidNotify({ title: "x".repeat(201), body: "b" }), false);
  assert.equal(isValidNotify(null), false);
});
