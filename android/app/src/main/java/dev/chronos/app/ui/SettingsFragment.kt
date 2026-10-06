package dev.chronos.app.ui

import android.app.AppOpsManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment
import dev.chronos.app.ChronosApp
import dev.chronos.app.net.ProviderEntry
import dev.chronos.app.net.ServerDiscovery
import dev.chronos.app.shield.ShieldPrefsStore
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * Settings: server URL/key (keys never displayed), blocklist picker,
 * providers (v1.1 /api/providers: add/reorder, keys never displayed).
 */
class SettingsFragment : Fragment() {
    private val app get() = requireContext().applicationContext as ChronosApp
    private lateinit var body: LinearLayout

    override fun onCreateView(inf: LayoutInflater, c: ViewGroup?, s: Bundle?): View {
        val ctx = requireContext()
        body = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        val url = EditText(ctx).apply { hint = "Server URL"; setText(app.auth.serverUrl) }
        // Key field is always blank: keys are never displayed.
        val key = EditText(ctx).apply { hint = "Instance key (never shown)" }
        val save = Button(ctx).apply { text = "Save" }
        save.setOnClickListener {
            app.auth.serverUrl = url.text.toString()
            if (key.text.isNotEmpty()) app.auth.instanceKey = key.text.toString()
            key.setText("")
        }
        body.addView(url)
        body.addView(key)
        body.addView(save)

        // §9 auto-discovery: port field + Auto-find. Manual entry stays untouched.
        val port = EditText(ctx).apply {
            hint = "Discovery port (default 693)"
            setText(ServerDiscovery.DEFAULT_PORT.toString())
        }
        val progress = TextView(ctx).apply { text = "" }
        val autoFind = Button(ctx).apply { text = "Auto-find server" }
        val cancel = Button(ctx).apply { text = "Cancel"; visibility = View.GONE }
        var sweep: Job? = null
        autoFind.setOnClickListener {
            val p = port.text.toString().toIntOrNull() ?: ServerDiscovery.DEFAULT_PORT
            val savedKey = app.auth.instanceKey // SAVED key only; never a typed key.
            val hosts = ServerDiscovery.candidates(p, ServerDiscovery.deviceLanIp())
            progress.text = "Scanning 0/${hosts.size}…"
            autoFind.isEnabled = false
            cancel.visibility = View.VISIBLE
            sweep = app.io.launch {
                val discovery = ServerDiscovery.realProbes()
                val win = try {
                    discovery.findFirst(hosts, savedKey) { n, total, host ->
                        activity?.runOnUiThread { progress.text = "Scanning $n/$total… $host" }
                    }
                } catch (_: Exception) {
                    null
                }
                activity?.runOnUiThread {
                    autoFind.isEnabled = true
                    cancel.visibility = View.GONE
                    if (win != null) {
                        url.setText(win) // winner fills URL field; user still taps Save.
                        progress.text = "Found: $win"
                    } else if (progress.text.startsWith("Cancelled")) {
                        // keep cancel message
                    } else {
                        progress.text = "Not found on port $p."
                    }
                }
            }
        }
        cancel.setOnClickListener {
            sweep?.cancel()
            sweep = null
            progress.text = "Cancelled."
            autoFind.isEnabled = true
            cancel.visibility = View.GONE
        }
        body.addView(port)
        body.addView(autoFind)
        body.addView(cancel)
        body.addView(progress)

        body.addView(TextView(ctx).apply {
            text = "Usage access: used only to detect a blocked app opening; " +
                "no usage statistics are collected, stored, or sent anywhere."
        })
        val usage = Button(ctx).apply { text = "Grant usage access" }
        usage.setOnClickListener { startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)) }
        body.addView(usage)
        body.addView(TextView(ctx).apply {
            text = if (hasUsageAccess()) "Usage access: granted" else "Usage access: not granted"
        })

        val block = EditText(ctx).apply { hint = "Blocklist (comma-separated packages)" }
        block.setText(ShieldPrefsStore(ctx).blocklist.joinToString(","))
        val blockSave = Button(ctx).apply { text = "Save blocklist" }
        blockSave.setOnClickListener {
            ShieldPrefsStore(ctx).blocklist =
                block.text.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        }
        body.addView(block)
        body.addView(blockSave)

        val provTitle = TextView(ctx).apply { text = "Providers"; textSize = 18f }
        body.addView(provTitle)
        val provList = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        body.addView(provList)
        loadProviders(provList)

        val g = EditText(ctx).apply { hint = "group (stt/text/embeddings)" }
        val n = EditText(ctx).apply { hint = "name" }
        val u = EditText(ctx).apply { hint = "base_url" }
        val add = Button(ctx).apply { text = "Add provider" }
        add.setOnClickListener {
            app.io.launch {
                try {
                    app.api.providerAdd(g.text.toString(), n.text.toString(), u.text.toString(), null)
                    activity?.runOnUiThread { loadProviders(provList) }
                } catch (_: Exception) { }
            }
        }
        body.addView(g)
        body.addView(n)
        body.addView(u)
        body.addView(add)
        return body
    }

    private fun hasUsageAccess(): Boolean {
        val ops = requireContext().getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        return ops.checkOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            android.os.Process.myUid(), requireContext().packageName,
        ) == AppOpsManager.MODE_ALLOWED
    }

    private fun loadProviders(box: LinearLayout) {
        app.io.launch {
            val all: List<ProviderEntry> = try {
                val (stt, text, emb) = app.api.getProviders()
                stt + text + emb
            } catch (_: Exception) {
                emptyList()
            }
            activity?.runOnUiThread {
                box.removeAllViews()
                all.forEachIndexed { idx, e ->
                    val row = LinearLayout(requireContext()).apply { orientation = LinearLayout.HORIZONTAL }
                    row.addView(TextView(requireContext()).apply {
                        // Name + key count only; key values never displayed.
                        text = "${e.group}/${e.name} (${e.keyCount} keys)"
                    })
                    if (idx > 0) {
                        val up = Button(requireContext()).apply { text = "↑" }
                        up.setOnClickListener {
                            app.io.launch {
                                try {
                                    app.api.providerReorder(e.id, idx - 1)
                                    activity?.runOnUiThread { loadProviders(box) }
                                } catch (_: Exception) { }
                            }
                        }
                        row.addView(up)
                    }
                    box.addView(row)
                }
            }
        }
    }
}
