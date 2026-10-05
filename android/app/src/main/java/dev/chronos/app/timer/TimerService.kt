package dev.chronos.app.timer

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import androidx.core.app.NotificationCompat
import dev.chronos.app.R
import dev.chronos.app.net.TimerSession
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Foreground service for the timer tick. Mirrors the server-owned session;
 * `timer` WS frames update [TimerState.session] from anywhere (any client).
 */
object TimerState {
    @Volatile var session: TimerSession? = null
    @Volatile var elapsedMs: Long = 0L
    val listeners = mutableSetOf<() -> Unit>()
    fun emit() = listeners.toList().forEach { try { it() } catch (_: Exception) { } }
}

class TimerService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var tick: Job? = null
    private val binder = Binder()

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel("timer", "Timer", NotificationManager.IMPORTANCE_LOW)
        )
        startForeground(1, note("Timer idle"))
        tick = scope.launch {
            while (isActive) {
                val s = TimerState.session
                if (s != null) {
                    TimerState.elapsedMs = System.currentTimeMillis() - s.startedMs
                    val nm2 = getSystemService(NotificationManager::class.java)
                    nm2.notify(1, note("Session running — ${fmt(TimerState.elapsedMs)}"))
                    TimerState.emit()
                }
                delay(1000)
            }
        }
    }

    private fun note(text: String): Notification {
        val pi = PendingIntent.getActivity(
            this, 0,
            Intent(this, Class.forName("dev.chronos.app.ui.MainActivity")),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, "timer")
            .setContentTitle("Chronos")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        tick?.cancel()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        fun fmt(ms: Long): String {
            val s = (ms / 1000).toInt()
            return "%02d:%02d".format(s / 60, s % 60)
        }
    }
}
