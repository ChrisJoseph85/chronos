package dev.chronos.app.shield

import org.junit.Assert.*
import org.junit.Test

class ShieldManagerTest {
    class FakeStore : ShieldManager.ShieldStore {
        override var attempts: Int = 0
        override var strict: Boolean = true
    }

    @Test fun cleanStopKeepsTime() {
        val m = ShieldManager(FakeStore())
        m.onSessionStart()
        assertFalse(m.stopVoidFlag())
    }

    @Test fun stopAfterAttemptVoids() {
        val m = ShieldManager(FakeStore())
        m.onSessionStart()
        m.onBlockedAppOpened()
        m.onBlockedAppOpened()
        assertEquals(2, m.attempts())
        assertTrue(m.stopVoidFlag())
    }

    @Test fun strictOffAlwaysKeeps() {
        val s = FakeStore().also { it.strict = false }
        val m = ShieldManager(s)
        m.onSessionStart()
        m.onBlockedAppOpened()
        assertFalse(m.stopVoidFlag())
        assertFalse(m.blockingActive(sessionRunning = true))
    }

    @Test fun blockingRequiresRunningSession() {
        val m = ShieldManager(FakeStore())
        assertFalse(m.blockingActive(sessionRunning = false))
        assertTrue(m.blockingActive(sessionRunning = true))
    }

    @Test fun newSessionResetsCounter() {
        val m = ShieldManager(FakeStore())
        m.onBlockedAppOpened()
        m.onSessionStart()
        assertEquals(0, m.attempts())
    }
}
