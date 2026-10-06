package com.chronos.api

import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * ntfy (F-Droid build, no Firebase): reminders / proposal / question /
 * timer milestones. Polls the topic SSE stream when configured.
 */
class NtfyClient(private val http: OkHttpClient = OkHttpClient()) {
    interface Listener {
        fun onMessage(text: String)
    }

    @Volatile
    private var running = false

    fun poll(topicUrl: String, listener: Listener) {
        if (running || topicUrl.isEmpty()) return
        running = true
        Thread {
            try {
                http.newCall(Request.Builder().url("$topicUrl/sse").get().build()).execute().use { resp ->
                    val src = resp.body?.source() ?: return@use
                    while (running) {
                        val line = try {
                            src.readUtf8Line() ?: break
                        } catch (_: Exception) {
                            break
                        }
                        if (line.startsWith("data:")) listener.onMessage(line.removePrefix("data:").trim())
                    }
                }
            } catch (_: Exception) {
            } finally {
                running = false
            }
        }.start()
    }

    fun stop() {
        running = false
    }
}
