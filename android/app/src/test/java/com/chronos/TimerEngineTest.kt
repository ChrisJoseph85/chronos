package com.chronos

import com.chronos.api.ApiException
import com.chronos.api.TimerApi
import com.chronos.api.TimerPreset
import com.chronos.api.TimerSession
import com.chronos.api.TimerStart
import com.chronos.store.MemoryPrefs
import com.chronos.timer.Clock
import com.chronos.timer.FakeClock
import com.chronos.timer.PomodoroPhase
import com.chronos.timer.PomodoroSpec
import com.chronos.timer.TimerEngine
import com.chronos.timer.TimerMode
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Regression net for THE BUG THAT KILLED THE OLD APP (mode selector stuck on
 * stopwatch, nothing worked): every mode must persist, switch behavior,
 * tick live, and send the correct request bodies — proven here with a fake
 * clock (advance time, assert displayed elapsed) and a fake API.
 */
class FakeTimerApi : TimerApi {
    var running: TimerSession? = null
    var starts = 0
    var lastStart: TimerStart? = null
    var stops = mutableListOf<Pair<String, Boolean>>()
    var presets: List<TimerPreset> = emptyList()

    override suspend fun timerGet(): TimerSession? = running

    override suspend fun timerStart(body: TimerStart): TimerSession {
        if (running != null) throw ApiException(409, "timer running", "timer running")
        starts++
        lastStart = body
        val s = TimerSession(
            id = "s$starts", label = body.label, mode = body.mode,
            target_ms = body.target_ms, start_ms = FakeNow.now, source = body.source,
        )
        running = s
        return s
    }

    override suspend fun timerStop(source: String, void: Boolean): TimerSession {
        stops.add(source to void)
        val s = (running ?: TimerSession(id = "none")).copy(end_ms = FakeNow.now, voided = void)
        running = null
        return s
    }

    override suspend fun timerPresets(): List<TimerPreset> = presets
}

object FakeNow {
    var now: Long = 0
}

class TimerEngineTest {
    private lateinit var prefs: MemoryPrefs
    private lateinit var api: FakeTimerApi
    private lateinit var clock: FakeClock
    private lateinit var engine: TimerEngine

    @Before
    fun setUp() {
        prefs = MemoryPrefs()
        api = FakeTimerApi()
        FakeNow.now = 0
        clock = FakeClock(0)
        engine = TimerEngine(prefs, api, clock)
    }

    private fun syncFakeNow() {
        FakeNow.now = clock.nowMs()
    }

    @Test
    fun modeSelectorPersists() {
        engine.selectMode(TimerMode.POMODORO)
        assertEquals("pomodoro", prefs.timerMode)
        // A fresh engine (e.g. recreated card) reads the persisted mode.
        assertEquals(TimerMode.POMODORO, TimerEngine(prefs, api, clock).mode)
    }

    @Test
    fun modeSwitchChangesRequestBody() = runBlocking {
        syncFakeNow()
        // Stopwatch: target_ms MUST be absent (server ignores it).
        engine.selectMode(TimerMode.STOPWATCH)
        engine.start("a", null)
        assertEquals("stopwatch", api.lastStart!!.mode)
        assertNull(api.lastStart!!.target_ms)
        engine.stop(0, true)

        // Countdown: target_ms == chosen duration.
        engine.selectMode(TimerMode.COUNTDOWN)
        engine.countdownDurationMs = 10 * 60_000L
        engine.start("b", null)
        assertEquals("countdown", api.lastStart!!.mode)
        assertEquals(10 * 60_000L, api.lastStart!!.target_ms)
        engine.stop(0, true)

        // Pomodoro: target_ms == focus ms.
        engine.selectMode(TimerMode.POMODORO)
        engine.pomodoro = PomodoroSpec(25, 5, 4)
        engine.start("c", "node1")
        assertEquals("pomodoro", api.lastStart!!.mode)
        assertEquals(25 * 60_000L, api.lastStart!!.target_ms)
        assertEquals("node1", api.lastStart!!.node_id)
    }

    @Test
    fun stopwatchCountsUpLive() = runBlocking {
        engine.selectMode(TimerMode.STOPWATCH)
        syncFakeNow()
        val started = engine.start("work", null)
        assertTrue(started.running)
        assertEquals(0, started.displayMs)

        // Advance time: displayed elapsed must follow the clock.
        clock.advance(61_000)
        syncFakeNow()
        val live = engine.refresh()
        assertTrue(live.running)
        assertEquals(61_000, live.displayMs)
        assertNull(live.remainingMs)
    }

    @Test
    fun countdownNeedsDurationThenCountsDown() = runBlocking {
        engine.selectMode(TimerMode.COUNTDOWN)
        engine.countdownDurationMs = 0
        val refused = engine.start("x", null)
        assertFalse(refused.running)
        assertEquals("set a duration first", refused.status)
        assertEquals(0, api.starts) // no request sent

        engine.countdownDurationMs = 25 * 60_000L
        syncFakeNow()
        engine.start("x", null)
        clock.advance(60_000)
        syncFakeNow()
        val live = engine.refresh()
        assertTrue(live.running)
        assertEquals(24 * 60_000L, live.remainingMs)
        assertEquals(60_000, live.displayMs)
    }

