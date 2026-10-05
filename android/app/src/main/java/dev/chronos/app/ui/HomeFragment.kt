package dev.chronos.app.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import androidx.fragment.app.Fragment
import dev.chronos.app.ChronosApp
import dev.chronos.app.net.ApiException
import dev.chronos.app.net.NodeInfo
import dev.chronos.app.shield.ShieldPrefsStore
import dev.chronos.app.timer.TimerService
import dev.chronos.app.timer.TimerState
import kotlinx.coroutines.launch

/**
 * Home: mode selector (stopwatch|countdown|pomodoro), target picker
 * (project/tag/task via nodes API), strict-shield toggle (default ON),
 * presets row (25/5x4 always). A session running ANYWHERE shows live with
 * elapsed + End. Second start -> server 409 -> "stop current first".
 */
class HomeFragment : Fragment() {
    private val app get() = requireContext().applicationContext as ChronosApp
    private lateinit var sessionLine: TextView
    private lateinit var statusLine: TextView
    private lateinit var modeGroup: RadioGroup
    private lateinit var targetSpinner: Spinner
    private lateinit var strictSwitch: Switch
    private lateinit var presetsRow: LinearLayout
    private var nodes: List<NodeInfo> = emptyList()

    override fun onCreateView(inf: LayoutInflater, c: ViewGroup?, s: Bundle?): View {
        val root = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        modeGroup = RadioGroup(requireContext()).apply { orientation = RadioGroup.HORIZONTAL }
        listOf("stopwatch", "countdown", "pomodoro").forEach {
            modeGroup.addView(RadioButton(requireContext()).apply {
                text = it
                tag = it
                if (it == "stopwatch") isChecked = true
            })
        }
        root.addView(modeGroup)
        targetSpinner = Spinner(requireContext())
        root.addView(targetSpinner)
        strictSwitch = Switch(requireContext()).apply {
            text = "Strict shield"
            isChecked = ShieldPrefsStore(requireContext()).strict
        }
        strictSwitch.setOnCheckedChangeListener { _, on ->
            ShieldPrefsStore(requireContext()).strict = on
        }
        root.addView(strictSwitch)
        presetsRow = LinearLayout(requireContext()).apply { orientation = LinearLayout.HORIZONTAL }
        root.addView(presetsRow)
        sessionLine = TextView(requireContext()).apply { textSize = 20f }
        root.addView(sessionLine)
        statusLine = TextView(requireContext())
        root.addView(statusLine)
        val start = Button(requireContext()).apply { text = "Start" }
        start.setOnClickListener { startSession() }
        root.addView(start)
        val end = Button(requireContext()).apply { text = "End" }
        end.setOnClickListener { endSession() }
        root.addView(end)
        loadTargets()
        TimerState.listeners.add(::render)
        render()
        return root
    }

    override fun onDestroyView() {
        TimerState.listeners.remove(::render)
        super.onDestroyView()
    }

    private fun mode(): String {
        val id = modeGroup.checkedRadioButtonId
        return (modeGroup.findViewById<RadioButton>(id)?.tag as? String) ?: "stopwatch"
    }

    private fun loadTargets() {
        app.io.launch {
            try {
                val ns = app.api.getNodes()
                nodes = ns
                val titles = ns.map { "${it.kind}: ${it.title}" }
                activity?.runOnUiThread {
                    targetSpinner.adapter = ArrayAdapter(
                        requireContext(), android.R.layout.simple_spinner_item,
                        listOf("(no target)") + titles,
                    )
                }
                loadPresets()
            } catch (_: Exception) { }
        }
    }

    private fun loadPresets() {
        app.io.launch {
            try {
                val presets = app.api.getPresets().toMutableList()
                if (presets.none { it.second == 25L && it.third == 5L }) {
                    presets.add(0, Triple("25/5x4", 25L, 5L))
                }
                activity?.runOnUiThread {
                    presetsRow.removeAllViews()
                    presets.forEach { (name, focus, _) ->
                        val b = Button(requireContext()).apply { text = name }
                        b.setOnClickListener { startPreset(focus) }
                        presetsRow.addView(b)
                    }
                }
            } catch (_: Exception) { }
        }
    }

    private fun startPreset(focusMin: Long) {
        startSession(presetTargetMs = focusMin * 60_000L, presetMode = "pomodoro")
    }

    private fun startSession(presetTargetMs: Long? = null, presetMode: String? = null) {
        if (!app.health.writesAllowed()) {
            statusLine.text = "server is down"
            return
        }
        val m = presetMode ?: mode()
        val sel = targetSpinner.selectedItemPosition - 1
        val node = if (sel in nodes.indices) nodes[sel] else null
        val target = presetTargetMs ?: if (m == "stopwatch") null else 25 * 60_000L
        app.io.launch {
            try {
                val sess = app.api.startTimer(
                    label = node?.title ?: m, mode = m, nodeId = node?.id, targetMs = target,
                )
                app.shield.onSessionStart()
                TimerState.session = sess
                TimerState.elapsedMs = 0L
                TimerState.emit()
                ui { statusLine.text = "" }
            } catch (e: ApiException) {
                ui { statusLine.text = if (e.status == 409) "stop current first" else e.message }
            } catch (e: Exception) {
                ui { statusLine.text = e.message }
            }
        }
    }

    private fun endSession() {
        app.io.launch {
            try {
                // Clean stop: void=false (elapsed KEPT); after attempts: void=true.
                app.api.stopTimer(app.shield.stopVoidFlag())
                TimerState.session = null
                TimerState.emit()
                ui { statusLine.text = "" }
            } catch (e: Exception) {
                ui { statusLine.text = e.message }
            }
        }
    }

    private fun render() {
        activity?.runOnUiThread {
            val s = TimerState.session
            sessionLine.text = if (s == null) "No session running"
            else "${s.mode} — ${s.label} — ${TimerService.fmt(TimerState.elapsedMs)}${if (s.voided) " (voided)" else ""}"
        }
    }

    private fun ui(fn: () -> Unit) {
        activity?.runOnUiThread(fn)
    }
}
