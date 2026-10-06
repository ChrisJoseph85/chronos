package com.chronos.shield

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.chronos.api.RealChronosApi
import com.chronos.store.AndroidPrefs
import com.chronos.timer.TimerEngine
import com.chronos.timer.SystemClock
import com.chronos.timer.formatMs
import com.chronos.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Full-screen shield redirect. NO direct entry: without a live session in the
 * launching intent this finishes immediately. Lasts as long as the session
 * runs — the ONLY bypass voids the session (elapsed discarded).
 */
class ShieldActivity : AppCompatActivity() {
    companion object {
        const val EXTRA_REMAINING_MS = "remaining_ms"
        const val EXTRA_ATTEMPTS = "attempts"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // No direct entry: guard on a real running session.
        if (!intent.hasExtra(EXTRA_REMAINING_MS)) {
            finish()
            return
        }
        val left = intent.getLongExtra(EXTRA_REMAINING_MS, 0)
        val attempts = intent.getIntExtra(EXTRA_ATTEMPTS, 0)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 96, 48, 96)
        }
        root.addView(TextView(this).apply {
            text = "Session running — ${formatMs(left)} left."
            textSize = 22f
        })
        root.addView(TextView(this).apply { text = "Blocked app attempt #$attempts" })
        val back = Button(this).apply { text = "Back to timer" }
        val end = Button(this).apply { text = "End session — time voided" }
        root.addView(back)
        root.addView(end)
        setContentView(root)

        back.setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }
        end.setOnClickListener {
            scope.launch {
                val prefs = AndroidPrefs(this@ShieldActivity)
                // Shield is only reachable while strict is ON, so void:true.
                val engine = TimerEngine(prefs, RealChronosApi(prefs.serverUrl, { prefs.apiKey }), SystemClock())
                engine.stop(attempts.coerceAtLeast(1), strictOn = true)
                startActivity(Intent(this@ShieldActivity, MainActivity::class.java))
                finish()
            }
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
