// Server auto-discovery, mirroring Android spec §9 (Discovery.kt).
// Order: 127.0.0.1 -> device LAN /24 hosts, same port throughout
// (default 693). Per host: short-timeout GET /api/health, then an
// authenticated probe with the SAVED instance key only. First healthy +
// authorized host wins. Pure + injectable fetch: shared by main tests and
// the renderer, no node/Electron APIs here.

export const DEFAULT_DISCOVERY_PORT = 693;
export const DEFAULT_TIMEOUT_MS = 1200;

/** /24 prefix of an IPv4 address, or null when not usable. */
export function subnet24(ip) {
  if (typeof ip !== "string") return null;
  const parts = ip.split(".");
  if (parts.length !== 4) return null;
  if (parts.some((p) => !/^\d{1,3}$/.test(p) || Number(p) < 0 || Number(p) > 255)) return null;
  if (parts[0] === "127") return null;
  return parts.slice(0, 3).join(".");
}

/** Candidate hosts in scan order. Localhost always first. */
export function candidates(localIp) {
  const out = ["127.0.0.1"];
  const prefix = subnet24(localIp);
  if (prefix) {
    for (let i = 1; i <= 254; i++) {
      const host = `${prefix}.${i}`;
      if (host !== localIp && !out.includes(host)) out.push(host);
    }
  }
  return out;
}

export function healthUrl(base) {
  return `${String(base).replace(/\/+$/, "")}/api/health`;
}

/**
 * Scan for a Chronos server.
 * @param {object} opts {localIp, key, port, timeoutMs, fetchFn, isCancelled, onProgress}
 * fetchFn(url, {headers, timeoutMs}) -> Response-like {ok, status, json()}
 * The authenticated probe uses the SAVED key only (never a pasted key at
 * scan time — callers pass the stored key).
 */
export async function scan(opts = {}) {
  const {
    localIp = null,
    key = "",
    port = DEFAULT_DISCOVERY_PORT,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    fetchFn = fetch,
    isCancelled = () => false,
    onProgress = () => {},
  } = opts;
  if (!key) return null;
  for (const host of candidates(localIp)) {
    if (isCancelled()) return null;
    onProgress(host);
    const base = `http://${host}:${port}`;
    try {
      const healthy = await fetchFn(healthUrl(base), { timeoutMs });
      if (!healthy || !healthy.ok) continue;
      const authed = await fetchFn(`${base}/api/timer`, {
        headers: { "X-Chronos-Key": key },
        timeoutMs,
      });
      // 401/403 = server alive but key wrong -> keep scanning.
      if (authed && (authed.ok || authed.status === 404)) return base;
    } catch {
      continue;
    }
  }
  return null;
}
