package com.chronos.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import com.chronos.ChronosApp
import com.chronos.timer.formatHms
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate

/**
 * Stats: GET /api/timer/summary totals + GET /api/stats/breakdown drilldown
 * bars: project -> children -> tasks (per-child total_ms). Voided sessions
 * are already excluded server-side. Pre-v1.2 servers show "server too old".
 */
class StatsFragment : ScopedFragment() {
    private lateinit var body: android.widget.LinearLayout
    private var drillNode: String? = null
    private var drillTitle: String = ""

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        return col(requireContext()) {
            title(UiStrings.STATS)
            body = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.VERTICAL
            }
            addView(body)
            btn(UiStrings.TOP_LEVEL) {
                drillNode = null
                drillTitle = ""
                load()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    private fun load() {
        val act = activity as? MainActivity ?: return
        scope.launch {
            val app = act.application as ChronosApp
            if (!isAdded) return@launch
            body.removeAllViews()
            try {
                val s = withContext(Dispatchers.IO) { app.api().timerSummary(drillNode) }
                body.addView(TextView(context).apply { text = "Total: ${formatHms(s.project_total_ms)}" })
                body.addView(TextView(context).apply { text = "Descendants: ${formatHms(s.descendant_total_ms)}" })
            } catch (_: Exception) {
                body.addView(TextView(context).apply { text = "(Summary Unavailable)" })
            }
            val from = LocalDate.now().minusDays(30).toString()
            val to = LocalDate.now().plusDays(1).toString()
            try {
                val items = withContext(Dispatchers.IO) { app.api().breakdown(drillNode, from, to) }
                if (drillTitle.isNotEmpty()) {
                    body.addView(TextView(context).apply { text = "Drill: $drillTitle"; textSize = 16f })
                }
                for (item in items) {
                    body.addView(
                        android.widget.Button(context).apply {
                            text = "${item.title} [${item.kind}] ${formatHms(item.total_ms)}"
                            setOnClickListener {
                                drillNode = item.node_id
                                drillTitle = item.title
                                load()
                            }
                        },
                    )
                }
            } catch (e: com.chronos.api.ServerTooOld) {
                body.addView(TextView(context).apply { text = "Server Too Old — Update Server For Breakdown" })
            } catch (_: Exception) {
                body.addView(TextView(context).apply { text = "(Breakdown Unavailable)" })
            }
        }
    }
}
