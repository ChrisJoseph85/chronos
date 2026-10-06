package com.chronos.timer

import com.chronos.api.ApiException
import com.chronos.api.ServerTooOld
import com.chronos.api.TimerApi
import com.chronos.api.TimerSession
import com.chronos.api.TimerStart
import com.chronos.store.SettingsRepo

/**
 * Timer state machine. The server is the source of truth; this mirrors it.
 *
 * THE OLD BUG: the card showed 3 modes but stopwatch was stuck selected and
 * nothing worked — selection never persisted, never changed request bodies,
 * never changed elapsed math. Here:
 *  - [selectMode] persists to prefs AND switches behavior immediately;
 *  - [startBody] differs per mode (stopwatch ignores target_ms; countdown
 *    requires a duration; pomodoro sends focus ms and walks cycles);
 *  - [view] computes elapsed differently per mode from a swappable clock.
 */
enum class TimerMode(val wire: String) {
    STOPWATCH("stopwatch"),
    COUNTDOWN("countdown"),
    POMODORO("pomodoro"),
    ;

    companion object {
        fun of(wire: String): TimerMode = entries.firstOrNull { it.wire == wire } ?: STOPWATCH
    }
}

enum class PomodoroPhase { FOCUS, BREAK }

/** Forced default preset 25/5x4 is always available, even with no server presets. */
data class PomodoroSpec(val focusMin: Int = 25, val breakMin: Int = 5, val cycles: Int = 4) {
    companion object {
        val DEFAULT_25_5x4 = PomodoroSpec(25, 5, 4)
    }

    val focusMs: Long get() = focusMin * 60_000L
    val breakMs: Long get() = breakMin * 60_000L
}

data class PomodoroState(
    val phase: PomodoroPhase,
    val cycle: Int, // 1-based focus index
    val cycles: Int,
    val phaseRemainingMs: Long,
    val focusElapsedMs: Long, // breaks excluded
    val done: Boolean,
)

/** What the home card renders. */
data class TimerView(
    val running: Boolean,
    val mode: TimerMode,
    /** Displayed elapsed (focus time; pomodoro breaks excluded from totals). */
    val displayMs: Long,
    /** Countdown/pomodoro-phase time left, null for stopwatch. */
    val remainingMs: Long?,
    val pomodoro: PomodoroState? = null,
    val label: String = "",
    /** Non-empty when the last action needs user attention (409, no duration...). */
    val status: String = "",
)

