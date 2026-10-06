// Server discovery. Browsers cannot enumerate the LAN, so: 127.0.0.1
// first, then the manual host, then remembered hosts (deduped).
export const DEFAULT_PORT = 693;

export function normalizeHost(h: string): string {
  return h.trim().replace(/\/+$/, "");
}

export function withPort(host: string, port = DEFAULT_PORT): string {
  const h = normalizeHost(host);
  if (/^https?:\/\//.test(h)) return h;
  return `http://${h}:${port}`;
}

// Order: loopback first, then manual, then remembered (dedup, loopback not repeated).
export function orderHosts(manualHost: string | null, remembered: string[]): string[] {
  const out: string[] = ["http://127.0.0.1:" + DEFAULT_PORT];
  const push = (u: string) => {
    const n = normalizeHost(u);
    if (n && !out.includes(n)) out.push(n);
  };
  if (manualHost && manualHost.trim()) push(withPort(manualHost));
  for (const r of remembered) push(normalizeHost(r));
  return out;
}

export function rememberHost(remembered: string[], host: string, cap = 8): string[] {
  const n = normalizeHost(host);
  if (!n) return remembered;
  return [n, ...remembered.filter((h) => h !== n)].slice(0, cap);
}
