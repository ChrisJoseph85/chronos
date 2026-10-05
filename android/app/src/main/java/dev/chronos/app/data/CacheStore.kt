package dev.chronos.app.data

import android.content.Context
import java.io.File

/**
 * Minimal offline cache (spec allows Room OR minimal cache): last-good JSON
 * payloads for events/nodes/briefing + timer summary, served read-only when
 * the server is down. Writes are blocked in that state, never queued.
 */
class CacheStore(ctx: Context) {
    private val dir = File(ctx.cacheDir, "chronos_offline").also { it.mkdirs() }

    fun put(name: String, json: String) {
        try {
            File(dir, "$name.json").writeText(json)
        } catch (_: Exception) { }
    }

    fun get(name: String): String? = try {
        File(dir, "$name.json").takeIf { it.exists() }?.readText()
    } catch (_: Exception) {
        null
    }
}
