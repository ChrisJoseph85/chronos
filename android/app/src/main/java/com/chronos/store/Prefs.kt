package com.chronos.store

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Settings surface. Defaults: port 693, strict shield ON, mode stopwatch. */
interface SettingsRepo {
    var serverUrl: String
    var apiKey: String
    var port: Int
    var strictShield: Boolean
    var timerMode: String
    var blocklist: Set<String>
    var ntfyTopic: String
    fun cached(key: String): String?
    fun setCached(key: String, value: String)
}

/** Pure-memory impl for unit tests and previews. */
class MemoryPrefs : SettingsRepo {
    override var serverUrl: String = ""
    override var apiKey: String = ""
    override var port: Int = 693
    override var strictShield: Boolean = true
    override var timerMode: String = "stopwatch"
    override var blocklist: Set<String> = emptySet()
    override var ntfyTopic: String = ""
    private val cache = mutableMapOf<String, String>()
    override fun cached(key: String): String? = cache[key]
    override fun setCached(key: String, value: String) {
        cache[key] = value
    }
}

/** EncryptedSharedPreferences impl. The key is stored encrypted, never logged. */
class AndroidPrefs(context: Context) : SettingsRepo {
    private val mk = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
    private val p = EncryptedSharedPreferences.create(
        context, "chronos", mk,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    override var serverUrl: String
        get() = p.getString("server_url", "") ?: ""
        set(v) = p.edit().putString("server_url", v).apply()
    override var apiKey: String
        get() = p.getString("api_key", "") ?: ""
        set(v) = p.edit().putString("api_key", v).apply()
    override var port: Int
        get() = p.getInt("port", 693)
        set(v) = p.edit().putInt("port", v).apply()
    override var strictShield: Boolean
        get() = p.getBoolean("strict", true)
        set(v) = p.edit().putBoolean("strict", v).apply()
    override var timerMode: String
        get() = p.getString("timer_mode", "stopwatch") ?: "stopwatch"
        set(v) = p.edit().putString("timer_mode", v).apply()
    override var blocklist: Set<String>
        get() = p.getStringSet("blocklist", emptySet()) ?: emptySet()
        set(v) = p.edit().putStringSet("blocklist", v).apply()
    override var ntfyTopic: String
        get() = p.getString("ntfy", "") ?: ""
        set(v) = p.edit().putString("ntfy", v).apply()
    override fun cached(key: String): String? = p.getString("cache_$key", null)
    override fun setCached(key: String, value: String) {
        p.edit().putString("cache_$key", value).apply()
    }
}
