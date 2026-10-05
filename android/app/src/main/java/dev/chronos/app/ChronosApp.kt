package dev.chronos.app

import android.app.Application
import dev.chronos.app.data.AuthStore
import dev.chronos.app.data.CacheStore
import dev.chronos.app.net.ChronosApi
import dev.chronos.app.net.HealthGate
import dev.chronos.app.shield.ShieldManager
import dev.chronos.app.shield.ShieldPrefsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class ChronosApp : Application() {
    val io = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    lateinit var auth: AuthStore
    lateinit var cache: CacheStore
    lateinit var api: ChronosApi
    lateinit var shield: ShieldManager
    val health: HealthGate by lazy {
        HealthGate(probe = {
            try {
                api.getHealth()
                true
            } catch (_: Exception) {
                false
            }
        })
    }

    override fun onCreate() {
        super.onCreate()
        auth = AuthStore(this)
        cache = CacheStore(this)
        api = ChronosApi(auth)
        shield = ShieldManager(ShieldPrefsStore(this))
    }
}
