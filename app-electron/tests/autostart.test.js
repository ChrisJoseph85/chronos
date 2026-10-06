import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  desktopFileContent, desktopFilePath, applyLinuxAutostart, applyAutostart, isAutostart,
} from "../main/autostart.js";

const memfs = () => {
  const files = new Map();
  return {
    files,
    mkdirSync: () => {},
    writeFileSync: (p, c) => files.set(p, String(c)),
    unlinkSync: (p) => {
      if (!files.has(p)) { const e = new Error("ENOENT"); e.code = "ENOENT"; throw e; }
      files.delete(p);
    },
    accessSync: (p) => {
      if (!files.has(p)) { const e = new Error("ENOENT"); e.code = "ENOENT"; throw e; }
    },
  };
};

describe("autostart", () => {
  it("linux .desktop is user-level and carries --autostart", () => {
    const body = desktopFileContent("/opt/Chronos/chronos");
    assert.match(body, /^\[Desktop Entry\]/m);
    assert.match(body, /--autostart/);
    assert.ok(!/sudo/.test(body));
    assert.equal(desktopFilePath("/home/u"), "/home/u/.config/autostart/chronos-electron.desktop");
  });

  it("linux apply sets and clears without sudo", () => {
    const fs = memfs();
    const base = { homeDir: "/home/u", execPath: "/opt/c", fs };
    assert.equal(applyLinuxAutostart({ ...base, enabled: true }), "set");
    assert.ok(fs.files.get(desktopFilePath("/home/u")).includes("--autostart"));
    assert.equal(applyLinuxAutostart({ ...base, enabled: false }), "cleared");
    assert.equal(applyLinuxAutostart({ ...base, enabled: false }), "cleared"); // idempotent
  });

  it("isAutostart reflects the .desktop file", () => {
    const fs = memfs();
    assert.equal(isAutostart({ platform: "linux", homeDir: "/home/u", fs }), false);
    applyLinuxAutostart({ homeDir: "/home/u", execPath: "/x", enabled: true, fs });
    assert.equal(isAutostart({ platform: "linux", homeDir: "/home/u", fs }), true);
  });

  it("win/mac delegate to setLoginItemSettings with --autostart arg", () => {
    const calls = [];
    const app = {
      setLoginItemSettings: (o) => calls.push(o),
      getLoginItemSettings: () => ({ openAtLogin: true }),
    };
    const r = applyAutostart({ platform: "darwin", enabled: true, app });
    assert.equal(r.method, "login-item");
    assert.deepEqual(calls[0], { openAtLogin: true, args: ["--autostart"] });
    assert.equal(isAutostart({ platform: "win32", app }), true);
  });

  it("unknown platforms report unsupported", () => {
    assert.equal(applyAutostart({ platform: "sunos", enabled: true }).method, "unsupported");
  });
});
