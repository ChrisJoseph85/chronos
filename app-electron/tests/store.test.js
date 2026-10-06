import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createStore } from "../main/store.js";

const fresh = () => createStore(join(mkdtempSync(join(tmpdir(), "chronos-")), "s.json"));

describe("store", () => {
  it("starts with defaults when file is missing", () => {
    const s = fresh();
    assert.equal(s.get("sidebarCollapsed"), false);
    assert.deepEqual(s.get("panels"), {});
    assert.equal(s.get("window"), null);
  });

  it("persists window bounds and panel fractions", () => {
    const dir = mkdtempSync(join(tmpdir(), "chronos-"));
    const p = join(dir, "s.json");
    createStore(p).set("window", { x: 1, y: 2, width: 800, height: 600, maximized: false });
    createStore(p).setPanel("planner-a", 0.33);
    const raw = JSON.parse(readFileSync(p, "utf8"));
    assert.equal(raw.window.width, 800);
    assert.ok(Math.abs(raw.panels["planner-a"] - 0.33) < 1e-9);
    assert.equal(createStore(p).get("window").width, 800);
  });

  it("clamps panel fractions to 0.1..0.9", () => {
    const s = fresh();
    assert.equal(s.setPanel("k", 99), 0.9);
    assert.equal(s.setPanel("k", -5), 0.1);
    assert.equal(s.setPanel("k", "junk"), 0.5);
  });

  it("recovers from corrupt JSON", () => {
    const dir = mkdtempSync(join(tmpdir(), "chronos-"));
    const p = join(dir, "s.json");
    writeFileSync(p, "{not json", "utf8");
    const s = createStore(p);
    assert.equal(s.get("window"), null);
    s.set("sidebarCollapsed", true); // overwrites corrupt file
    assert.equal(createStore(p).get("sidebarCollapsed"), true);
  });

  it("never stores secrets: only known UI keys round-trip", () => {
    const s = fresh();
    s.set("window", { width: 1, height: 1 });
    const raw = JSON.parse(readFileSync(s.path, "utf8"));
    assert.deepEqual(Object.keys(raw).sort(), ["panels", "sidebarCollapsed", "window"]);
  });
});
