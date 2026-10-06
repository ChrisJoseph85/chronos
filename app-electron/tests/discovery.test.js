import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { subnet24, candidates, scan, DEFAULT_DISCOVERY_PORT } from "../main/discovery.js";

describe("discovery", () => {
  it("default port is 693 (Android spec §9)", () => {
    assert.equal(DEFAULT_DISCOVERY_PORT, 693);
  });

  it("subnet24 rejects junk and loopback", () => {
    assert.equal(subnet24("192.168.1.50"), "192.168.1");
    assert.equal(subnet24("10.0.0.5"), "10.0.0");
    assert.equal(subnet24("127.0.0.1"), null);
    assert.equal(subnet24("not-an-ip"), null);
    assert.equal(subnet24("1.2.3.999"), null);
    assert.equal(subnet24(null), null);
  });

  it("localhost is always first, then LAN /24 without self", () => {
    const c = candidates("192.168.1.50");
    assert.equal(c[0], "127.0.0.1");
    assert.equal(c.length, 254); // 127.0.0.1 + 253 others (self excluded)
    assert.ok(!c.includes("192.168.1.50"));
    assert.ok(c.includes("192.168.1.1"));
    assert.deepEqual(candidates(null), ["127.0.0.1"]);
  });

  it("scan returns first healthy+authorized host", async () => {
    const seen = [];
    const fetchFn = async (url, { headers = {} } = {}) => {
      seen.push(url);
      if (url.endsWith("/api/health")) return { ok: true, status: 200 };
      if (url.endsWith("/api/timer")) {
        return headers["X-Chronos-Key"] === "saved-key"
          ? { ok: true, status: 200 }
          : { ok: false, status: 401 };
      }
      return { ok: false, status: 404 };
    };
    const found = await scan({ localIp: null, key: "saved-key", fetchFn });
    assert.equal(found, "http://127.0.0.1:693");
    assert.ok(seen[0].endsWith("/api/health"));
  });

  it("scan skips hosts with wrong key and returns null without key", async () => {
    const deny = async (url) => (url.endsWith("/api/health") ? { ok: true } : { ok: false, status: 401 });
    assert.equal(await scan({ localIp: null, key: "wrong", fetchFn: deny }), null);
    assert.equal(await scan({ localIp: null, key: "", fetchFn: deny }), null);
  });

  it("scan honors cancellation", async () => {
    let n = 0;
    const fetchFn = async (url) => {
      n++;
      return url.endsWith("/api/health") ? { ok: true, status: 200 } : { ok: false, status: 401 };
    };
    const found = await scan({ localIp: "10.9.8.7", key: "k", fetchFn, isCancelled: () => n >= 6 });
    assert.equal(found, null);
    assert.ok(n <= 8, `expected early stop, got ${n} probes`);
  });
});
