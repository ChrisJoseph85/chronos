package com.chronos.ui

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.chronos.ChronosApp
import com.chronos.app.R
import com.chronos.api.Health
import com.chronos.api.Proposal
import com.chronos.api.Question
import com.chronos.api.TimerSession
import com.chronos.api.WsClient
import com.chronos.timer.TimerService
import com.google.android.material.bottomnavigation.BottomNavigationView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Host: 5-tab bottom nav (Home, Calendar, Tasks, Briefing, More — hard
 * platform limit, never more), health-gate banner, global voice bar.
 * More screen holds Projects, Stats, Settings (same fragments).
 */
class MainActivity : AppCompatActivity(), WsClient.Listener {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    /** True when the server is unreachable: cached read-only, writes blocked. */
    var readOnly: Boolean = false
        private set

    var tickRunning: Boolean = false
    var tickDisplayMs: Long = 0
    var tickRemainingMs: Long = -1
    var tickLabel: String = ""

    private lateinit var banner: TextView
    private lateinit var voice: VoiceBar

    private val tickReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context?, intent: Intent?) {
            if (intent?.action != TimerService.ACTION_TICK) return
            tickRunning = intent.getBooleanExtra(TimerService.EXTRA_RUNNING, false)
            tickDisplayMs = intent.getLongExtra(TimerService.EXTRA_DISPLAY_MS, 0)
            tickRemainingMs = intent.getLongExtra(TimerService.EXTRA_REMAINING_MS, -1)
            tickLabel = intent.getStringExtra(TimerService.EXTRA_LABEL) ?: ""
            (supportFragmentManager.findFragmentById(R.id.container) as? TickListener)?.onTick()
        }
    }

    interface TickListener {
        fun onTick()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        banner = findViewById(R.id.health_banner)
        voice = findViewById(R.id.voice_bar)
        voice.onVoiceError = { toast(it) }

        val nav = findViewById<BottomNavigationView>(R.id.bottom_nav)
        nav.menu.clear()
        menuInflater.inflate(R.menu.bottom_nav, nav.menu)
        // Enforce the 5-tab limit even if the menu XML ever grows: extra
        // items are dropped instead of crashing on launch like the old app.
        while (nav.menu.size() > 5) nav.menu.removeItem(nav.menu.getItem(5).itemId)
        nav.setOnItemSelectedListener { item ->
            open(
                when (item.itemId) {
                    R.id.tab_calendar -> CalendarFragment()
                    R.id.tab_tasks -> TasksFragment()
                    R.id.tab_briefing -> BriefingFragment()
                    R.id.tab_more -> MoreFragment()
                    else -> HomeFragment()
                },
            )
            true
        }
        if (savedInstanceState == null) open(HomeFragment())

        ContextCompat.registerReceiver(
            this, tickReceiver, IntentFilter(TimerService.ACTION_TICK),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
    }

    fun open(f: Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.container, f)
            .commit()
    }

    fun voicePrefill(text: String) {
        voice.prefill(text)
    }

    fun ws(): WsClient = (application as ChronosApp).ws.also { it.listener = this }

    fun blockedWrite(): Boolean {
        if (readOnly) toast("server is down — writes blocked")
        return readOnly
    }

    override fun onResume() {
        super.onResume()
        checkHealth()
        if ((application as ChronosApp).prefs.serverUrl.isNotEmpty()) ws().connect()
        try {
            if ((application as ChronosApp).prefs.serverUrl.isNotEmpty()) {
                ContextCompat.startForegroundService(this, Intent(this, TimerService::class.java))
            }
        } catch (_: Exception) {
        }
    }

    override fun onPause() {
        (application as ChronosApp).ws.close()
        super.onPause()
    }

    override fun onDestroy() {
        unregisterReceiver(tickReceiver)
        voice.onDetach()
        scope.cancel()
        super.onDestroy()
    }

    private fun checkHealth() {
        val app = application as ChronosApp
        if (app.prefs.serverUrl.isEmpty() || app.prefs.apiKey.isEmpty()) {
            setDown("set server URL + key in More → Settings")
            return
        }
        scope.launch {
            try {
                val h: Health = withContext(Dispatchers.IO) { app.api().health() }
                if (h.status == "ok") setUp() else setDown("server is down")
            } catch (_: Exception) {
                setDown("server is down")
            }
        }
    }

    private fun setUp() {
        readOnly = false
        banner.visibility = View.GONE
    }

    private fun setDown(msg: String) {
        readOnly = true
        banner.text = "$msg — read-only cache"
        banner.visibility = View.VISIBLE
    }

    // WsClient.Listener: remote stop/void and proposals reflect live.
    override fun onTimer(session: TimerSession?) {
        (supportFragmentManager.findFragmentById(R.id.container) as? HomeFragment)?.onRemoteTimer(session)
    }

    override fun onProposal(proposal: Proposal) {
        voice.showCard(proposal.summary)
    }

    override fun onQuestion(question: Question) {
        voice.showCard("Q: ${question.text}")
    }

    override fun onOpen() {}
    override fun onClosed() {}

    private fun toast(msg: String) = android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_SHORT).show()
}
