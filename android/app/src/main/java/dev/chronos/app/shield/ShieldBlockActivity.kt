package dev.chronos.app.shield

import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import dev.chronos.app.ChronosApp
import dev.chronos.app.timer.TimerService
import dev.chronos.app.timer.TimerState
import kotlinx.coroutines.launch

/**
 * Blocked app opens -> full-screen redirect, no direct entry. The lock lasts
 * as long as the session runs (no magic cooldown).
 */
class ShieldBlockActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        val app = application as ChronosApp
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(48, 48, 48, 48)
        }
        val s = TimerState.session
        val left = if (s?.targetMs != null) s.targetMs - TimerState.elapsedMs else -1L
        val leftTxt = if (left >= 0) TimerService.fmt(left) + " left" else TimerService.fmt(TimerState.elapsedMs) + " elapsed"
        root.addView(TextView(this).apply {
            text = "Session running — $leftTxt."
            textSize = 22f
            gravity = Gravity.CENTER
        })
        root.addView(TextView(this).apply {
            text = "Attempt #${app.shield.attempts()} — stopping now voids the session."
            gravity = Gravity.CENTER
        })
        val back = Button(this).apply { text = "Back to timer" }
        back.setOnClickListener { finish() }
        val end = Button(this).apply { text = "End session — time voided" }
        end.setOnClickListener {
            app.io.launch {
                try {
                    // attempts >= 1 -> void:true -> VOIDED, elapsed discarded.
                    val sess = app.api.stopTimer(app.shield.stopVoidFlag())
                    TimerState.session = null
                    TimerState.emit()
                    runOnUiThread { finish() }
                } catch (_: Exception) {
                    runOnUiThread { end.text = "Server unreachable — try again" }
                }
            }
        }
        root.addView(back)
        root.addView(end)
        setContentView(root)
    }

    override fun onBackPressed() {
        // Back goes to timer, never into the blocked app.
        super.onBackPressed()
    }
}
