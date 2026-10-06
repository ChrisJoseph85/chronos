package com.chronos

import com.chronos.net.Discovery
import org.junit.Assert.*
import org.junit.Test

class DiscoveryTest {
    private val savedKey = "SAVED-KEY"
    private val typedKey = "TYPED-KEY"

    private inner class ScriptedProbe(
        val healthyHosts: Set<String>,
        val authedHosts: Set<String>,
    ) : Discovery.Probe {
        val order = mutableListOf<String>()
        val keysSeen = mutableListOf<String>()
        override fun healthy(url: String, timeoutMs: Int): Boolean {
            order.add(url)
            return healthyHosts.any { url.contains(it) }
        }

        override fun authorized(url: String, key: String, timeoutMs: Int): Boolean {
            keysSeen.add(key)
            return authedHosts.any { url.contains(it) }
        }
    }

    @Test
    fun localhostFirstThenSlash24InOrder() {
        val c = Discovery(693).candidates("192.168.7.50")
        assertEquals("127.0.0.1", c.first())
        assertTrue(c.contains("192.168.7.1"))
        assertTrue(c.contains("192.168.7.254"))
        assertFalse(c.contains("192.168.7.50")) // self skipped
        assertFalse(c.any { it.startsWith("192.168.8.") })
        assertEquals(1 + 253, c.size) // localhost + full /24 minus self
    }

    @Test
    fun noLocalIpMeansLocalhostOnly() {
        assertEquals(listOf("127.0.0.1"), Discovery().candidates(null))
    }

    @Test
    fun firstHealthyAuthorizedWinsAndUsesSavedKeyOnly() {
        val probe = ScriptedProbe(
            healthyHosts = setOf("127.0.0.1", "192.168.7.9"),
            authedHosts = setOf("192.168.7.9"),
        )
        val found = Discovery(693).scan("192.168.7.50", savedKey, probe)
        assertEquals("http://192.168.7.9:693", found)
        // Localhost probed first.
        assertTrue(probe.order.first().contains("127.0.0.1"))
        // The probe ONLY ever saw the saved key — never a typed/pasted one.
        assertTrue(probe.keysSeen.isNotEmpty())
        assertTrue(probe.keysSeen.all { it == savedKey })
        assertFalse(probe.keysSeen.contains(typedKey))
    }

    @Test
    fun customPortThroughout() {
        val probe = ScriptedProbe(setOf("127.0.0.1"), setOf("127.0.0.1"))
        assertEquals("http://127.0.0.1:8080", Discovery(8080).scan(null, savedKey, probe))
    }

    @Test
    fun nothingFoundMeansNull() {
        val probe = ScriptedProbe(emptySet(), emptySet())
        assertNull(Discovery().scan("10.0.0.5", savedKey, probe))
    }

    @Test
    fun emptySavedKeyNeverScans() {
        val probe = ScriptedProbe(setOf("127.0.0.1"), setOf("127.0.0.1"))
        assertNull(Discovery().scan(null, "", probe))
        assertTrue(probe.order.isEmpty())
    }

    @Test
    fun cancelStopsScan() {
        val probe = ScriptedProbe(setOf("192.168.7.200"), setOf("192.168.7.200"))
        var calls = 0
        val found = Discovery().scan("192.168.7.50", savedKey, probe, isCancelled = { ++calls > 3 })
        assertNull(found)
        assertTrue(probe.order.size <= 4)
    }

    @Test
    fun badIpsRejected() {
        val d = Discovery()
        assertNull(d.subnet24(null))
        assertNull(d.subnet24("not-an-ip"))
        assertNull(d.subnet24("127.0.0.1"))
        assertEquals("10.0.0", d.subnet24("10.0.0.9"))
    }
}
