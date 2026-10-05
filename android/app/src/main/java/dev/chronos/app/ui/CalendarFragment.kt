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
import dev.chronos.app.net.EventItem
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * Calendar: month/week/day agenda, phone style. View only; tap a slot
 * prefills the voice bar; commit only via proposal accept.
 */
class CalendarFragment : Fragment() {
    var onSlotTap: ((String) -> Unit)? = null
    private val app get() = requireContext().applicationContext as ChronosApp
    private lateinit var list: LinearLayout
    private var viewMode = "day"

    override fun onCreateView(inf: LayoutInflater, c: ViewGroup?, s: Bundle?): View {
        val root = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        val tabs = LinearLayout(requireContext()).apply { orientation = LinearLayout.HORIZONTAL }
        listOf("month", "week", "day").forEach { m ->
            val b = Button(requireContext()).apply { text = m }
            b.setOnClickListener { viewMode = m; load() }
            tabs.addView(b)
        }
        root.addView(tabs)
        list = LinearLayout(requireContext()).apply { orientation = LinearLayout.VERTICAL }
        root.addView(list)
        load()
        return root
    }

    private fun load() {
        val today = LocalDate.now()
        val (from, to) = when (viewMode) {
            "month" -> today.withDayOfMonth(1) to today.withDayOfMonth(today.lengthOfMonth())
            "week" -> today.minusDays(today.dayOfWeek.value.toLong() - 1) to today.plusDays(7)
            else -> today to today
        }
        val f = DateTimeFormatter.ISO_DATE
        app.io.launch {
            val items: List<EventItem> = try {
                val (ev, raw) = app.api.getEvents(from.format(f), to.format(f))
                app.cache.put("events", raw)
                ev
            } catch (_: Exception) {
                // Offline: cached read-only.
                emptyList()
            }
            activity?.runOnUiThread {
                list.removeAllViews()
                if (items.isEmpty()) list.addView(TextView(requireContext()).apply {
                    text = if (app.health.serverDown) "server is down — no cached events" else "No events"
                })
                items.forEach { e ->
                    val b = Button(requireContext()).apply { text = e.title }
                    b.setOnClickListener { onSlotTap?.invoke("Schedule follow-up for ${e.title}") }
                    list.addView(b)
                }
            }
        }
    }
}
