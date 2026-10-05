package dev.chronos.app.net

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class KeyRedactionTest {
    private val key = "super-secret-instance-key"

    @Test fun authHeaderPresentOnAllRoutes() {
        val reqs = listOf(
            ApiRoutes.events("http://h", key, "a", "b"),
            ApiRoutes.nodes("http://h", key),
            ApiRoutes.briefing("http://h", key, "2026-10-05"),
            ApiRoutes.timerGet("http://h", key),
            ApiRoutes.timerStart("http://h", key, "l", "stopwatch", null, null, "android"),
            ApiRoutes.timerStop("http://h", key, "android", void = true),
            ApiRoutes.timerSummary("http://h", key),
            ApiRoutes.statsBreakdown("http://h", key, null, "a", "b"),
            ApiRoutes.say("http://h", key, "hi", null),
            ApiRoutes.providers("http://h", key),
        )
        for (r in reqs) assertEquals(key, r.header(ApiRoutes.KEY_HEADER))
    }

    @Test fun redactedLogNeverContainsKey() {
        val r = ApiRoutes.timerStop("http://h", key, "android", void = true)
        val log = with(ApiRoutes) { r.redactedLog() }
        assertFalse(log.contains(key))
        assertTrue(log.contains("/api/timer/stop"))
    }

    @Test fun voidFlagSerializedOnlyWhenTrue() {
        // Body is not logged anywhere; verify shape via content-length-safe peek is skipped:
        // instead assert the two requests differ in body size (void adds bytes).
        val keep = ApiRoutes.timerStop("http://h", key, "android", void = false)
        val void = ApiRoutes.timerStop("http://h", key, "android", void = true)
        assertTrue((void.body!!.contentLength()) > (keep.body!!.contentLength()))
        assertTrue(ApiRoutes.voice("http://h", key, File("x")).header(ApiRoutes.KEY_HEADER) == key)
    }

    @Test fun wsUrlSchemeMapped() {
        assertEquals("ws://h/ws", ApiRoutes.wsUrl("http://h"))
        assertEquals("wss://h/ws", ApiRoutes.wsUrl("https://h/"))
    }
}
