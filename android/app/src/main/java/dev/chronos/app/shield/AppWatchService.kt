package dev.chronos.app.shield

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import dev.chronos.app.ChronosApp
import dev.chronos.app.timer.TimerState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Foreground-app tripwire via UsageStats permission. Shown rationale (verbatim):
 * "used only to detect a blocked app opening; no usage statistics are collected,
 * stored, or sent anywhere." No measurement — tripwire only.
 */
class AppWatchService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel("shield", "Focus shield", NotificationManager.IMPORTANCE_MIN)
        )
        startForeground(2, NotificationCompat.Builder(this, "shield")
            .setContentTitle("Chronos shield")
            .setContentText("Watching blocked apps while a session runs")
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setOngoing(true)
            .build())
        job = scope.launch {
            while (isActive) {
                try {
                    poll()
                } catch (_: Exception) { }
                delay(2000)
            }
        }
    }

    private fun poll() {
        val app = application as ChronosApp
        val shield = app.shield
        val running = TimerState.session != null
        if (!shield.blockingActive(running)) return
        val store = ShieldPrefsStore(this)
        if (store.blocklist.isEmpty()) return
        val usm = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val now = System.currentTimeMillis()
        val stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, now - 10_000, now)
        val fg = stats.maxByOrNull { it.lastTimeUsed }?.packageName ?: return
        if (fg == packageName) return
        if (store.blocklist.contains(fg)) {
            shield.onBlockedAppOpened()
            val i = Intent(this, ShieldBlockActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            startActivity(i)
        }
    }

    override fun onDestroy() {
        job?.cancel()
        scope.cancel()
        super.onDestroy()
    }
}
