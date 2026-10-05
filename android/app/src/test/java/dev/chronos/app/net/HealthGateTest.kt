package dev.chronos.app.net

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class HealthGateTest {
    @Test fun reachableAllowsWrites() = runTest {
        val g = HealthGate(probe = { true })
        assertTrue(g.refresh())
        assertTrue(g.writesAllowed())
    }

    @Test fun unreachableBlocksWrites() = runTest {
        val g = HealthGate(probe = { false })
        assertFalse(g.refresh())
        assertTrue(g.serverDown)
        assertFalse(g.writesAllowed())
    }

    @Test fun probeThrowMeansDown() = runTest {
        val g = HealthGate(probe = { throw RuntimeException("boom") })
        assertFalse(g.refresh())
        assertFalse(g.writesAllowed())
    }
}
