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
    private lateinit var blockInput: EditText
    private lateinit var status: TextView
    private lateinit var providerBody: android.widget.LinearLayout
    private var scanning = false
    private var cancelled = false

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        val app = requireActivity().application as ChronosApp
        val p = app.prefs
        return col(requireContext()) {
            title("Settings")
            urlInput = edit("server URL", p.serverUrl)
            keyInput = edit("instance key", "").apply {
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                hint = if (p.apiKey.isEmpty()) "instance key" else "key saved (enter to replace)"
            }
            portInput = edit("port", p.port.toString())
            status = text("")
            btn(if (!scanning) "Auto-find server" else "Cancel scan") { toggleScan() }
            btn("Save") {
                val port = portInput.text.toString().toIntOrNull() ?: 693
                p.serverUrl = urlInput.text.toString().trim()
                val k = keyInput.text.toString()
                if (k.isNotEmpty()) p.apiKey = k // saved key only; never used at scan time
                p.port = port
                p.blocklist = blockInput.text.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
                status.text = "saved"
            }
            title("Focus shield")
            text(ShieldLogic.RATIONALE)
            if (!ShieldWatch.hasUsageAccess(requireContext())) {
                btn("Grant usage access (tripwire only)") {
                    startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
                }
            } else {
                text("usage access granted")
            }
            blockInput = edit("blocklist (comma packages)", p.blocklist.joinToString(","))
            title("Providers (keys never displayed)")
            providerBody = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.VERTICAL
            }
            addView(providerBody)
            row(
                android.widget.Button(context).apply {
                    text = "Reload"
                    setOnClickListener { loadProviders() }
                },
            )
        }
    }

    override fun onResume() {
        super.onResume()
        loadProviders()
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
            status.text = "save the instance key first (scan uses the saved key only)"
            return
        }
        val port = portInput.text.toString().toIntOrNull() ?: 693
        scanning = true
        cancelled = false
        status.text = "scanning…"
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
                    onProgress = { host -> launch { if (isAdded) status.text = "trying $host…" } },
                )
            }
            scanning = false
            if (!isAdded) return@launch
            if (found != null) {
                urlInput.setText(found)
                status.text = "found $found (URL filled — Save to keep)"
            } else if (cancelled) {
                status.text = "scan cancelled"
            } else {
                status.text = "no server found"
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
                                text = "+key"
                                setOnClickListener {
                                    if (!act.blockedWrite()) {
                                        val v = android.widget.EditText(context).apply { hint = "paste key (sent once, never shown)" }
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
