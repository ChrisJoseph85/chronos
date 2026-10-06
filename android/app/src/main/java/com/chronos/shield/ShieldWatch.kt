package com.chronos.shield

import android.app.AppOpsManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Process

/** Android glue for the tripwire. No measurement — foreground package only. */
object ShieldWatch {
    fun hasUsageAccess(ctx: Context): Boolean {
        val ops = ctx.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = ops.checkOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName,
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun foregroundPackage(ctx: Context): String? {
        return try {
            val usm = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
            val now = System.currentTimeMillis()
            val stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, now - 10_000, now)
            stats.maxByOrNull { it.lastTimeUsed }?.packageName
        } catch (_: Exception) {
            null
        }
    }
}
