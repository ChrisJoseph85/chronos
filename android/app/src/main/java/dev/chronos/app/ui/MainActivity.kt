package dev.chronos.app.ui

import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.bottomnavigation.BottomNavigationView
import dev.chronos.app.ChronosApp
import dev.chronos.app.R
import dev.chronos.app.net.Proposal
import dev.chronos.app.net.Question
import dev.chronos.app.net.WsClient
import dev.chronos.app.net.WsFrame
import dev.chronos.app.shield.AppWatchService
import dev.chronos.app.timer.TimerService
import dev.chronos.app.timer.TimerState
import kotlinx.coroutines.launch
import android.content.Intent

class MainActivity : AppCompatActivity() {
    private lateinit var app: ChronosApp
    private lateinit var banner: TextView
    private lateinit var voice: VoiceBarView
    private var ws: WsClient? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        app = application as ChronosApp

        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        banner = TextView(this).apply {
            text = "server is down"
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        voice = VoiceBarView(this)
        val frag = FrameLayout(this).apply { id = View.generateViewId() }
        frag.id = 1001
        val nav = BottomNavigationView(this)
        nav.inflateMenu(R.menu.bottom_nav)
        root.addView(banner)
        root.addView(voice)
        root.addView(frag, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(nav)
        setContentView(root)

        voice.wsResolve = { id, verb -> ws?.acceptRejectSkip(id, verb) }
        nav.setOnItemSelectedListener { item ->
            show(item.itemId)
            true
        }
        show(R.id.nav_home)
        startService(Intent(this, TimerService::class.java))
        startService(Intent(this, AppWatchService::class.java))
        refreshGate()
    }

    private fun show(id: Int) {
        val f = when (id) {
            R.id.nav_calendar -> CalendarFragment()
            R.id.nav_tasks -> TreeFragment.newInstance(TreeFragment.ROOT_TASKS)
            R.id.nav_projects -> TreeFragment.newInstance(TreeFragment.ROOT_PROJECTS)
            R.id.nav_briefing -> BriefingFragment()
            R.id.nav_stats -> StatsFragment()
            R.id.nav_settings -> SettingsFragment()
            else -> HomeFragment()
        }
        if (f is CalendarFragment) f.onSlotTap = { text -> voice.prefill(text) }
        supportFragmentManager.beginTransaction().replace(1001, f).commit()
    }

    private fun refreshGate() {
        app.io.launch {
            val ok = app.health.refresh()
            runOnUiThread {
                banner.visibility = if (ok) View.GONE else View.VISIBLE
                banner.text = "server is down"
            }
            if (ok && app.auth.hasCredentials()) connectWs()
        }
    }

    private fun connectWs() {
        ws?.close()
        ws = WsClient(app.auth, app.api.http, onFrame = { frame ->
            runOnUiThread {
                when (frame) {
                    is WsFrame.Timer -> {
                        // Remote stop/void (another client) reflects here via WS.
                        TimerState.session = frame.session
                        TimerState.emit()
                    }
                    is WsFrame.ProposalF -> voice.showProposal(frame.proposal)
                    is WsFrame.QuestionF -> voice.showQuestion(frame.question)
                    else -> TimerState.emit()
                }
            }
        })
        ws?.connect()
    }

    override fun onResume() {
        super.onResume()
        refreshGate()
    }

    override fun onDestroy() {
        ws?.close()
        super.onDestroy()
    }
}
