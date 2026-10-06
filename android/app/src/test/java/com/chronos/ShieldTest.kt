package com.chronos

import com.chronos.shield.AttemptCounter
import com.chronos.shield.ShieldLogic
import org.junit.Assert.*
import org.junit.Test

class ShieldTest {
    @Test
    fun strictDefaultsOn() {
        assertTrue(ShieldLogic.STRICT_DEFAULT)
        assertTrue(com.chronos.store.MemoryPrefs().strictShield)
    }

    @Test
    fun voidRule() {
        // Clean stop keeps time.
        assertFalse(ShieldLogic.shouldVoidOnStop(strictOn = true, blockAttempts = 0))
        // Stop after >=1 attempt voids.
        assertTrue(ShieldLogic.shouldVoidOnStop(strictOn = true, blockAttempts = 1))
        assertTrue(ShieldLogic.shouldVoidOnStop(strictOn = true, blockAttempts = 40))
        // Strict OFF never voids.
        assertFalse(ShieldLogic.shouldVoidOnStop(strictOn = false, blockAttempts = 9))
    }

    @Test
    fun rationaleVerbatim() {
        assertEquals(
            "used only to detect a blocked app opening; no usage statistics are collected, stored, or sent anywhere.",
            ShieldLogic.RATIONALE,
        )
    }

    @Test
    fun attemptCounterPerSession() {
        val c = AttemptCounter()
        assertEquals(0, c.attempts)
        c.trip()
        c.trip()
        assertEquals(2, c.attempts)
        c.reset()
        assertEquals(0, c.attempts)
    }

    @Test
    fun blockedOpened() {
        val block = setOf("com.evil.game")
        assertTrue(ShieldLogic.blockedOpened(block, "com.evil.game"))
        assertFalse(ShieldLogic.blockedOpened(block, "com.good.reader"))
        assertFalse(ShieldLogic.blockedOpened(block, null))
    }
}
