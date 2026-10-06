package com.chronos.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import com.chronos.ChronosApp
import com.chronos.api.TimerSession
import com.chronos.store.SettingsRepo
import com.chronos.timer.PomodoroSpec
import com.chronos.timer.SystemClock
import com.chronos.timer.TimerEngine
import com.chronos.timer.TimerMode
import com.chronos.timer.formatHms
import com.chronos.timer.formatMs
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Timer card: mode selector (stopwatch | countdown | pomodoro) that persists
 * and actually switches behavior, target picker (node id), strict-shield
 * toggle (default ON), presets row (25/5x4 always), live elapsed tick.
 * A session running ANYWHERE shows live with an End button; a second start
 * surfaces the server 409 as "stop current first".
 */
class HomeFragment : ScopedFragment(), MainActivity.TickListener {
    private lateinit var engine: TimerEngine
    private lateinit var prefs: SettingsRepo
    private lateinit var elapsedText: TextView
    private lateinit var statusText: TextView
    private lateinit var durationInput: EditText
    private lateinit var targetInput: EditText
    private lateinit var labelInput: EditText
    private lateinit var presetRow: android.widget.LinearLayout
    private var running = false
    private var attempts = 0

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        prefs = (requireActivity().application as ChronosApp).prefs
        val app = requireActivity().application as ChronosApp
        engine = TimerEngine(prefs, app.api(), SystemClock())

        return col(requireContext()) {
            title("Timer")

            val modes = RadioGroup(context).apply { orientation = RadioGroup.HORIZONTAL }
            val rbS = RadioButton(context).apply { text = "stopwatch"; id = View.generateViewId() }
            val rbC = RadioButton(context).apply { text = "countdown"; id = View.generateViewId() }
            val rbP = RadioButton(context).apply { text = "pomodoro"; id = View.generateViewId() }
            modes.addView(rbS)
            modes.addView(rbC)
            modes.addView(rbP)
            addView(modes)
            when (engine.mode) {
                TimerMode.STOPWATCH -> modes.check(rbS.id)
                TimerMode.COUNTDOWN -> modes.check(rbC.id)
                TimerMode.POMODORO -> modes.check(rbP.id)
            }
            modes.setOnCheckedChangeListener { _, id ->
                // The old bug: selection never persisted/switched. This does both.
                val m = when (id) {
                    rbC.id -> TimerMode.COUNTDOWN
                    rbP.id -> TimerMode.POMODORO
                    else -> TimerMode.STOPWATCH
                }
                scope.launch {
                    engine.selectMode(m)
                    durationInput.visibility = if (m == TimerMode.COUNTDOWN) View.VISIBLE else View.GONE
                    presetRow.visibility = if (m == TimerMode.POMODORO) View.VISIBLE else View.GONE
                    refresh()
                }
            }

            durationInput = edit("countdown minutes", "25").apply {
                visibility = if (engine.mode == TimerMode.COUNTDOWN) View.VISIBLE else View.GONE
            }
            labelInput = edit("label (optional)")
            targetInput = edit("target node id (optional)")
            presetRow = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.HORIZONTAL
                visibility = if (engine.mode == TimerMode.POMODORO) View.VISIBLE else View.GONE
            }
            addView(presetRow)

            switchRow("strict shield (default ON)", prefs.strictShield) {
                prefs.strictShield = it
            }

            elapsedText = text("idle").apply { textSize = 28f }
            statusText = text("")

            row(
                android.widget.Button(context).apply {
                    text = "Start"
                    setOnClickListener { start() }
                },
                android.widget.Button(context).apply {
                    text = "End"
                    setOnClickListener { stop() }
                },
            )
        }
    }

    override fun onResume() {
        super.onResume()
        loadPresets()
        refresh()
    }

    private fun loadPresets() {
        val act = activity ?: return
        if ((act as MainActivity).readOnly) return
        scope.launch {
            try {
                val app = act.application as ChronosApp
                val server = withContext(kotlinx.coroutines.Dispatchers.IO) { app.api().timerPresets() }
                    .map { PomodoroSpec(it.focus_minutes, it.break_minutes, it.cycles) }
                val all = engine.presetsWithDefault(server)
                presetRow.removeAllViews()
                for (p in all) {
                    presetRow.addView(
                        android.widget.Button(context).apply {
                            text = "${p.focusMin}/${p.breakMin}x${p.cycles}"
                            setOnClickListener {
                                engine.pomodoro = p
                                statusText.text = "preset ${p.focusMin}/${p.breakMin}x${p.cycles}"
                            }
                        },
                    )
                }
            } catch (_: Exception) {
            }
        }
    }

    private fun start() {
        val act = activity as? MainActivity ?: return
        if (act.blockedWrite()) return
        val mins = durationInput.text.toString().toIntOrNull()
        if (engine.mode == TimerMode.COUNTDOWN) {
            if (mins == null || mins <= 0) {
                statusText.text = "set a duration first"
                return
            }
            engine.countdownDurationMs = mins * 60_000L
        }
        val label = labelInput.text.toString().ifEmpty { engine.mode.wire }
        val node = targetInput.text.toString().ifBlank { null }
        scope.launch {
            val v = engine.start(label, node)
            running = v.running
            attempts = 0
            render(v.displayMs, v.remainingMs, v.label, v.status)
        }
    }

    private fun stop() {
        val act = activity as? MainActivity ?: return
        if (act.blockedWrite()) return
        scope.launch {
            // Stop after >=1 block attempt sends void:true (spec §4).
            val v = engine.stop(attempts, (act.application as ChronosApp).prefs.strictShield)
            running = false
            render(0, null, "", v.status)
        }
    }

    private fun refresh() {
        scope.launch {
            val v = engine.refresh()
            running = v.running
            render(v.displayMs, v.remainingMs, v.label, v.status)
        }
    }

    /** Remote session (other client, or WS timer frame) displays live. */
    fun onRemoteTimer(session: TimerSession?) {
        scope.launch {
            val v = engine.onTimerFrame(session)
            running = v.running
            render(v.displayMs, v.remainingMs, v.label, v.status)
        }
    }

    override fun onTick() {
        val act = activity as? MainActivity ?: return
        if (act.tickRunning) {
            running = true
            val left = act.tickRemainingMs
            render(act.tickDisplayMs, if (left < 0) null else left, act.tickLabel, "")
        }
    }

    private fun render(displayMs: Long, remainingMs: Long?, label: String, status: String) {
        if (!isAdded) return
        elapsedText.text = if (running) {
            if (remainingMs != null) "${formatHms(displayMs)}  (${formatMs(remainingMs)} left)"
            else formatHms(displayMs)
        } else "idle"
        if (label.isNotEmpty()) elapsedText.text = "$label — ${elapsedText.text}"
        if (status.isNotEmpty()) statusText.text = status
    }
}
