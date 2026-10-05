package dev.chronos.app.shield

/** Pure focus-shield rules. Attempt counter is device-side, per session. */
class ShieldManager(private val store: ShieldStore) {

    interface ShieldStore {
        var attempts: Int
        var strict: Boolean
    }

    fun onSessionStart() {
        store.attempts = 0
    }

    fun onBlockedAppOpened() {
        store.attempts = store.attempts + 1
    }

    fun attempts(): Int = store.attempts

    fun blockingActive(sessionRunning: Boolean): Boolean =
        store.strict && sessionRunning

    /**
     * Clean stop (zero attempts) -> elapsed KEPT (void=false).
     * Stop after >=1 attempt -> void=true, session VOIDED, elapsed discarded.
     * Strict OFF -> no blocking, stop always keeps time.
     */
    fun stopVoidFlag(): Boolean =
        store.strict && store.attempts > 0
}
