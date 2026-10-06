// Saved-key-only probe over fetch. Order: 127.0.0.1 → LAN /24. Port 693.
window.ChronosDiscover = (() => {
  const PORT = 693;
  async function probe(host, key, ms = 800) {
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), ms);
      const r = await fetch(`http://${host}:${PORT}/api/health`, { signal: c.signal });
      clearTimeout(t);
      return r.ok;
    } catch { return false; }
  }
  async function find(key, lan = "192.168.1") {
    if (await probe("127.0.0.1", key)) return "http://127.0.0.1:8080";
    for (let i = 1; i < 255; i++) {
      if (await probe(`${lan}.${i}`, key, 300)) return `http://${lan}.${i}:8080`;
    }
    return null;
  }
  return { PORT, find };
})();
