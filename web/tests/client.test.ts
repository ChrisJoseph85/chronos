import { describe, it, expect, vi } from "vitest";
import { authHeaders, requireKey, needsProposal, decideStopVoid, stopPayload, ChronosClient, joinUrl } from "../src/api";
import { orderHosts, rememberHost } from "../src/discovery";
import { summarizeBreakdown } from "../src/breakdown";
import { sanitizeProvider, renderProvidersSafe } from "../src/providers";
import * as fs from "node:fs";

const SECRET = "k-very-secret-abc123";

function fakeFetch(handler: (url: string, init?: RequestInit) => unknown) {
  return (async (url: string, init?: RequestInit) => {
    const body = handler(url, init);
    return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch;
}

describe("auth header", () => {
  it("sends X-Chronos-Key", () => {
    expect(authHeaders(SECRET)["X-Chronos-Key"]).toBe(SECRET);
  });
  it("client attaches key on every request", async () => {
    let seen: Record<string, string> | undefined;
    const f = fakeFetch((_u, init) => { seen = init?.headers as Record<string, string>; return {}; });
    const c = new ChronosClient("http://127.0.0.1:693", SECRET, f);
    await c.get("/api/stats");
    expect(seen!["X-Chronos-Key"]).toBe(SECRET);
  });
});

describe("key absence", () => {
  it("requireKey throws", () => { expect(() => requireKey(null)).toThrow(/missing-key/); });
  it("client refuses without key", async () => {
    const c = new ChronosClient("http://x", "", fakeFetch(() => ({})));
    await expect(c.get("/api/stats")).rejects.toThrow(/missing-key/);
  });
});

describe("proposal flow", () => {
  it("ambiguous say needs proposal; committed does not", () => {
    expect(needsProposal({ committed: false, proposal_id: "p-1" })).toBe(true);
    expect(needsProposal({ committed: true, proposal_id: "p-1" })).toBe(false);
    expect(needsProposal({ committed: false })).toBe(false);
  });
  it("accept routes proposal_id over the socket payload", async () => {
    const sent: string[] = [];
    const { wsProposalAction } = await import("../src/api");
    wsProposalAction({ send: (d: string) => sent.push(d) }, "accept", "p-9");
    expect(JSON.parse(sent[0]).proposal_id).toBe("p-9");
  });
});

describe("breakdown math", () => {
  it("sums and sorts with pct", () => {
    const s = summarizeBreakdown([
      { node_id: "a", title: "A", kind: "task", total_ms: 60000 },
      { node_id: "b", title: "B", kind: "task", total_ms: 180000 },
    ]);
    expect(s.total_ms).toBe(240000);
    expect(s.rows[0].node_id).toBe("b");
    expect(s.rows[0].pct).toBeCloseTo(75);
  });
  it("empty is zero-safe", () => {
    expect(summarizeBreakdown([]).total_ms).toBe(0);
  });
});

describe("void logic", () => {
  it("first stop keeps; void only after confirmed second attempt", () => {
    expect(decideStopVoid(false, false)).toBe(false);
    expect(decideStopVoid(true, false)).toBe(false);
    expect(decideStopVoid(true, true)).toBe(true);
    expect(stopPayload("web", false)).toEqual({ source: "web" });
    expect(stopPayload("web", true)).toEqual({ source: "web", void: true });
  });
});

describe("discovery ordering", () => {
  it("127.0.0.1 first, then manual, then remembered deduped", () => {
    const o = orderHosts("192.168.1.10", ["http://192.168.1.20:693", "http://127.0.0.1:693"]);
    expect(o[0]).toBe("http://127.0.0.1:693");
    expect(o[1]).toMatch(/192\.168\.1\.10/);
    expect(o.filter((x) => x === "http://127.0.0.1:693")).toHaveLength(1);
    expect(o).toContain("http://192.168.1.20:693");
  });
  it("rememberHost dedups and caps", () => {
    expect(rememberHost(["b"], "a")).toEqual(["a", "b"]);
    expect(rememberHost(["a"], "a")).toEqual(["a"]);
  });
  it("joinUrl trims slashes", () => {
    expect(joinUrl("http://h:693/", "/api/health")).toBe("http://h:693/api/health");
  });
});

describe("provider key write-only", () => {
  it("sanitize strips secret fields", () => {
    const s = sanitizeProvider({ id: "1", name: "x", key_value: SECRET, key: SECRET } as Record<string, unknown>);
    expect(JSON.stringify(s)).not.toContain(SECRET);
  });
  it("rendered list never contains key values", () => {
    const html = renderProvidersSafe([{ id: "1", group: "text", name: "n", base_url: "http://x", key_ids: ["k1"], key_count: 1 }]);
    expect(html).toContain("keys:1");
    expect(html).not.toContain(SECRET);
  });
});

describe("key never logged", () => {
  it("no console.log of the key in src", () => {
    const files = ["src/api.ts", "src/main.ts", "src/discovery.ts", "src/providers.ts", "src/breakdown.ts"];
    for (const f of files) {
      const src = fs.readFileSync(new URL(`../${f}`, import.meta.url), "utf8");
      for (const line of src.split("\n")) {
        if (line.includes("console.log")) {
          expect(line.includes("Key") || line.includes("key")).toBe(false);
        }
      }
    }
    expect(authHeaders(SECRET)["X-Chronos-Key"]).toBe(SECRET);
    void vi;
  });
});
