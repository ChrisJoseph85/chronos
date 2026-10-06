// Chronos app2 — discovery client (UI-B owned).
//
// Inlinable: no imports, no network at import time. The factory below only
// defines functions; every fetch happens inside scan(), which is lazy
// (called from a user click handler) and fully guarded.
//
// Pattern mirrors Android §9 (Discovery.kt): candidates are 127.0.0.1 first,
// then the device LAN /24 hosts on the same port (default 693). Per host:
// short-timeout GET /api/health, then an authenticated probe with the SAVED
// instance key ONLY — never a typed/pasted key at scan time.
//
// UMD-lite: works when concatenated into the renderer bundle (sets
// globalThis.ChronosDiscovery) and under node --test via require().
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.ChronosDiscovery = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var DEFAULT_PORT = 693;
  var DEFAULT_TIMEOUT_MS = 800;

  // Prefix of a host's /24, or null when there is no LAN to scan
  // (missing/garbage IP, or loopback — mirrors Android subnet24()).
  function subnet24(ip) {
    if (ip == null) return null;
    var parts = String(ip).split('.');
    if (parts.length !== 4) return null;
    for (var i = 0; i < 4; i++) {
      var n = Number(parts[i]);
      if (parts[i] === '' || isNaN(n) || n < 0 || n > 255 || Math.floor(n) !== n) return null;
    }
    if (parts[0] === '127') return null;
    return parts[0] + '.' + parts[1] + '.' + parts[2];
  }

  // Candidate HOSTS (not URLs) in scan order. Localhost always first;
  // the device's own IP is skipped.
  function candidates(localIp) {
    var out = ['127.0.0.1'];
    var prefix = subnet24(localIp);
    if (prefix !== null) {
      for (var i = 1; i <= 254; i++) {
        var host = prefix + '.' + i;
        if (host !== localIp && out.indexOf(host) === -1) out.push(host);
      }
    }
    return out;
  }

  function fetchWithTimeout(fetchFn, url, opts, timeoutMs) {
    opts = opts || {};
    // AbortController may not exist in every host; fall back to a plain fetch.
    try {
      if (typeof AbortController === 'undefined') return fetchFn(url, opts);
      var ctrl = new AbortController();
      var timer = setTimeout(function () {
        try { ctrl.abort(); } catch (_) { /* ignore */ }
      }, timeoutMs);
      opts.signal = ctrl.signal;
      var p = fetchFn(url, opts);
      return p.then(
        function (res) { clearTimeout(timer); return res; },
        function (err) { clearTimeout(timer); throw err; }
      );
    } catch (e) {
      try { return fetchFn(url, opts); } catch (e2) { return Promise.reject(e2); }
    }
  }

  // Lazy scan. Zero network calls when savedKey is empty (returns null
  // without invoking fetchFn once). Options:
  //   { port, localIp, savedKey, fetchFn?, timeoutMs?,
  //     onProgress?(host), isCancelled?() }
  // Resolves to the winning base URL ("http://host:port") or null.
  // fetchFn defaults to globalThis.fetch, resolved AT CALL TIME (never at import).
  function scan(opts) {
    opts = opts || {};
    var port = opts.port != null ? opts.port : DEFAULT_PORT;
    var timeoutMs = opts.timeoutMs != null ? opts.timeoutMs : DEFAULT_TIMEOUT_MS;
    var savedKey = opts.savedKey || '';
    var onProgress = typeof opts.onProgress === 'function' ? opts.onProgress : function () {};
    var isCancelled = typeof opts.isCancelled === 'function' ? opts.isCancelled : function () { return false; };
    var fetchFn = opts.fetchFn || null;

    if (!savedKey) return Promise.resolve(null);
    if (!fetchFn) {
      try {
        fetchFn = (typeof globalThis !== 'undefined' && globalThis.fetch) || null;
      } catch (_) { fetchFn = null; }
    }
    if (!fetchFn) return Promise.resolve(null);

    var hosts = candidates(opts.localIp);
    var idx = 0;

    function step() {
      if (idx >= hosts.length) return Promise.resolve(null);
      if (isCancelled()) return Promise.resolve(null);
      var host = hosts[idx++];
      try { onProgress(host); } catch (_) { /* ignore */ }
      var base = 'http://' + host + ':' + port;
      var healthy;
      try {
        healthy = fetchWithTimeout(fetchFn, base + '/api/health', { method: 'GET' }, timeoutMs);
      } catch (e) {
        return step();
      }
      return healthy.then(
        function (res) {
          if (!res || !res.ok) return step();
          var authed;
          try {
            authed = fetchWithTimeout(
              fetchFn, base + '/api/settings',
              { method: 'GET', headers: { 'X-Chronos-Key': savedKey } },
              timeoutMs
            );
          } catch (e) {
            return step();
          }
          return authed.then(
            function (res2) {
              if (res2 && res2.ok) return base;
              return step();
            },
            function () { return step(); }
          );
        },
        function () { return step(); }
      );
    }

    return step();
  }

  return {
    DEFAULT_PORT: DEFAULT_PORT,
    DEFAULT_TIMEOUT_MS: DEFAULT_TIMEOUT_MS,
    subnet24: subnet24,
    candidates: candidates,
    scan: scan,
  };
});
