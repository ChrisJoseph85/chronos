// Chronos web API client. Key lives in localStorage; NEVER logged.
export const KEY_STORAGE = "chronos.key";
export const BASE_STORAGE = "chronos.base";
export const HOSTS_STORAGE = "chronos.hosts";

export function authHeaders(key: string): Record<string, string> {
  return { "X-Chronos-Key": key, "Content-Type": "application/json" };
}

export function getStoredKey(store: Pick<Storage, "getItem"> = localStorage): string | null {
  const v = store.getItem(KEY_STORAGE);
  return v && v.length > 0 ? v : null;
}

export function requireKey(key: string | null): string {
  if (!key) throw new Error("missing-key: set server URL + instance key in Settings");
  return key;
}

export function joinUrl(base: string, path: string): string {
  return base.replace(/\/+$/, "") + path;
}

export type FetchLike = typeof fetch;

export interface SayResponse {
  intent?: string;
  tool_calls?: unknown[];
  proposal_id?: string | null;
  committed?: boolean;
  events?: unknown[];
  message?: string;
  question?: string | null;
}

// Proposal flow: /api/say never silently commits ambiguous input.
export function needsProposal(r: SayResponse): boolean {
  return !r.committed && !!r.proposal_id;
}

export function wsProposalAction(ws: { send(d: string): void }, kind: "accept" | "reject" | "skip", proposal_id: string): void {
  ws.send(JSON.stringify({ [kind]: true, proposal_id }));
}

// Void logic: first stop keeps time (void:false); void only after an explicit
// second user-confirmed attempt (focus-shield cost is intentional).
export function decideStopVoid(alreadyStoppedOnce: boolean, userConfirmedVoid: boolean): boolean {
  return alreadyStoppedOnce && userConfirmedVoid;
}

export function stopPayload(source: string, doVoid: boolean): { source: string; void?: boolean } {
  return doVoid ? { source, void: true } : { source };
}

export class ChronosClient {
  constructor(public base: string, public key: string, private f: FetchLike = fetch) {}
  private headers(): Record<string, string> {
    return authHeaders(this.key);
  }
  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    requireKey(this.key);
    const res = await this.f(joinUrl(this.base, path), {
      method,
      headers: this.headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 401) throw new Error("auth: Missing/Invalid key");
    if (res.status === 409) {
      const t = await res.text();
      throw new Error("conflict: " + t);
    }
    if (!res.ok) throw new Error(`http ${res.status}: ${await res.text()}`);
    return (await res.json()) as T;
  }
  get<T>(p: string): Promise<T> { return this.req<T>("GET", p); }
  post<T>(p: string, b?: unknown): Promise<T> { return this.req<T>("POST", p, b); }
  put<T>(p: string, b?: unknown): Promise<T> { return this.req<T>("PUT", p, b); }
  del<T>(p: string): Promise<T> { return this.req<T>("DELETE", p); }
  say(text: string, device_id = "web"): Promise<SayResponse> {
    return this.post<SayResponse>("/api/say", { text, device_id });
  }
  health(timeoutMs = 4000): Promise<{ status: string }> {
    const c = new AbortController();
    const t = setTimeout(() => c.abort(), timeoutMs);
    return this.f(joinUrl(this.base, "/api/health"), { signal: c.signal })
      .then(async (r) => {
        clearTimeout(t);
        if (!r.ok) throw new Error("down");
        return (await r.json()) as { status: string };
      })
      .catch((e) => { clearTimeout(t); throw e; });
  }
  // Saved-key-only probe: health is open, but data calls always send the key.
  async probe(timeoutMs = 4000): Promise<"ok" | "down"> {
    try { const h = await this.health(timeoutMs); return h.status === "ok" ? "ok" : "down"; }
    catch { return "down"; }
  }
}
