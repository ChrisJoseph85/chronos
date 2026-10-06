// Discovery target list (pure). Probing itself lives in renderer (fetch).
export const DISCOVERY_PORT = 693;

export function discoveryTargets() {
  const targets = ["127.0.0.1"];
  for (let i = 1; i < 255; i++) targets.push(`192.168.1.${i}`);
  return { port: DISCOVERY_PORT, targets };
}
