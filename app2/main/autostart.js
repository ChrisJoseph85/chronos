// Pure autostart helpers (no electron import: testable under plain node).
import path from "node:path";

export const isAutostartLaunch = (argv = process.argv) => argv.includes("--autostart");

export function linuxDesktopEntry(exec) {
  return `[Desktop Entry]\nType=Application\nName=Chronos\nExec="${exec}" --autostart\nX-GNOME-Autostart-enabled=true\n`;
}

// on=true writes user-level entry (never sudo); on=false removes it.
export function setAutostartLinux(on, home = process.env.HOME ?? "", f, exec = process.execPath) {
  const fp = path.join(home, ".config", "autostart", "chronos.desktop");
  if (on) f.writeFileSync(fp, linuxDesktopEntry(exec), { mode: 0o644 });
  else try { f.unlinkSync(fp); } catch { /* already absent */ }
  return fp;
}
