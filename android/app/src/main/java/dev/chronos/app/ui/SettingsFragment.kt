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
import dev.chronos.app.shield.ShieldPrefsStore
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
