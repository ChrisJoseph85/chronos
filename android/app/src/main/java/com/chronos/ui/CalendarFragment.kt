package com.chronos.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import com.chronos.ChronosApp
import com.chronos.api.CalEvent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Calendar: month/week/day agenda, Google-Calendar-phone style.
 * View only — tap a slot prefills the voice bar; commit only via proposal accept.
 */
class CalendarFragment : ScopedFragment() {
    private var mode = "day"
    private lateinit var list: android.widget.LinearLayout
    private lateinit var dayLabel: TextView
    private var anchor: LocalDate = LocalDate.now()

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        return col(requireContext()) {
            title("Calendar")
            val modes = RadioGroup(context).apply { orientation = RadioGroup.HORIZONTAL }
            val m = RadioButton(context).apply { text = "month"; id = View.generateViewId() }
            val w = RadioButton(context).apply { text = "week"; id = View.generateViewId() }
            val d = RadioButton(context).apply { text = "day"; id = View.generateViewId() }
            modes.addView(m)
            modes.addView(w)
            modes.addView(d)
            modes.check(d.id)
            modes.setOnCheckedChangeListener { _, id ->
                mode = when (id) {
                    m.id -> "month"
                    w.id -> "week"
                    else -> "day"
                }
                load()
            }
            addView(modes)
            row(
                android.widget.Button(context).apply { text = "<"; setOnClickListener { shift(-1) } },
                android.widget.Button(context).apply { text = ">"; setOnClickListener { shift(1) } },
            )
            dayLabel = text("")
            list = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.VERTICAL
            }
            addView(list)
        }
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    private fun shift(n: Long) {
        anchor = when (mode) {
            "month" -> anchor.plusMonths(n)
            "week" -> anchor.plusWeeks(n)
            else -> anchor.plusDays(n)
        }
        load()
    }

    private fun load() {
        val act = activity as? MainActivity ?: return
        val (from, to) = range()
        dayLabel.text = "$mode $from → $to"
        scope.launch {
            val app = act.application as ChronosApp
            val events: List<CalEvent> = try {
                if (act.readOnly) {
                    app.prefs.cached("events_$mode")?.let { emptyList() } ?: emptyList()
                } else {
                    withContext(Dispatchers.IO) { app.api().events(from, to) }.also {
                        app.prefs.setCached("events_$mode", "1")
                    }
                }
            } catch (_: Exception) {
                emptyList()
            }
            if (!isAdded) return@launch
            list.removeAllViews()
            if (events.isEmpty()) list.addView(TextView(context).apply { text = "(no events)" })
            val fmt = DateTimeFormatter.ofPattern("EEE HH:mm")
            for (e in events) {
                val t = try {
                    val z = ZoneId.systemDefault()
                    fmt.format(Instant.ofEpochMilli(e.from_ms).atZone(z))
                } catch (_: Exception) {
                    ""
                }
                list.addView(
                    android.widget.Button(context).apply {
                        text = "$t ${e.title}"
                        // Tap prefills the voice bar; commit only via proposal accept.
                        setOnClickListener { act.voicePrefill("reschedule ${e.title} ") }
                    },
                )
            }
        }
    }

    private fun range(): Pair<String, String> {
        val (a, b) = when (mode) {
            "month" -> anchor.withDayOfMonth(1) to anchor.withDayOfMonth(1).plusMonths(1)
            "week" -> anchor.minusDays((anchor.dayOfWeek.value - 1).toLong()) to
                anchor.minusDays((anchor.dayOfWeek.value - 1).toLong()).plusWeeks(1)
            else -> anchor to anchor.plusDays(1)
        }
        return a.toString() to b.toString()
    }
}
