package dev.chronos.app.net

import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class ServerDiscoveryTest {
    @Test fun localhostFirst() {
        val c = ServerDiscovery.candidates(693, "192.168.1.50")
        assertEquals("http://127.0.0.1:693", c.first())
        assertTrue(c.contains("http://192.168.1.1:693"))
        assertEquals(1 + 254, c.size)
    }

    @Test fun firstWin() = runTest {
        val order = mutableListOf<String>()
        val d = ServerDiscovery(
            healthCheck = { true },
            authCheck = { base, _ -> order.add(base); base.endsWith(".2:693") },
        )
        val hosts = listOf("http://127.0.0.1:693", "http://192.168.1.1:693", "http://192.168.1.2:693")
        assertEquals("http://192.168.1.2:693", d.findFirst(hosts, "k"))
        assertEquals(hosts, order) // stopped at winner, swept in order
    }

    @Test fun authProbeUsesSavedKey() = runTest {
        var seenKey: String? = null
        var seenBase: String? = null
        val d = ServerDiscovery(
            healthCheck = { true },
            authCheck = { base, key -> seenBase = base; seenKey = key; true },
        )
        val win = d.findFirst(listOf("http://127.0.0.1:693"), "SAVED-KEY-123")
        assertEquals("http://127.0.0.1:693", win)
        assertEquals("SAVED-KEY-123", seenKey)
        assertEquals("http://127.0.0.1:693", seenBase)
    }

    @Test fun cancelStopsSweep() = runTest {
        val d = ServerDiscovery(
            healthCheck = { delay(50); true },
            authCheck = { _, _ -> false },
        )
        val hosts = (1..50).map { "http://192.168.1.$it:693" }
        var checked = 0
        val job: Job = launch {
            d.findFirst(hosts, "k") { n, _, _ -> checked = n }
        }
        delay(75)
        job.cancel()
        job.join()
        assertTrue(checked < hosts.size)
    }

    @Test fun unreachableSkippedNotFailed() = runTest {
        val d = ServerDiscovery(
            healthCheck = { base ->
                if (base.contains(".1:")) throw java.io.IOException("down")
                true
            },
            authCheck = { _, _ -> true },
        )
        val win = d.findFirst(
            listOf("http://192.168.1.1:693", "http://192.168.1.2:693"),
            "k",
        )
        assertEquals("http://192.168.1.2:693", win)
    }
}
