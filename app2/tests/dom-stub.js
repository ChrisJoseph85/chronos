// 60-line DOM stub: innerHTML parsing, selectors (#id .cls tag tag[attr] descendant), events.
export function makeDom() {
  const all = [];
  class El {
    constructor(tag, attrs = {}) {
      this.tag = tag.toLowerCase(); this.attrs = attrs; this.children = [];
      this.parent = null; this.listeners = {}; this.text = ""; this.value = ""; this.checked = false;
      this.disabled = false; this.style = {}; this._cls = new Set((attrs.class ?? "").split(" ").filter(Boolean));
      all.push(this);
    }
    get id() { return this.attrs.id ?? ""; }
    get dataset() {
      const o = {};
      for (const [k, v] of Object.entries(this.attrs)) if (k.startsWith("data-")) o[k.slice(5)] = v;
      return o;
    }
    get classList() {
      const s = this._cls;
      return { add: (c) => s.add(c), remove: (c) => s.delete(c), toggle: (c, f) => (f ?? !s.has(c) ? s.add(c) : s.delete(c)), contains: (c) => s.has(c) };
    }
    get textContent() { return this.children.map((c) => c.textContent).join("") + this.text; }
    set textContent(v) { this.children = []; this.text = String(v); }
    get innerHTML() { return ""; }
    set innerHTML(h) { this.children = []; this.text = ""; parseInto(this, h); }
    appendChild(c) { c.parent = this; this.children.push(c); return c; }
    append(...cs) { cs.forEach((c) => typeof c === "string" ? this.text += c : this.appendChild(c)); }
    addEventListener(t, f) { (this.listeners[t] ??= []).push(f); }
    removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] ?? []).filter((x) => x !== f); }
    click() { (this.listeners.click ?? []).forEach((f) => f({ target: this })); }
    querySelector(s) { return this.querySelectorAll(s)[0] ?? null; }
    querySelectorAll(s) {
      const parts = s.trim().split(/\s+/).map(parseSel);
      const out = [];
      const walk = (n) => { for (const c of n.children) { if (matchChain(c, parts)) out.push(c); walk(c); } };
      walk(this);
      return out;
    }
  }
  function parseSel(s) {
    const m = s.match(/^([a-z0-9]*)?(#[a-zA-Z0-9_-]+)?((?:\.[a-zA-Z0-9_-]+)*)(?:\[([a-z-]+)(?:="([^"]*)")?\])?$/i);
    return { tag: m[1] || null, id: m[2]?.slice(1) ?? null, cls: (m[3] ?? "").split(".").filter(Boolean), attr: m[4] ?? null, val: m[5] ?? null };
  }
  function matchOne(n, p) {
    if (p.tag && n.tag !== p.tag) return false;
    if (p.id && n.id !== p.id) return false;
    if (!p.cls.every((c) => n._cls.has(c))) return false;
    if (p.attr && !(p.attr in n.attrs)) return false;
    if (p.attr && p.val !== null && n.attrs[p.attr] !== p.val && n.dataset[p.attr] !== p.val) return false;
    return true;
  }
  function matchChain(n, parts) {
    if (!matchOne(n, parts[parts.length - 1])) return false;
    let anc = n.parent;
    for (let i = parts.length - 2; i >= 0; i--) {
      while (anc && !matchOne(anc, parts[i])) anc = anc.parent;
      if (!anc) return false;
      anc = anc.parent;
    }
    return true;
  }
  function parseInto(parent, h) {
    const re = /<(\/?)([a-z0-9]+)((?:\s+[a-z-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/gi;
    const stack = [parent];
    let m;
    while ((m = re.exec(h))) {
      if (m[4] !== undefined) { stack[stack.length - 1].text += m[4].trim(); continue; }
      const [_, close, tag, attrStr] = m;
      if (close) { if (stack.length > 1) stack.pop(); continue; }
      const attrs = {};
      for (const am of attrStr.matchAll(/([a-z-]+)(?:="([^"]*)")?/g)) attrs[am[1]] = am[2] ?? "";
      const el = new El(tag, attrs);
      stack[stack.length - 1].appendChild(el);
      if (!/^(input|br|img)$/i.test(tag)) stack.push(el);
    }
  }
  const byId = {};
  const document = {
    createElement: (t) => new El(t),
    getElementById: (id) => byId[id] ?? null,
    querySelector: (s) => root.querySelector(s),
    querySelectorAll: (s) => root.querySelectorAll(s),
    _reg(id, el) { byId[id] = el; },
  };
  const root = new El("body");
  return { El, document, root };
}
