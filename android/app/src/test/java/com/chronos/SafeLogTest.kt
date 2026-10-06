package com.chronos

import com.chronos.api.SafeLog
import org.junit.Assert.*
import org.junit.Test

/** The instance key must NEVER reach any log output. Test-enforced. */
class SafeLogTest {
    @Test
    fun keyNeverLogged() {
        val key = "ck-live-super-secret-key-12345"
        val captured = mutableListOf<String>()
        val old = SafeLog.sink
        SafeLog.sink = { _, msg -> captured.add(msg) }
        try {
            SafeLog.d("api", "POST /api/say with key=$key body={...}", key)
            SafeLog.d("ws", "connect https://host/ws key=$key", key)
            SafeLog.d("api", "GET /api/health") // no secrets at all
        } finally {
            SafeLog.sink = old
        }
        assertEquals(3, captured.size)
        for (line in captured) {
            assertFalse("LEAKED KEY IN: $line", line.contains(key))
        }
        assertTrue(captured[0].contains("***"))
        assertTrue(captured[2].contains("GET /api/health"))
    }

    @Test
    fun redactHandlesEdgeCases() {
        assertEquals("a***b", SafeLog.redact("axyzb", listOf("xyz")))
        assertEquals("plain", SafeLog.redact("plain", listOf("")))
        assertEquals("plain", SafeLog.redact("plain", emptyList()))
    }
}
