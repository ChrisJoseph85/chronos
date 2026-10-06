package com.chronos

import android.app.Application
import com.chronos.api.RealChronosApi
import com.chronos.api.WsClient
import com.chronos.store.AndroidPrefs

class ChronosApp : Application() {
    val prefs by lazy { AndroidPrefs(this) }
    fun api() = RealChronosApi(prefs.serverUrl, { prefs.apiKey })
    val ws by lazy { WsClient(prefs.serverUrl, { prefs.apiKey }) }
}
