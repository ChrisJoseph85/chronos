package com.chronos.ui

import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ResolveInfo
import android.graphics.drawable.Drawable

/** One launchable app row for the blocklist picker. */
data class BlockedAppEntry(
    val packageName: String,
    val label: String,
    val icon: Drawable?,
)

/** Blocklist helpers: pure parts unit-tested, PM query kept thin. */
object BlockedApps {
    /** Toggle [pkg] in [current]: add if absent, remove if present. */
    fun toggle(current: Set<String>, pkg: String): Set<String> =
        if (current.contains(pkg)) current - pkg else current + pkg

    /** Sort entries by label, case-insensitive. */
    fun sort(entries: List<BlockedAppEntry>): List<BlockedAppEntry> =
        entries.sortedBy { it.label.lowercase() }

    /** Persist round-trip goes through SettingsRepo.blocklist (see PolishTest). */
    fun queryLaunchable(pm: PackageManager): List<BlockedAppEntry> {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val infos: List<ResolveInfo> = try {
            pm.queryIntentActivities(intent, 0)
        } catch (_: Exception) {
            emptyList()
        }
        return infos.mapNotNull { ri ->
            val pkg = ri.activityInfo?.packageName ?: return@mapNotNull null
            val label = try {
                ri.loadLabel(pm)?.toString() ?: pkg
            } catch (_: Exception) {
                pkg
            }
            val icon = try {
                ri.loadIcon(pm)
            } catch (_: Exception) {
                null
            }
            BlockedAppEntry(pkg, label, icon)
        }.distinctBy { it.packageName }
    }
}
