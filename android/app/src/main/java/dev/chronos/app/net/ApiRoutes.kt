package dev.chronos.app.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File

/** Builds every REST/WS request. Key travels ONLY in the X-Chronos-Key header. */
object ApiRoutes {
    const val KEY_HEADER = "X-Chronos-Key"
    private val JSON = "application/json; charset=utf-8".toMediaType()

    private fun base(url: String, path: String): String =
        url.trimEnd('/') + path

    private fun authed(url: String, key: String): Request.Builder =
        Request.Builder().url(url).header(KEY_HEADER, key)

    /** Safe to log: method + URL only, never headers/body. */
    fun Request.redactedLog(): String = "$method $url"

    fun health(baseUrl: String): Request =
        Request.Builder().url(base(baseUrl, "/api/health")).get().build()

    private fun get(baseUrl: String, key: String, path: String): Request =
        authed(base(baseUrl, path), key).get().build()

    private fun post(baseUrl: String, key: String, path: String, json: String): Request =
        authed(base(baseUrl, path), key).post(json.toRequestBody(JSON)).build()

    private fun put(baseUrl: String, key: String, path: String, json: String): Request =
        authed(base(baseUrl, path), key).put(json.toRequestBody(JSON)).build()

    fun events(baseUrl: String, key: String, from: String, to: String): Request =
        get(baseUrl, key, "/api/events?from=$from&to=$to")

    fun nodes(baseUrl: String, key: String, parent: Long? = null, tag: String? = null): Request {
        var p = "/api/nodes"
        val q = listOfNotNull(
            parent?.let { "parent=$it" },
            tag?.let { "tag=$it" },
        )
        if (q.isNotEmpty()) p += "?" + q.joinToString("&")
        return get(baseUrl, key, p)
    }

    fun briefing(baseUrl: String, key: String, date: String): Request =
        get(baseUrl, key, "/api/briefing?date=$date")

    fun timerGet(baseUrl: String, key: String, nodeId: Long? = null): Request =
        get(baseUrl, key, if (nodeId == null) "/api/timer" else "/api/timer?node_id=$nodeId")

    fun timerStart(
        baseUrl: String, key: String,
        label: String, mode: String, nodeId: Long?, targetMs: Long?, source: String,
    ): Request {
        val parts = mutableListOf(
            "\"label\":${q(label)}", "\"mode\":${q(mode)}", "\"source\":${q(source)}",
        )
        if (nodeId != null) parts.add("\"node_id\":$nodeId")
        if (targetMs != null) parts.add("\"target_ms\":$targetMs")
        return post(baseUrl, key, "/api/timer/start", "{${parts.joinToString(",")}}")
    }

    /** v1.2: void flag. Absent on old servers -> caller falls back gracefully. */
    fun timerStop(baseUrl: String, key: String, source: String, void: Boolean): Request =
        post(
            baseUrl, key, "/api/timer/stop",
            if (void) "{\"source\":${q(source)},\"void\":true}"
            else "{\"source\":${q(source)}}",
        )

    fun timerSummary(baseUrl: String, key: String, nodeId: Long? = null): Request =
        get(baseUrl, key, if (nodeId == null) "/api/timer/summary" else "/api/timer/summary?node_id=$nodeId")

    /** v1.2: 404 on old servers -> UI shows "server too old". */
    fun statsBreakdown(baseUrl: String, key: String, nodeId: Long?, from: String, to: String): Request {
        var p = "/api/stats/breakdown?from=$from&to=$to"
        if (nodeId != null) p += "&node_id=$nodeId"
        return get(baseUrl, key, p)
    }

    fun presets(baseUrl: String, key: String): Request =
        get(baseUrl, key, "/api/timer/presets")

    fun say(baseUrl: String, key: String, text: String, deviceId: String?): Request {
        val d = if (deviceId == null) "" else ",\"device_id\":${q(deviceId)}"
        return post(baseUrl, key, "/api/say", "{\"text\":${q(text)}$d}")
    }

    fun voice(baseUrl: String, key: String, audio: File): Request {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("audio", audio.name, audio.asRequestBody("audio/*".toMediaType()))
            .build()
        return authed(base(baseUrl, "/api/voice"), key).post(body).build()
    }

    fun providers(baseUrl: String, key: String): Request =
        get(baseUrl, key, "/api/providers")

    fun providerAdd(baseUrl: String, key: String, group: String, name: String, baseUrl2: String, model: String?): Request {
        val m = if (model == null) "" else ",\"model\":${q(model)}"
        return post(baseUrl, key, "/api/providers",
            "{\"group\":${q(group)},\"name\":${q(name)},\"base_url\":${q(baseUrl2)}$m}")
    }

    fun providerUpdate(baseUrl: String, key: String, id: String, position: Int): Request =
        put(baseUrl, key, "/api/providers/$id", "{\"position\":$position}")

    fun wsUrl(baseUrl: String): String {
        val t = baseUrl.trimEnd('/')
        return when {
            t.startsWith("https://") -> "wss://" + t.removePrefix("https://") + "/ws"
            t.startsWith("http://") -> "ws://" + t.removePrefix("http://") + "/ws"
            else -> "$t/ws"
        }
    }

    private fun q(s: String): String = "\"" + s
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n") + "\""
}
