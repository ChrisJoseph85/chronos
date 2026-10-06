package com.chronos.net

/**
 * Server auto-discovery (spec §9). Manual URL entry always stays available.
 * Order: 127.0.0.1 -> device LAN /24 hosts, same port throughout
 * (editable, default 693). Per host: short-timeout GET /api/health, then an
 * authenticated probe with the SAVED instance key ONLY — never a pasted or
 * typed key at scan time (callers pass repo.apiKey). First healthy +
 * authorized host wins. Bounded and user-cancelable.
 */
class Discovery(val port: Int = 693, val timeoutMs: Int = 800) {

    interface Probe {
        fun healthy(url: String, timeoutMs: Int): Boolean
        fun authorized(url: String, key: String, timeoutMs: Int): Boolean
    }

    /** Candidate hosts in scan order. Localhost always first. */
    fun candidates(localIp: String?): List<String> {
        val out = mutableListOf("127.0.0.1")
        val prefix = subnet24(localIp)
        if (prefix != null) {
            for (i in 1..254) {
                val host = "$prefix.$i"
                if (host != localIp && host !in out) out.add(host)
            }
        }
        return out
    }

    fun subnet24(ip: String?): String? {
        if (ip == null) return null
        val parts = ip.split(".")
        if (parts.size != 4 || parts.any { it.toIntOrNull() !in 0..255 }) return null
        if (parts[0] == "127") return null
        return parts.take(3).joinToString(".")
    }

    fun scan(
        localIp: String?,
        savedKey: String,
        probe: Probe,
        isCancelled: () -> Boolean = { false },
        onProgress: (host: String) -> Unit = {},
    ): String? {
        if (savedKey.isEmpty()) return null
        for (host in candidates(localIp)) {
            if (isCancelled()) return null
            onProgress(host)
            val url = "http://$host:$port"
            try {
                if (!probe.healthy(url, timeoutMs)) continue
                if (probe.authorized(url, savedKey, timeoutMs)) return url
            } catch (_: Exception) {
                continue
            }
        }
        return null
    }
}
