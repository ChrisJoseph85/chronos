package com.chronos.ui

import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import com.chronos.ChronosApp
import com.chronos.net.Discovery
import com.chronos.shield.ShieldLogic
import com.chronos.shield.ShieldWatch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/**
 * Settings: server URL/key, port field (default 693), Auto-find
 * (localhost -> /24 with the SAVED key only, §9), blocklist, UsageStats
 * tripwire rationale (verbatim), providers add/reorder (keys never shown).
 */
class SettingsFragment : ScopedFragment() {
    private lateinit var urlInput: EditText
    private lateinit var keyInput: EditText
    private lateinit var portInput: EditText
    private lateinit var status: TextView
    private lateinit var providerBody: android.widget.LinearLayout
    private lateinit var blockBody: android.widget.LinearLayout
    private var scanning = false
    private var cancelled = false

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        val app = requireActivity().application as ChronosApp
        val p = app.prefs
        return col(requireContext()) {
            title(UiStrings.SETTINGS)
            urlInput = edit(UiStrings.HINT_SERVER_URL, p.serverUrl)
            keyInput = edit(UiStrings.HINT_INSTANCE_KEY, "").apply {
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                hint = if (p.apiKey.isEmpty()) UiStrings.HINT_INSTANCE_KEY else "Key Saved (Enter To Replace)"
            }
            portInput = edit(UiStrings.HINT_PORT, p.port.toString())
            status = text("")
            btn(if (!scanning) UiStrings.AUTO_FIND else UiStrings.CANCEL_SCAN) { toggleScan() }
            btn(UiStrings.SAVE) {
                val port = portInput.text.toString().toIntOrNull() ?: 693
                p.serverUrl = urlInput.text.toString().trim()
                val k = keyInput.text.toString()
                if (k.isNotEmpty()) p.apiKey = k // saved key only; never used at scan time
                p.port = port
                status.text = "Saved"
            }
            title(UiStrings.FOCUS_SHIELD)
            text(ShieldLogic.RATIONALE)
            if (!ShieldWatch.hasUsageAccess(requireContext())) {
                btn("Grant Usage Access (Tripwire Only)") {
                    startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
                }
            } else {
                text("Usage Access Granted")
            }
            title(UiStrings.BLOCKED_APPS)
            text("Checked Apps Trigger The Shield Tripwire")
            blockBody = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.VERTICAL
            }
            addView(blockBody)
            title("Providers (Keys Never Displayed)")
            providerBody = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.VERTICAL
            }
            addView(providerBody)
            row(
                android.widget.Button(context).apply {
                    text = UiStrings.RELOAD
                    setOnClickListener { loadProviders() }
                },
            )
        }
    }

    override fun onResume() {
        super.onResume()
        loadProviders()
        loadBlockedApps()
    }

    /** Visual multi-select list of launchable apps, persisted to prefs.blocklist. */
    private fun loadBlockedApps() {
        val act = activity as? MainActivity ?: return
        val app = act.application as ChronosApp
        scope.launch {
            val entries = withContext(Dispatchers.IO) {
                BlockedApps.sort(BlockedApps.queryLaunchable(requireContext().packageManager))
            }
            if (!isAdded) return@launch
            blockBody.removeAllViews()
            if (entries.isEmpty()) {
                blockBody.addView(TextView(context).apply { text = UiStrings.EMPTY })
                return@launch
            }
            var blocked = app.prefs.blocklist
            for (e in entries) {
                val rowView = android.widget.LinearLayout(context).apply {
                    orientation = android.widget.LinearLayout.HORIZONTAL
                }
                val icon = android.widget.ImageView(context).apply {
                    layoutParams = android.widget.LinearLayout.LayoutParams(96, 96)
                    try {
                        setImageDrawable(e.icon)
                    } catch (_: Exception) {
                    }
                }
                val check = android.widget.CheckBox(context).apply {
                    text = e.label
                    isChecked = blocked.contains(e.packageName)
                    setOnCheckedChangeListener { _, on ->
                        blocked = BlockedApps.toggle(blocked, e.packageName).let {
                            if (on) it + e.packageName else it - e.packageName
                        }
                        // Persisted to prefs, consumed by the shield tripwire.
                        app.prefs.blocklist = blocked
                    }
                }
                rowView.addView(icon)
                rowView.addView(check)
                blockBody.addView(rowView)
            }
        }
    }

    private fun toggleScan() {
        if (scanning) {
            cancelled = true
            return
        }
        val act = activity as? MainActivity ?: return
        val app = act.application as ChronosApp
        // §9: scan authenticates with the SAVED key only — never the text field.
        val savedKey = app.prefs.apiKey
        if (savedKey.isEmpty()) {
            status.text = "Save The Instance Key First (Scan Uses The Saved Key Only)"
            return
        }
        val port = portInput.text.toString().toIntOrNull() ?: 693
        scanning = true
        cancelled = false
        status.text = "Scanning…"
        scope.launch {
            val localIp = withContext(Dispatchers.IO) { deviceIp() }
            val client = OkHttpClient.Builder()
                .connectTimeout(900, TimeUnit.MILLISECONDS)
                .readTimeout(900, TimeUnit.MILLISECONDS)
                .build()
            val probe = object : Discovery.Probe {
                override fun healthy(url: String, timeoutMs: Int): Boolean = try {
                    client.newCall(
                        okhttp3.Request.Builder().url("$url/api/health").get().build(),
                    ).execute().use { it.isSuccessful }
                } catch (_: Exception) {
                    false
                }

                override fun authorized(url: String, key: String, timeoutMs: Int): Boolean = try {
                    // Saved-key-only probe: a lightweight authed GET.
                    client.newCall(
                        okhttp3.Request.Builder().url("$url/api/timer").header("X-Chronos-Key", key).get().build(),
                    ).execute().use { it.code != 401 }
                } catch (_: Exception) {
                    false
                }
            }
            val found = withContext(Dispatchers.IO) {
                Discovery(port).scan(
                    localIp, savedKey, probe,
                    isCancelled = { cancelled },
                    onProgress = { host -> launch { if (isAdded) status.text = "Trying $host…" } },
                )
            }
            scanning = false
            if (!isAdded) return@launch
            if (found != null) {
                urlInput.setText(found)
                status.text = "Found $found (URL Filled — Save To Keep)"
            } else if (cancelled) {
                status.text = "Scan Cancelled"
            } else {
                status.text = "No Server Found"
            }
        }
    }

    private fun deviceIp(): String? {
        return try {
            val wm = requireContext().applicationContext.getSystemService(android.content.Context.WIFI_SERVICE) as WifiManager
            val ip = wm.connectionInfo.ipAddress
            "${ip and 0xFF}.${ip shr 8 and 0xFF}.${ip shr 16 and 0xFF}.${ip shr 24 and 0xFF}"
        } catch (_: Exception) {
            null
        }
    }

    private fun loadProviders() {
        val act = activity as? MainActivity ?: return
        if (act.readOnly) return
        scope.launch {
            val app = act.application as ChronosApp
            try {
                val pv = withContext(Dispatchers.IO) { app.api().providers() }
                if (!isAdded) return@launch
                providerBody.removeAllViews()
                for (group in listOf("stt" to pv.stt, "text" to pv.text, "embeddings" to pv.embeddings)) {
                    providerBody.addView(TextView(context).apply { text = group.first; textSize = 16f })
                    group.second.forEachIndexed { idx, e ->
                        // Keys NEVER displayed: only key_count/key_ids (server never returns values).
                        val r = android.widget.LinearLayout(context).apply {
                            orientation = android.widget.LinearLayout.HORIZONTAL
                        }
                        r.addView(TextView(context).apply { text = "${e.name} (${e.key_count} keys)" })
                        r.addView(
                            android.widget.Button(context).apply {
                                text = "↑"
                                setOnClickListener { moveProvider(e.id, idx - 1) }
                            },
                        )
                        r.addView(
                            android.widget.Button(context).apply {
                                text = "↓"
                                setOnClickListener { moveProvider(e.id, idx + 1) }
                            },
                        )
                        r.addView(
                            android.widget.Button(context).apply {
                                text = "+Key"
                                setOnClickListener {
                                    if (!act.blockedWrite()) {
                                        val v = android.widget.EditText(context).apply { hint = "Paste Key (Sent Once, Never Shown)" }
                                        providerBody.addView(v)
                                        v.setOnEditorActionListener { _, _, _ ->
                                            scope.launch {
                                                try {
                                                    withContext(Dispatchers.IO) { app.api().addProviderKey(e.id, v.text.toString()) }
                                                    providerBody.removeView(v)
                                                    loadProviders()
                                                } catch (_: Exception) {
                                                }
                                            }
                                            true
                                        }
                                    }
                                }
                            },
                        )
                        providerBody.addView(r)
                    }
                }
            } catch (_: Exception) {
            }
        }
    }

    private fun moveProvider(id: String, position: Int) {
        if (position < 0) return
        val act = activity as? MainActivity ?: return
        scope.launch {
            try {
                withContext(Dispatchers.IO) { (act.application as ChronosApp).api().moveProvider(id, position) }
                loadProviders()
            } catch (_: Exception) {
            }
        }
    }
}
