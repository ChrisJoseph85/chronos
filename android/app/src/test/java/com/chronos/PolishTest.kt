package com.chronos

import com.chronos.api.CalEvent
import com.chronos.store.MemoryPrefs
import com.chronos.ui.BlockedApps
import com.chronos.ui.CalendarLogic
import com.chronos.ui.UiPolicy
import com.chronos.ui.UiStrings
import com.google.android.material.bottomnavigation.BottomNavigationView
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

/** Android-polish contract: labels, strings, blocklist, calendar agenda. */
class PolishTest {
    @Test
    fun navLabelModeIsLabeled() {
        // All 5 bottom-nav labels always visible.
        assertEquals(
            BottomNavigationView.LABEL_VISIBILITY_LABELED,
            UiPolicy.NAV_LABEL_MODE,
        )
    }

    @Test
    fun centralizedStringsCapitalized() {
        for (s in UiStrings.ALL) {
            assertTrue("not capitalized: \"$s\"", UiStrings.isCapitalized(s))
            assertFalse(
                "all-lowercase label: \"$s\"",
                s.trim().trimStart('(').all { !it.isLetter() || it.isLowerCase() },
            )
        }
        // Weekday headers centralized and complete.
        assertEquals(listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), UiStrings.WEEKDAYS)
    }

    @Test
    fun stringResourcesCapitalized() {
        // Assert on the centralized string resources / weekday array.
        val f = File("src/main/res/values/strings.xml")
        assertTrue("strings.xml missing at ${f.absolutePath}", f.isFile)
        val text = f.readText()
        val values = Regex("<string name=\"[^\"]+\">([^<]*)</string>")
            .findAll(text).map { it.groupValues[1] }.toList() +
            Regex("<item>([^<]*)</item>").findAll(text).map { it.groupValues[1] }.toList()
        assertTrue(values.isNotEmpty())
        for (v in values) {
            val first = v.trim().trimStart('(').firstOrNull { it.isLetter() }
            assertNotNull("no letter in \"$v\"", first)
            assertTrue("resource not capitalized: \"$v\"", first!!.isUpperCase())
        }
    }

    @Test
    fun blocklistPersistRoundTrip() {
        val prefs = MemoryPrefs()
        assertTrue(prefs.blocklist.isEmpty())
        var cur = prefs.blocklist
        cur = BlockedApps.toggle(cur, "com.example.game")
        cur = BlockedApps.toggle(cur, "com.example.social")
        prefs.blocklist = cur
        assertEquals(setOf("com.example.game", "com.example.social"), prefs.blocklist)
        // Uncheck one -> removed and persisted.
        prefs.blocklist = BlockedApps.toggle(prefs.blocklist, "com.example.game")
        assertEquals(setOf("com.example.social"), prefs.blocklist)
        // Shield tripwire consumes the persisted set.
        assertTrue(com.chronos.shield.ShieldLogic.blockedOpened(prefs.blocklist, "com.example.social"))
        assertFalse(com.chronos.shield.ShieldLogic.blockedOpened(prefs.blocklist, "com.example.game"))
    }

    @Test
    fun calendarAgendaOrdering() {
        val zone = ZoneId.of("UTC")
        val day = LocalDate.of(2026, 10, 6)
        fun ev(id: String, hour: Int) = CalEvent(
            id = id, title = id,
            from_ms = day.atTime(hour, 0).atZone(zone).toInstant().toEpochMilli(),
            to_ms = day.atTime(hour + 1, 0).atZone(zone).toInstant().toEpochMilli(),
        )
        val shuffled = listOf(ev("c", 15), ev("a", 8), ev("b", 12))
        val ordered = CalendarLogic.orderAgenda(shuffled)
        assertEquals(listOf("a", "b", "c"), ordered.map { it.id })
        // Per-day agenda is time-ordered too.
        val agenda = CalendarLogic.agendaFor(shuffled, day, zone)
        assertEquals(listOf("a", "b", "c"), agenda.map { it.id })
        // Month grid: 42 Monday-first cells, selection + counts land right.
        val cells = CalendarLogic.monthCells(
            YearMonth.of(2026, 10), day, day,
            mapOf(day to 3),
        )
        assertEquals(42, cells.size)
        assertEquals(LocalDate.of(2026, 9, 28), cells.first().date) // Monday
        val sel = cells.single { it.isSelected }
        assertEquals(day, sel.date)
        assertEquals(3, sel.eventCount)
        assertTrue(sel.isToday)
    }
}