    @Test
    fun pomodoroRunsFocusBreakCycles() {
        engine.selectMode(TimerMode.POMODORO)
        engine.pomodoro = PomodoroSpec(25, 5, 4)
        val start = 1_000_000L

        var st = engine.pomodoroState(start, start + 24 * 60_000L, engine.pomodoro)
        assertEquals(PomodoroPhase.FOCUS, st.phase)
        assertEquals(1, st.cycle)
        assertEquals(60_000L, st.phaseRemainingMs)
        assertEquals(24 * 60_000L, st.focusElapsedMs)
        assertFalse(st.done)

        st = engine.pomodoroState(start, start + 26 * 60_000L, engine.pomodoro)
        assertEquals(PomodoroPhase.BREAK, st.phase)
        assertEquals(1, st.cycle)
        assertEquals(25 * 60_000L, st.focusElapsedMs) // breaks excluded

        st = engine.pomodoroState(start, start + 31 * 60_000L, engine.pomodoro)
        assertEquals(PomodoroPhase.FOCUS, st.phase)
        assertEquals(2, st.cycle)

        // Full 25/5x4 = 4*25 + 3*5 = 115 min; after that the set is done.
        st = engine.pomodoroState(start, start + 115 * 60_000L + 1, engine.pomodoro)
        assertTrue(st.done)
        assertEquals(4 * 25 * 60_000L, st.focusElapsedMs)
    }

    @Test
    fun forcedPresetAlwaysOffered() {
        val withDefault = engine.presetsWithDefault(emptyList())
        assertTrue(withDefault.contains(PomodoroSpec.DEFAULT_25_5x4))
        assertEquals(PomodoroSpec(25, 5, 4), withDefault.first())

        val custom = listOf(PomodoroSpec(50, 10, 2))
        val merged = engine.presetsWithDefault(custom)
        assertEquals(2, merged.size)
        assertEquals(PomodoroSpec.DEFAULT_25_5x4, merged.first())

        // No duplicate when the server already ships 25/5x4.
        val dup = engine.presetsWithDefault(listOf(PomodoroSpec(25, 5, 4)))
        assertEquals(1, dup.size)
    }

    @Test
    fun sessionStartedElsewhereDisplaysLive() = runBlocking {
        // Another client started a stopwatch 2 minutes ago.
        api.running = TimerSession(id = "remote", mode = "stopwatch", label = "desk", start_ms = 0)
        clock.t = 120_000
        val v = engine.refresh()
        assertTrue(v.running)
        assertEquals(TimerMode.STOPWATCH, v.mode)
        assertEquals(120_000, v.displayMs)
        assertEquals("desk", v.label)
    }

    @Test
    fun wsTimerFrameDrivesCard() {
        val s = TimerSession(id = "ws", mode = "countdown", start_ms = 0, target_ms = 60_000)
        val v = engine.onTimerFrame(s)
        clock.t = 10_000
        val v2 = engine.onTimerFrame(s)
        assertTrue(v2.running)
        assertEquals(50_000L, v2.remainingMs)
        // Null frame (remote stop) clears the card.
        assertFalse(engine.onTimerFrame(null).running)
        assertTrue(v.running)
    }

    @Test
    fun secondStartShows409Message() = runBlocking {
        engine.selectMode(TimerMode.STOPWATCH)
        syncFakeNow()
        engine.start("one", null)
        val second = engine.start("two", null)
        assertFalse(second.running)
        assertEquals("stop current first", second.status)
    }

    @Test
    fun cleanStopKeepsTime() = runBlocking {
        engine.selectMode(TimerMode.STOPWATCH)
        syncFakeNow()
        engine.start("keep", null)
        val v = engine.stop(blockAttempts = 0, strictOn = true)
        assertEquals(1, api.stops.size)
        assertEquals("android" to false, api.stops.first()) // void:false -> kept
        assertEquals("session kept", v.status)
    }

    @Test
    fun stopAfterBlockAttemptVoids() = runBlocking {
        engine.selectMode(TimerMode.STOPWATCH)
        syncFakeNow()
        engine.start("doomed", null)
        val v = engine.stop(blockAttempts = 3, strictOn = true)
        assertEquals("android" to true, api.stops.first()) // void:true -> VOIDED
        assertEquals("session voided", v.status)
    }

    @Test
    fun strictOffNeverVoids() = runBlocking {
        engine.selectMode(TimerMode.STOPWATCH)
        syncFakeNow()
        engine.start("free", null)
        engine.stop(blockAttempts = 5, strictOn = false)
        assertEquals("android" to false, api.stops.first())
    }
}
