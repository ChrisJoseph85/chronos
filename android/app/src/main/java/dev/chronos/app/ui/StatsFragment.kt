package dev.chronos.app.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment
import dev.chronos.app.ChronosApp
import dev.chronos.app.net.BreakdownRepository
import kotlinx.coroutines.launch

/**
 * Stats: GET /api/timer/summary totals + GET /api/stats/breakdown drilldown
 * bars: project -> children -> tasks (per-child total_ms).
 */
class StatsFragment : Fragment() {
    private val app get() = requireContext().applicationContext as ChronosApp
    private lateinit var body: LinearLayout
    private val trail = ArrayDeque<Long?>().also { it.addLast(null) }

    override fun onCreateView(inf: LayoutInflater, c: ViewGroup?, s: Bundle?): View {
        body = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        load()
        return body
    }

    private fun load() {
        val nodeId = trail.last()
        app.io.launch {
            var summaryTxt = ""
            try {
                val s = app.api.getSummary(nodeId)
                summaryTxt = "Total ${s.nodeTotalMs / 60000} min · descendants ${s.descendantTotalMs / 60000} min"
            } catch (_: Exception) {
                summaryTxt = "server is down"
            }
            val state = BreakdownRepository(app.api.breakdownAdapter())
                .load(nodeId, "2026-01-01", "2026-12-31")
            activity?.runOnUiThread {
                body.removeAllViews()
                body.addView(TextView(requireContext()).apply { text = summaryTxt })
                if (trail.size > 1) {
                    val back = Button(requireContext()).apply { text = "← Up" }
                    back.setOnClickListener { trail.removeLast(); load() }
                    body.addView(back)
                }
                when (state) {
                    is BreakdownRepository.UiState.Notice ->
                        body.addView(TextView(requireContext()).apply { text = state.text })
                    is BreakdownRepository.UiState.Data -> state.children.forEach { c ->
                        val b = Button(requireContext()).apply {
                            text = "${c.title} — ${c.totalMs / 60000} min"
                        }
                        b.setOnClickListener { trail.addLast(c.nodeId); load() }
                        body.addView(b)
                    }
                }
            }
        }
    }
}
