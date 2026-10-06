// Breakdown math: server returns per-direct-child totals; client only
// sums + percentages for the drill view.
export interface BreakdownRow { node_id: string; title: string; kind: string; total_ms: number; }

export function summarizeBreakdown(rows: BreakdownRow[]): { total_ms: number; rows: (BreakdownRow & { pct: number })[] } {
  const total_ms = rows.reduce((a, r) => a + Math.max(0, r.total_ms || 0), 0);
  const out = rows.map((r) => ({ ...r, pct: total_ms > 0 ? (100 * r.total_ms) / total_ms : 0 }));
  out.sort((a, b) => b.total_ms - a.total_ms);
  return { total_ms, rows: out };
}

export function fmtDur(ms: number): string {
  const m = Math.floor(ms / 60000);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}h ${m % 60}m` : `${m}m`;
}
