package dev.chronos.app.net

/** Health gate: unreachable -> cached read-only + "server is down" banner; writes blocked. */
class HealthGate(private val probe: suspend () -> Boolean) {
    var serverDown: Boolean = false
        private set

    suspend fun refresh(): Boolean {
        serverDown = try {
            !probe()
        } catch (_: Exception) {
            true
        }
        return !serverDown
    }

    /** True when a write may proceed. No silent queuing while down. */
    fun writesAllowed(): Boolean = !serverDown
}
