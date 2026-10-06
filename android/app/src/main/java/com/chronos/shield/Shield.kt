package com.chronos.shield

/**
 * Focus-shield rules (spec §4, frozen UX).
 *
 * - Strict toggle ON is the default; OFF disables all blocking and stops keep time.
 * - Blocked app opens -> full-screen redirect, no direct entry, for as long as
 *   the session runs.
 * - Attempt counter is device-side, per session.
 * - Clean stop (zero attempts) keeps time; stop after >=1 attempt sends
 *   void:true (session VOIDED, elapsed discarded — the ONLY bypass, and it
 *   costs the session). Remote stop/void reflects via WS on every client.
 */
object ShieldLogic {
    /** Shown verbatim in-app next to the UsageStats permission prompt. */
    const val RATIONALE =
        "used only to detect a blocked app opening; no usage statistics are collected, stored, or sent anywhere."

    const val STRICT_DEFAULT: Boolean = true

    /** The ONLY bypass: void the session, losing its elapsed time. */
    fun shouldVoidOnStop(strictOn: Boolean, blockAttempts: Int): Boolean =
        strictOn && blockAttempts > 0

    fun blockedOpened(blocklist: Set<String>, foregroundPackage: String?): Boolean =
        foregroundPackage != null && blocklist.contains(foregroundPackage)
}

/** Device-side per-session attempt counter. Reset on every new session. */
class AttemptCounter {
    var attempts: Int = 0
        private set

    fun trip(): Int {
        attempts += 1
        return attempts
    }

    fun reset() {
        attempts = 0
    }
}
