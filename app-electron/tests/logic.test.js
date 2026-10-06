import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  formatDuration, formatMsLong, buildNodeTree, collectTags, monthCells,
  dayRangeMs, monthRangeMs, scaleBars, eventsByDay, clampFraction, parseHostPort,
} from "../renderer/src/logic.js";

describe("renderer logic", () => {
  it("formats durations", () => {
    assert.equal(formatDuration(0), "0:00");
    assert.equal(formatDuration(65000), "1:05");
    assert.equal(formatDuration(3661000), "1:01:01");
    assert.equal(formatMsLong(3600000), "1h");
    assert.equal(formatMsLong(5400000), "1h 30m");
    assert.equal(formatMsLong(60000), "1m");
  });

  it("builds sorted node trees", () => {
    const tree = buildNodeTree([
      { id: "c", title: "zeta", parent_id: "a" },
      { id: "a", title: "root" },
      { id: "b", title: "alpha", parent_id: "a" },
      { id: "orphan", title: "x", parent_id: "missing" },
    ]);
    assert.equal(tree.length, 2); // root + orphan-with-missing-parent
    assert.deepEqual(tree[0].children.map((n) => n.id), ["b", "c"]);
  });

  it("collects tags from mixed shapes", () => {
    assert.deepEqual(
      collectTags([{ tags: ["b", "a"] }, { tags: "c, a" }, { tag: "d" }, {}]),
      ["a", "b", "c", "d"],
    );
  });

  it("renders month grids", () => {
    const cells = monthCells(2026, 10, 1); // Oct 2026 starts Thursday
    assert.equal(cells.slice(0, 3).every((c) => c === null), true);
    assert.equal(cells[3], 1);
    assert.equal(cells.filter(Boolean).length, 31);
  });

  it("computes day/month ranges", () => {
    const [s, e] = dayRangeMs(2026, 10, 6);
    assert.equal(e - s, 86400000);
    const [ms, me] = monthRangeMs(2026, 2);
    assert.equal(me - ms, 28 * 86400000);
  });

  it("scales bars and groups events by day", () => {
    assert.deepEqual(scaleBars([{ value: 0 }]), [{ value: 0, pct: 0 }]);
    const rows = scaleBars([{ value: 50, label: "a" }, { value: 100, label: "b" }]);
    assert.deepEqual(rows.map((r) => r.pct), [50, 100]);
    const m = eventsByDay([{ start_ms: new Date(2026, 9, 6, 12).getTime() }]);
    assert.equal(m.get("2026-10-06"), 1);
  });

  it("clamps splitter fractions and parses host:port", () => {
    assert.equal(clampFraction(0.33), 0.33);
    assert.equal(clampFraction(9), 0.9);
    assert.equal(clampFraction("junk"), 0.5);
    assert.deepEqual(parseHostPort("192.168.1.5:8080", 693), { host: "192.168.1.5", port: 8080 });
    assert.deepEqual(parseHostPort("example.local", 693), { host: "example.local", port: 693 });
  });
});
