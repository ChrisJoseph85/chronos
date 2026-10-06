package com.chronos.ui

import com.chronos.api.CalEvent
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

/** One month-grid cell. Monday-first grid, always 42 cells (6x7). */
data class DayCell(
    val date: LocalDate,
    val inMonth: Boolean,
    val isToday: Boolean,
    val isSelected: Boolean,
    val eventCount: Int,
)

/** Pure calendar math + agenda ordering (unit-tested, no Android deps). */
object CalendarLogic {
    /** Monday-first 6x7 grid covering [month]. */
    fun monthCells(
        month: YearMonth,
        selected: LocalDate,
        today: LocalDate,
        counts: Map<LocalDate, Int> = emptyMap(),
    ): List<DayCell> {
        val first = month.atDay(1)
        // Monday-first offset: MONDAY=1..SUNDAY=7 -> 0..6 leading days.
        val lead = (first.dayOfWeek.value - 1)
        val start = first.minusDays(lead.toLong())
        return (0 until 42).map { i ->
            val d = start.plusDays(i.toLong())
            DayCell(
                date = d,
                inMonth = d.month == month.month,
                isToday = d == today,
                isSelected = d == selected,
                eventCount = counts[d] ?: 0,
            )
        }
    }

    /** Day key for an event start instant. */
    fun dayOf(event: CalEvent, zone: ZoneId = ZoneId.systemDefault()): LocalDate =
        java.time.Instant.ofEpochMilli(event.from_ms).atZone(zone).toLocalDate()

    /** Map each event to its day, counting events per day in range. */
    fun countsFor(events: List<CalEvent>, zone: ZoneId = ZoneId.systemDefault()): Map<LocalDate, Int> =
        events.groupingBy { dayOf(it, zone) }.eachCount()

    /** Agenda: events on [day], time-ordered ascending. */
    fun agendaFor(events: List<CalEvent>, day: LocalDate, zone: ZoneId = ZoneId.systemDefault()): List<CalEvent> =
        events.filter { dayOf(it, zone) == day }.sortedBy { it.from_ms }

    /** Whole-list time ordering (agenda invariant). */
    fun orderAgenda(events: List<CalEvent>): List<CalEvent> = events.sortedBy { it.from_ms }

    /** Deterministic chip color (ARGB) per event id — "kind color chips". */
    fun chipColor(id: String): Int {
        val palette = intArrayOf(
            0xFF1A73E8.toInt(), 0xFF188038.toInt(), 0xFF9334E6.toInt(),
            0xFFE37400.toInt(), 0xFFD93025.toInt(), 0xFF0097A7.toInt(),
        )
        return palette[(id.hashCode() and Int.MAX_VALUE) % palette.size]
    }
}
