package com.chronos.timer

/** Swappable clock: system in prod, fake in unit tests. */
interface Clock {
    fun nowMs(): Long
}

class SystemClock : Clock {
    override fun nowMs(): Long = System.currentTimeMillis()
}

/** Test clock: advance time deterministically, assert displayed elapsed. */
class FakeClock(var t: Long = 0) : Clock {
    override fun nowMs(): Long = t
    fun advance(ms: Long) {
        t += ms
    }
}
