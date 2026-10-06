// Electron main-process logic tests (no display needed). Run:
//   node --test web/tests-electron/notify.mjs   (from repo root)
// Kept out of vitest's default include (no .test./.spec. suffix) so the existing suite is untouched.
// Never imports the 'electron' package: main.js lazy-imports it only when run under Electron.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  IPC_NOTIFY,
  DEFAULT_SIZE,
  DIST_TARGETS,
  isDev,
  isAutostartLaunch,
  isValidNotify,
  loginItemArgs,
  desktopEntryText,
  distTargetsFor,
  resolveLoadTarget,
  loadBounds,
  saveBounds,
  setAutostartLinux,
  shouldQuitAsSecondInstance,
} from "../electron/main.js";

function fakeFs() {
  const files = new Map();
  return {
    files,
    readFileSync: (p) => {
      if (!files.has(p)) { const e = new Error("ENOENT"); e.code = "ENOENT"; throw e; }
      return files.get(p);
    },
    writeFileSync: (p, s) => { files.set(p, String(s)); },
    mkdirSync: () => {},
    unlinkSync: (p) => {
      if (!files.delete(p)) { const e = new Error("ENOENT"); e.code = "ENOENT"; throw e; }
    },
  };
}

describe("notify IPC validation", () => {
  it("channel name is chronos-notify", () => assert.equal(IPC_NOTIFY, "chronos-notify"));
  it("accepts a well-formed toast", () => assert.equal(isValidNotify({ title: "Timer started", body: "25:00" }), true));
  it("rejects empty title", () => assert.equal(isValidNotify({ title: "   ", body: "x" }), false));
  it("rejects missing/non-string fields", () => {
    assert.equal(isValidNotify(null), false);
    assert.equal(isValidNotify({ body: "x" }), false);
    assert.equal(isValidNotify({ title: "t" }), false);
    assert.equal(isValidNotify({ title: "t", body: 42 }), false);
  });
  it("rejects oversized payloads", () => {
    assert.equal(isValidNotify({ title: "t".repeat(201), body: "x" }), false);
    assert.equal(isValidNotify({ title: "t", body: "x".repeat(1001) }), false);
  });
});

describe("single instance", () => {
  it("quits when another instance holds the lock", () => assert.equal(shouldQuitAsSecondInstance(false), true));
  it("continues when the lock is acquired", () => assert.equal(shouldQuitAsSecondInstance(true), false));
});

describe("autostart settings args", () => {
  it("login item args enable open-at-login (Win/Mac)", () => {
    assert.deepEqual(loginItemArgs(true), { openAtLogin: true });
    assert.deepEqual(loginItemArgs(false), { openAtLogin: false });
  });
  it("--autostart flag detection", () => {
    assert.equal(isAutostartLaunch(["node", "main.js", "--autostart"]), true);
    assert.equal(isAutostartLaunch(["node", "main.js"]), false);
  });
  it("linux .desktop entry relaunches with --autostart", () => {
    const txt = desktopEntryText("/opt/Chronos/chronos");
    assert.match(txt, /\[Desktop Entry\]/);
    assert.match(txt, /--autostart/);
  });
  it("linux entry is user-level, never sudo paths", () => {
    const f = fakeFs();
    const fp = setAutostartLinux(true, "/home/u", f, "/opt/Chronos/chronos");
    assert.equal(fp, "/home/u/.config/autostart/chronos.desktop");
    assert.match(f.files.get(fp), /--autostart/);
    for (const p of f.files.keys()) {
      assert.ok(!p.startsWith("/etc") && !p.startsWith("/usr"), `must not touch system path: ${p}`);
    }
    setAutostartLinux(false, "/home/u", f);
    assert.equal(f.files.has(fp), false);
  });
});

describe("load target", () => {
  it("--dev loads the Vite server", () => {
    assert.deepEqual(resolveLoadTarget(["e", "--dev"]), { kind: "url", value: "http://localhost:5173" });
    assert.equal(isDev(["e", "--dev"]), true);
  });
  it("production loads web/dist", () => {
    const t = resolveLoadTarget(["e"]);
    assert.equal(t.kind, "file");
    assert.ok(t.value.endsWith("dist/index.html"), t.value);
  });
});

describe("dist targets", () => {
  it("covers AppImage+deb (linux), nsis (win), dmg (mac, unsigned)", () => {
    assert.deepEqual(DIST_TARGETS, { linux: ["AppImage", "deb"], win: ["nsis"], mac: ["dmg"] });
    assert.deepEqual(distTargetsFor("linux"), ["AppImage", "deb"]);
    assert.deepEqual(distTargetsFor("win32"), ["nsis"]);
    assert.deepEqual(distTargetsFor("darwin"), ["dmg"]);
  });
});

describe("window bounds memory", () => {
  it("defaults to 1280x860", () => {
    assert.deepEqual(DEFAULT_SIZE, { width: 1280, height: 860 });
    assert.deepEqual(loadBounds("/nope", fakeFs()), { width: 1280, height: 860 });
  });
  it("round-trips through save/load", () => {
    const f = fakeFs();
    saveBounds("/ud", { width: 1400, height: 900, x: 10, y: 20 }, f);
    assert.deepEqual(loadBounds("/ud", f), { width: 1400, height: 900, x: 10, y: 20 });
  });
  it("falls back to defaults on corrupt/tiny data", () => {
    const f = fakeFs();
    f.files.set("/ud/window-bounds.json", "not-json{{{");
    assert.deepEqual(loadBounds("/ud", f).width, 1280);
    f.files.set("/ud/window-bounds.json", JSON.stringify({ width: 100, height: 100 }));
    assert.deepEqual(loadBounds("/ud", f).width, 1280);
  });
});
