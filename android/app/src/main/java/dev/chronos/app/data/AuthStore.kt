package dev.chronos.app.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Server URL + instance key in EncryptedSharedPreferences. Key never logged. */
class AuthStore(ctx: Context) {
    private val prefs: SharedPreferences = try {
        val masterKey = MasterKey.Builder(ctx)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            ctx, "chronos_auth", masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    } catch (_: Exception) {
        // Emulator/CI fallback: plain prefs so debug builds never crash.
        ctx.getSharedPreferences("chronos_auth_plain", Context.MODE_PRIVATE)
    }

    var serverUrl: String
        get() = prefs.getString("server_url", "http://127.0.0.1:8080") ?: "http://127.0.0.1:8080"
        set(v) { prefs.edit().putString("server_url", v.trimEnd('/')).apply() }

    var instanceKey: String
        get() = prefs.getString("instance_key", "") ?: ""
        set(v) { prefs.edit().putString("instance_key", v).apply() }

    fun hasCredentials(): Boolean = instanceKey.isNotEmpty()
}
