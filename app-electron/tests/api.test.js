import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { Api, normalizeBaseUrl } from "../renderer/src/api.js";

const stub = (handler) => async (url, init = {}) => handler(url, init);
const ok = (data, status = 200) => ({ ok: status < 300, status, json: async () => data });

describe("api client", () => {
  it("normalizes base URLs", () => {
    assert.equal(normalizeBaseUrl(""), "http://127.0.0.1:8080");
    assert.equal(normalizeBaseUrl("host:1234/"), "http://host:1234");
    assert.equal(normalizeBaseUrl("https://x/"), "https://x");
  });

  it("sends the instance key as X-Chronos-Key header", async () => {
    let got;
    const api = new Api({ baseUrl: "http://h:1", key: "k123", fetchFn: stub((u, init) => { got = init; return ok({}); }) });
    await api.timer();
    assert.equal(got.headers["X-Chronos-Key"], "k123");
  });

  it("health is unauthenticated, errors carry server detail", async () => {
    let got;
    const api = new Api({
      baseUrl: "http://h:1", key: "k",
      fetchFn: stub((u, init) => {
        got = init;
        return u.endsWith("/api/health") ? ok({ status: "ok" }) : ok({ detail: "nope" }, 401);
      }),
    });
    assert.deepEqual(await api.health(), { status: "ok" });
    assert.deepEqual(got.headers, {});
    await assert.rejects(api.timer(), /nope/);
  });

  it("voice posts multipart form, createNode uses commands seam", async () => {
    const calls = [];
    const api = new Api({
      baseUrl: "http://h:1", key: "k",
      fetchFn: stub((u, init) => { calls.push([u, init]); return ok({ text: "hi" }); }),
    });
    await api.createNode({ title: "t" });
    assert.match(calls[0][0], /\/api\/commands$/);
    assert.deepEqual(JSON.parse(calls[0][1].body), { tool: "create_node", arguments: { title: "t" } });
    const fd = new FormData();
    fd.append("file", new Blob(["x"]), "n.webm");
    await api.voice(new Blob(["x"]));
    assert.match(calls[1][0], /\/api\/voice$/);
    assert.ok(calls[1][1].body instanceof FormData);
  });

  it("network failures become Error (health banner path)", async () => {
    const api = new Api({ baseUrl: "http://h:1", fetchFn: stub(() => { throw new Error("down"); }) });
    await assert.rejects(api.health(), /network: down/);
  });
});
