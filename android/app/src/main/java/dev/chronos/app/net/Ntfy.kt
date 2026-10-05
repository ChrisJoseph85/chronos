package dev.chronos.app.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/** ntfy (F-Droid build) for reminders/proposal/question/timer milestones. No Firebase. */
object Ntfy {
    private val TEXT = "text/plain; charset=utf-8".toMediaType()

    fun publish(http: OkHttpClient, topicUrl: String, message: String, title: String? = null) {
        try {
            val b = Request.Builder().url(topicUrl).post(message.toRequestBody(TEXT))
            if (title != null) b.header("Title", title)
            http.newCall(b.build()).execute().close()
        } catch (_: Exception) { }
    }
}