class TimerEngine(
    private val prefs: SettingsRepo,
    private val api: TimerApi,
    private val clock: Clock,
) {
    var mode: TimerMode
        get() = TimerMode.of(prefs.timerMode)
        private set(m) {
            prefs.timerMode = m.wire
        }

    /** Mode selector: persists AND switches behavior. Returns the idle view. */
    fun selectMode(m: TimerMode): TimerView {
        mode = m
        return view(null, clock.nowMs())
    }

    /** Countdown duration input (ms). Required before a countdown start. */
    var countdownDurationMs: Long = 25 * 60_000L

    /** Active pomodoro spec (from server presets row; forced 25/5x4 always offered). */
    var pomodoro: PomodoroSpec = PomodoroSpec.DEFAULT_25_5x4

    /** Server presets with the forced 25/5x4 prepended when absent. */
    fun presetsWithDefault(server: List<PomodoroSpec>): List<PomodoroSpec> {
        if (server.any { it == PomodoroSpec.DEFAULT_25_5x4 }) return server
        return listOf(PomodoroSpec.DEFAULT_25_5x4) + server
    }

    /** Refresh from server: a session started on ANY client displays live. */
    suspend fun refresh(): TimerView {
        val remote = try {
            api.timerGet()
        } catch (e: Exception) {
            return TimerView(false, mode, 0, null, label = "", status = netStatus(e))
        }
        return view(remote, clock.nowMs())
    }

    /** A WS `timer` frame drives the card exactly like a GET refresh. */
    fun onTimerFrame(session: TimerSession?): TimerView = view(session, clock.nowMs())

    /** Pure elapsed math per mode — the heart of the live tick. */
    fun view(session: TimerSession?, nowMs: Long): TimerView {
        if (session == null) return TimerView(false, mode, 0, null)
        return when (TimerMode.of(session.mode)) {
            TimerMode.STOPWATCH -> TimerView(
                true, TimerMode.STOPWATCH,
                displayMs = (nowMs - session.start_ms).coerceAtLeast(0),
                remainingMs = null, label = session.label,
            )
            TimerMode.COUNTDOWN -> {
                val total = session.target_ms ?: 0L
                val left = (total - (nowMs - session.start_ms)).coerceAtLeast(0)
                TimerView(true, TimerMode.COUNTDOWN, total - left, left, label = session.label)
            }
            TimerMode.POMODORO -> {
                val spec = specFor(session)
                val st = pomodoroState(session.start_ms, nowMs, spec)
                TimerView(
                    true, TimerMode.POMODORO, st.focusElapsedMs, st.phaseRemainingMs,
                    pomodoro = st, label = session.label,
                )
            }
        }
    }

    /** Walk focus/break cycles from the session start. Break after each focus except the last. */
    fun pomodoroState(startMs: Long, nowMs: Long, spec: PomodoroSpec): PomodoroState {
        var t = startMs
        var focusDone = 0L
        for (cycle in 1..spec.cycles) {
            val focusEnd = t + spec.focusMs
            if (nowMs < focusEnd) {
                return PomodoroState(PomodoroPhase.FOCUS, cycle, spec.cycles, focusEnd - nowMs, (nowMs - t) + focusDone, false)
            }
            focusDone += spec.focusMs
            t = focusEnd
            if (cycle < spec.cycles) {
                val breakEnd = t + spec.breakMs
                if (nowMs < breakEnd) {
                    return PomodoroState(PomodoroPhase.BREAK, cycle, spec.cycles, breakEnd - nowMs, focusDone, false)
                }
                t = breakEnd
            }
        }
        return PomodoroState(PomodoroPhase.FOCUS, spec.cycles, spec.cycles, 0, focusDone, true)
    }

    private fun specFor(session: TimerSession): PomodoroSpec {
        // Server start echoes target_ms = focus ms; match a known spec or fall back to selection.
        val focusMin = session.target_ms?.let { (it / 60_000L).toInt() }
        return if (focusMin != null && focusMin == pomodoro.focusMin) pomodoro
        else pomodoro
    }

    /** Build the start body for the CURRENT mode. Null = refuse with [TimerView.status]. */
    fun startBody(label: String, nodeId: String?): TimerStart? = when (mode) {
        // Stopwatch ignores target_ms — never send one.
        TimerMode.STOPWATCH -> TimerStart(label, TimerMode.STOPWATCH.wire, nodeId, null)
        // Countdown needs a duration input first.
        TimerMode.COUNTDOWN -> {
            if (countdownDurationMs <= 0) null
            else TimerStart(label, TimerMode.COUNTDOWN.wire, nodeId, countdownDurationMs)
        }
        TimerMode.POMODORO -> TimerStart(label, TimerMode.POMODORO.wire, nodeId, pomodoro.focusMs)
    }

    suspend fun start(label: String, nodeId: String?): TimerView {
        val body = startBody(label, nodeId)
            ?: return TimerView(false, mode, 0, null, status = "set a duration first")
        return try {
            val s = api.timerStart(body)
            view(s, clock.nowMs())
        } catch (e: ApiException) {
            if (e.code == 409) TimerView(false, mode, 0, null, status = "stop current first")
            else TimerView(false, mode, 0, null, status = netStatus(e))
        } catch (e: Exception) {
            TimerView(false, mode, 0, null, status = netStatus(e))
        }
    }

    /**
     * Stop rules (spec §4): clean stop keeps time; stop after ≥1 block
     * attempt sends void:true (session VOIDED, elapsed discarded).
     * Pre-v1.2 servers fall back to a plain stop ("server too old").
     */
    suspend fun stop(blockAttempts: Int, strictOn: Boolean): TimerView {
        val void = strictOn && blockAttempts > 0
        return try {
            val s = api.timerStop("android", void)
            val status = if (s.voided) "session voided" else "session kept"
            TimerView(false, mode, 0, null, status = status)
        } catch (e: ServerTooOld) {
            TimerView(false, mode, 0, null, status = "stopped (server too old for void)")
        } catch (e: ApiException) {
            TimerView(false, mode, 0, null, status = netStatus(e))
        } catch (e: Exception) {
            TimerView(false, mode, 0, null, status = netStatus(e))
        }
    }

    private fun netStatus(e: Exception): String = "server unreachable"
}

fun formatHms(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d:%02d".format(s / 3600, (s % 3600) / 60, s % 60)
}

fun formatMs(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "%02d:%02d".format(s / 60, s % 60)
}
