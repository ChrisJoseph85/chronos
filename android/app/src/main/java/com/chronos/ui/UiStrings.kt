package com.chronos.ui

import com.google.android.material.bottomnavigation.BottomNavigationView

/**
 * Centralized user-visible strings. Every label is capitalized
 * (first letter upper, never all-lowercase). Fragments must use
 * these instead of inline literals so PolishTest can assert on them.
 */
object UiStrings {
    const val HOME = "Home"
    const val CALENDAR = "Calendar"
    const val TASKS = "Tasks"
    const val BRIEFING = "Briefing"
    const val MORE = "More"
    const val PROJECTS = "Projects"
    const val STATS = "Stats"
    const val SETTINGS = "Settings"
    const val TIMER = "Timer"

    const val STOPWATCH = "Stopwatch"
    const val COUNTDOWN = "Countdown"
    const val POMODORO = "Pomodoro"
    const val START = "Start"
    const val END = "End"
    const val STOP = "Stop"

    const val HINT_SAY = "Say something…"
    const val SEND = "Send"
    const val ACCEPT = "Accept"
    const val REJECT = "Reject"
    const val SKIP = "Skip"
    const val SAVE = "Save"
    const val LOAD = "Load"
    const val RELOAD = "Reload"
    const val TODAY = "Today"
    const val FIND_FREE_TIME = "Find Free Time"

    const val HINT_COUNTDOWN_MINUTES = "Countdown minutes"
    const val HINT_LABEL_OPTIONAL = "Label (optional)"
    const val HINT_TARGET_NODE = "Target node ID (optional)"
    const val HINT_SERVER_URL = "Server URL"
    const val HINT_INSTANCE_KEY = "Instance Key"
    const val HINT_PORT = "Port"
    const val HINT_DATE = "Date YYYY-MM-DD"

    const val STRICT_SHIELD = "Strict Shield (Default ON)"
    const val BLOCKED_APPS = "Blocked Apps"
    const val FOCUS_SHIELD = "Focus Shield"
    const val PROVIDERS = "Providers (Keys Never Displayed)"
    const val AUTO_FIND = "Auto-Find Server"
    const val CANCEL_SCAN = "Cancel Scan"
    const val TOP_LEVEL = "Top Level"

    const val NO_EVENTS = "(No Events)"
    const val EMPTY = "(Empty)"
    const val UNAVAILABLE_OFFLINE = "(Unavailable Offline)"
    const val MONTH = "Month"
    const val WEEK = "Week"
    const val DAY = "Day"

    val WEEKDAYS: List<String> = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    /** Every user-visible label, for the capitalization test. */
    val ALL: List<String> = listOf(
        HOME, CALENDAR, TASKS, BRIEFING, MORE, PROJECTS, STATS, SETTINGS, TIMER,
        STOPWATCH, COUNTDOWN, POMODORO, START, END, STOP,
        HINT_SAY, SEND, ACCEPT, REJECT, SKIP, SAVE, LOAD, RELOAD, TODAY, FIND_FREE_TIME,
        HINT_COUNTDOWN_MINUTES, HINT_LABEL_OPTIONAL, HINT_TARGET_NODE,
        HINT_SERVER_URL, HINT_INSTANCE_KEY, HINT_PORT, HINT_DATE,
        STRICT_SHIELD, BLOCKED_APPS, FOCUS_SHIELD, PROVIDERS,
        AUTO_FIND, CANCEL_SCAN, TOP_LEVEL,
        MONTH, WEEK, DAY,
    ) + WEEKDAYS

    /** Capitalized = starts with an uppercase letter (parentheticals exempt from case but never all-lowercase words). */
    fun isCapitalized(s: String): Boolean {
        val t = s.trim().trimStart('(')
        if (t.isEmpty()) return false
        val firstLetter = t.firstOrNull { it.isLetter() } ?: return false
        return firstLetter.isUpperCase()
    }
}

/** Nav policy: all 5 bottom-nav labels always visible. */
object UiPolicy {
    const val NAV_LABEL_MODE: Int = BottomNavigationView.LABEL_VISIBILITY_LABELED
}
