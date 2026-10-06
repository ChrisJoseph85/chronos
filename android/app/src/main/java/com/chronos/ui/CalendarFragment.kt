package com.chronos.ui

import android.graphics.Typeface
import android.os.Bundle
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.TextView
import com.chronos.ChronosApp
import com.chronos.api.CalEvent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Calendar, rebuilt: month grid (weekday headers, today highlighted,
 * event dots per day, selected-day ring), agenda list below
 * (time-ordered, kind color chips, tap -> detail + voice prefill),
 * smooth month paging (slide animation). Reuses app.api().events.
 * View only — commit only via proposal accept.
 */
class CalendarFragment : ScopedFragment() {
    private var month: YearMonth = YearMonth.now()
    private var selected: LocalDate = LocalDate.now()
    private lateinit var monthLabel: TextView
    private lateinit var grid: GridLayout
    private lateinit var agendaTitle: TextView
    private lateinit var agenda: LinearLayout
    private var events: List<CalEvent> = emptyList()

    private val titleFmt = DateTimeFormatter.ofPattern("MMMM yyyy")
    private val dayFmt = DateTimeFormatter.ofPattern("EEEE, MMM d")
    private val timeFmt = DateTimeFormatter.ofPattern("HH:mm")

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        val ctx = requireContext()
        val root = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }

        root.addView(TextView(ctx).apply { text = UiStrings.CALENDAR; textSize = 20f; setPadding(0, 16, 0, 8) })

        // Month pager: ‹ Prev | Month Year | Next › + Today.
        val pager = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val prev = Button(ctx).apply { text = "‹"; setOnClickListener { page(-1) } }
        monthLabel = TextView(ctx).apply {
            textSize = 18f; setTypeface(typeface, Typeface.BOLD)
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val next = Button(ctx).apply { text = "›"; setOnClickListener { page(1) } }
        val todayBtn = Button(ctx).apply {
            text = UiStrings.TODAY
            setOnClickListener {
                month = YearMonth.now(); selected = LocalDate.now()
                renderGrid(); load()
            }
        }
        pager.addView(prev); pager.addView(monthLabel); pager.addView(next); pager.addView(todayBtn)
        root.addView(pager)

        // Weekday headers.
        val headers = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        for (d in UiStrings.WEEKDAYS) {
            headers.addView(TextView(ctx).apply {
                text = d; gravity = Gravity.CENTER; setTypeface(typeface, Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
        }
        root.addView(headers)

        grid = GridLayout(ctx).apply { columnCount = 7; rowCount = 6 }
        root.addView(grid)

        root.addView(Button(ctx).apply {
            text = UiStrings.FIND_FREE_TIME
            setOnClickListener {
                (activity as? MainActivity)?.voicePrefill("Find free time ${selected} ")
            }
        })

        agendaTitle = TextView(ctx).apply { textSize = 16f; setTypeface(typeface, Typeface.BOLD) }
        root.addView(agendaTitle)
        agenda = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        root.addView(agenda)

        // Swipe left/right pages the month too (smooth paging both ways).
        val gesture = object : View.OnTouchListener {
            var x0 = 0f
            override fun onTouch(v: View, e: android.view.MotionEvent): Boolean {
                when (e.action) {
                    android.view.MotionEvent.ACTION_DOWN -> x0 = e.x
                    android.view.MotionEvent.ACTION_UP -> {
                        val dx = e.x - x0
                        if (dx > 120) page(-1) else if (dx < -120) page(1)
                    }
                }
                return true
            }
        }
        root.setOnTouchListener(gesture)

        renderGrid()
        return root
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    private fun page(delta: Long) {
        month = month.plusMonths(delta)
        // Smooth month paging: slide the grid.
        grid.animate().translationXBy(-24f * delta).alpha(0.4f).setDuration(90).withEndAction {
            renderGrid(); load()
            grid.translationX = 24f * delta
            grid.animate().translationX(0f).alpha(1f).setDuration(140).start()
        }.start()
    }

    private fun renderGrid() {
        val ctx = requireContext()
        val today = LocalDate.now()
        val counts = CalendarLogic.countsFor(events)
        val cells = CalendarLogic.monthCells(month, selected, today, counts)
        monthLabel.text = month.format(titleFmt)
        grid.removeAllViews()
        val zone = ZoneId.systemDefault()
        for (cell in cells) {
            val dayEvents = CalendarLogic.agendaFor(events, cell.date, zone)
            val num = TextView(ctx).apply {
                text = cell.date.dayOfMonth.toString()
                gravity = Gravity.CENTER
                textSize = 15f
                alpha = if (cell.inMonth) 1f else 0.35f
                if (cell.isToday) {
                    setTypeface(typeface, Typeface.BOLD)
                    setBackgroundColor(0xFF1A73E8.toInt())
                    setTextColor(0xFFFFFFFF.toInt())
                }
                if (cell.isSelected) {
                    // Selected-day ring.
                    background = android.graphics.drawable.GradientDrawable().apply {
                        shape = android.graphics.drawable.GradientDrawable.OVAL
                        setStroke(4, 0xFF1A73E8.toInt())
                    }
                    setTypeface(typeface, Typeface.BOLD)
                }
                setPadding(0, 10, 0, 2)
            }
            val dots = TextView(ctx).apply {
                gravity = Gravity.CENTER; textSize = 12f
                text = when {
                    dayEvents.isEmpty() -> ""
                    dayEvents.size == 1 -> "●"
                    dayEvents.size <= 3 -> "●".repeat(dayEvents.size)
                    else -> "●●●+"
                }
                val first = dayEvents.firstOrNull()
                if (first != null) setTextColor(CalendarLogic.chipColor(first.id))
                setPadding(0, 0, 0, 10)
            }
            val cellView = LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER
                isClickable = true; isFocusable = true
                layoutParams = GridLayout.LayoutParams().apply {
                    width = 0; columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f)
                }
                addView(num); addView(dots)
                val d = cell.date
                setOnClickListener {
                    selected = d
                    if (d.month != month.month) month = YearMonth.from(d)
                    renderGrid(); renderAgenda()
                }
            }
            grid.addView(cellView)
        }
        renderAgenda()
    }

    private fun renderAgenda() {
        val ctx = requireContext()
        val zone = ZoneId.systemDefault()
        val items = CalendarLogic.agendaFor(events, selected, zone)
        agendaTitle.text = selected.format(dayFmt)
        agenda.removeAllViews()
        if (items.isEmpty()) {
            agenda.addView(TextView(ctx).apply { text = UiStrings.NO_EVENTS })
            return
        }
        for (e in items) {
            val t = try {
                timeFmt.format(Instant.ofEpochMilli(e.from_ms).atZone(zone)) +
                    "–" + timeFmt.format(Instant.ofEpochMilli(e.to_ms).atZone(zone))
            } catch (_: Exception) {
                ""
            }
            val rowView = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                setPadding(0, 4, 0, 4)
            }
            // Kind color chip.
            rowView.addView(View(ctx).apply {
                setBackgroundColor(CalendarLogic.chipColor(e.id))
                layoutParams = LinearLayout.LayoutParams(12, 48).apply { marginEnd = 16 }
            })
            rowView.addView(Button(ctx).apply {
                text = "$t  ${e.title}"
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                // Tap -> detail/prefill say: detail toast + voice bar prefill.
                setOnClickListener {
                    val act = activity as? MainActivity ?: return@setOnClickListener
                    act.voicePrefill("Reschedule ${e.title} ")
                }
            })
            agenda.addView(rowView)
        }
    }

    private fun load() {
        val act = activity as? MainActivity ?: return
        val from = month.atDay(1).toString()
        val to = month.plusMonths(1).atDay(1).toString()
        scope.launch {
            val app = act.application as ChronosApp
            val fetched: List<CalEvent> = try {
                if (act.readOnly) emptyList()
                else withContext(Dispatchers.IO) { app.api().events(from, to) }
            } catch (_: Exception) {
                emptyList()
            }
            if (!isAdded) return@launch
            events = CalendarLogic.orderAgenda(fetched)
            renderGrid()
        }
    }
}
