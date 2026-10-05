package dev.chronos.app.shield

import android.content.Context

class ShieldPrefsStore(ctx: Context) : ShieldManager.ShieldStore {
    private val p = ctx.getSharedPreferences("chronos_shield", Context.MODE_PRIVATE)
    override var attempts: Int
        get() = p.getInt("attempts", 0)
        set(v) { p.edit().putInt("attempts", v).apply() }
    override var strict: Boolean
        get() = p.getBoolean("strict", true)
        set(v) { p.edit().putBoolean("strict", v).apply() }

    var blocklist: Set<String>
        get() = p.getStringSet("blocklist", emptySet()) ?: emptySet()
        set(v) { p.edit().putStringSet("blocklist", v).apply() }
}
