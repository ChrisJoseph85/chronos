// Provider management helpers. Key VALUES are write-only: the API only
// ever returns key_ids/key_count, and the client must never render or
// persist a key value.
export interface ProviderEntry {
  id: string; group: string; name: string; base_url: string;
  model?: string; position?: number; key_ids?: string[]; key_count?: number;
  [k: string]: unknown;
}

const SECRET_KEYS = ["key", "key_value", "api_key", "secret", "token"];

export function sanitizeProvider<T extends Record<string, unknown>>(e: T): T {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(e)) {
    if (SECRET_KEYS.includes(k.toLowerCase())) continue;
    out[k] = v;
  }
  return out as T;
}

// Render-safe text: asserts no secret-looking value leaks into HTML.
export function renderProvidersSafe(entries: ProviderEntry[]): string {
  const clean = entries.map(sanitizeProvider);
  return clean.map((e) =>
    `<div class="card"><b>${esc(String(e.name))}</b> <span class="muted">${esc(String(e.group))} · ${esc(String(e.base_url))} · keys:${Number(e.key_count ?? e.key_ids?.length ?? 0)}</span></div>`
  ).join("");
}

export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}
