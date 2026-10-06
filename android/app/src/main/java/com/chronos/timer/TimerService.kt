package com.chronos.timer

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import com.chronos.api.RealChronosApi
import com.chronos.shield.AttemptCounter
import com.chronos.shield.ShieldActivity
import com.chronos.shield.ShieldLogic
import com.chronos.shield.ShieldWatch
import com.chronos.store.AndroidPrefs
import com.chronos.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Foreground service: 1s live tick while a session runs + shield tripwire.
 * Broadcasts ACTION_TICK; the home card renders elapsed from server start_ms.
 */
class TimerService : Service() {
    companion object {
        const val ACTION_TICK = "com.chronos.app.TICK"
        const val EXTRA_DISPLAY_MS = "display_ms"
        const val EXTRA_REMAINING_MS = "remaining_ms"
        const val EXTRA_RUNNING = "running"
        const val EXTRA_LABEL = "label"
        const val EXTRA_STATUS = "status"
        const val ACTION_START = "start"
        const val ACTION_STOP_FOREGROUND = "stop_fg"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val handler = Handler(Looper.getMainLooper())
    private val attempts = AttemptCounter()
    private var runningSessionId: String? = null

    private lateinit var tick: Runnable

    private fun tickRunnable() = object : Runnable {
        override fun run() {
            val self = this
            scope.launch {
                poll()
                handler.postDelayed(self, 1000)
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        tick = tickRunnable()
        startForeground(1, notification("Timer running"))
        handler.post(tick)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP_FOREGROUND) {
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacks(tick)
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun poll() {
        val prefs = AndroidPrefs(this)
        if (prefs.serverUrl.isEmpty() || prefs.apiKey.isEmpty()) return
        val engine = TimerEngine(prefs, RealChronosApi(prefs.serverUrl, { prefs.apiKey }), SystemClock())
        val view = try {
            engine.refresh()
        } catch (_: Exception) {
            return
        }
        if (view.running) {
            // New session -> reset device-side attempt counter.
            // (Session id unknown from view; reset when transitioning idle->run.)
            if (runningSessionId == null) {
                runningSessionId = view.label + view.displayMs
                attempts.reset()
            }
        } else {
            runningSessionId = null
        }
        sendBroadcast(
            Intent(ACTION_TICK)
                .putExtra(EXTRA_DISPLAY_MS, view.displayMs)
                .putExtra(EXTRA_REMAINING_MS, view.remainingMs ?: -1L)
                .putExtra(EXTRA_RUNNING, view.running)
                .putExtra(EXTRA_LABEL, view.label)
                .putExtra(EXTRA_STATUS, view.status)
                .setPackage(packageName),
        )
        // Shield tripwire: strict ON + session running + blocked app foreground.
        if (view.running && prefs.strictShield && prefs.blocklist.isNotEmpty()
            && ShieldWatch.hasUsageAccess(this)
        ) {
            val fg = ShieldWatch.foregroundPackage(this)
            if (ShieldLogic.blockedOpened(prefs.blocklist, fg) && fg != packageName) {
                attempts.trip()
                startActivity(
                    Intent(this, ShieldActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                        .putExtra(ShieldActivity.EXTRA_REMAINING_MS, view.remainingMs ?: view.displayMs)
                        .putExtra(ShieldActivity.EXTRA_ATTEMPTS, attempts.attempts),
                )
            }
        }
    }

    private fun notification(text: String): Notification {
        val ch = "timer"
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(ch, "Timer", NotificationManager.IMPORTANCE_LOW))
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, ch)
            .setContentTitle("Chronos")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_recent_history)
            .setContentIntent(pi)
            .build()
    }
}
