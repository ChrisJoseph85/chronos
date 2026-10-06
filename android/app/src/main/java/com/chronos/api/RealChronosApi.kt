package com.chronos.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * OkHttp implementation. Auth = X-Chronos-Key header on every call.
 * The key is NEVER logged (all logs go through SafeLog with redaction).
 * v1.2 routes degrade to [ServerTooOld] on 404 so the UI can fall back.
 */
class RealChronosApi(
    baseUrl: String,
    private val key: () -> String,
    client: OkHttpClient? = null,
) : ChronosApi {
    private val base = baseUrl.trim().trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }
    private val http = client ?: OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private fun req(path: String): Request.Builder =
        Request.Builder().url(base + path).header("X-Chronos-Key", key())

    private suspend fun get(path: String): String = withContext(Dispatchers.IO) {
        SafeLog.d("api", "GET $path")
        http.newCall(req(path).get().build()).execute().use { resp ->
            bodyOrThrow(resp.code, path, resp.body?.string() ?: "")
        }
    }

    private suspend fun post(path: String, bodyJson: String): String = withContext(Dispatchers.IO) {
        // Body may echo labels, never the key — still redact defensively.
        SafeLog.d("api", "POST $path ${bodyJson.take(300)}", key())
        val body = bodyJson.toRequestBody("application/json".toMediaType())
        http.newCall(req(path).post(body).build()).execute().use { resp ->
            bodyOrThrow(resp.code, path, resp.body?.string() ?: "")
        }
    }

    private fun bodyOrThrow(code: Int, path: String, body: String): String {
        if (code in 200..299) return body
        if (code == 404 && (path == "/api/stats/breakdown" || path.startsWith("/api/stats/breakdown?"))) {
            throw ServerTooOld("GET $path")
        }
        throw ApiException(code, "$path -> HTTP $code", body.take(500))
    }

    override suspend fun health(): Health =
        json.decodeFromString(Health.serializer(), get("/api/health"))

    override suspend fun timerGet(): TimerSession? {
        val raw = get("/api/timer").trim()
        if (raw.isEmpty() || raw == "null") return null
        return json.decodeFromString(TimerSession.serializer(), raw)
    }

    override suspend fun timerStart(body: TimerStart): TimerSession =
        json.decodeFromString(
            TimerSession.serializer(),
            post("/api/timer/start", json.encodeToString(TimerStart.serializer(), body)),
        )

    override suspend fun timerStop(source: String, void: Boolean): TimerSession {
        return try {
            json.decodeFromString(
                TimerSession.serializer(),
                post("/api/timer/stop", json.encodeToString(TimerStop.serializer(), TimerStop(source, void))),
            )
        } catch (e: ApiException) {
            // Graceful "server too old" fallback: pre-v1.2 servers reject the
            // void flag (404/422). Retry as a plain stop and keep time.
            if (void && (e.code == 404 || e.code == 422)) {
                SafeLog.d("api", "stop void unsupported, plain-stop fallback")
                json.decodeFromString(
                    TimerSession.serializer(),
                    post("/api/timer/stop", json.encodeToString(TimerStop.serializer(), TimerStop(source, false))),
                )
            } else throw e
        }
    }

    override suspend fun timerPresets(): List<TimerPreset> =
        json.decodeFromString(ListSerializer(TimerPreset.serializer()), get("/api/timer/presets"))

    override suspend fun timerSummary(nodeId: String?): TimerSummary =
        json.decodeFromString(
            TimerSummary.serializer(),
            get("/api/timer/summary" + (nodeId?.let { "?node_id=$it" } ?: "")),
        )

    override suspend fun breakdown(nodeId: String?, from: String, to: String): List<BreakdownItem> {
        val q = "?from=$from&to=$to" + (nodeId?.let { "&node_id=$it" } ?: "")
        return json.decodeFromString(ListSerializer(BreakdownItem.serializer()), get("/api/stats/breakdown$q"))
    }

    override suspend fun events(from: String, to: String): List<CalEvent> =
        json.decodeFromString(ListSerializer(CalEvent.serializer()), get("/api/events?from=$from&to=$to"))

    override suspend fun nodes(parent: String?): List<Node> =
        json.decodeFromString(
            ListSerializer(Node.serializer()),
            get("/api/nodes" + (parent?.let { "?parent=$it" } ?: "")),
        )

    override suspend fun briefing(date: String): Briefing =
        json.decodeFromString(Briefing.serializer(), get("/api/briefing?date=$date"))

    override suspend fun say(text: String): SayResult =
        json.decodeFromString(
            SayResult.serializer(),
            post("/api/say", """{"text":${json.encodeToString(String.serializer(), text)},"device_id":"android"}"""),
        )

    override suspend fun voice(audio: ByteArray, fileName: String): String = withContext(Dispatchers.IO) {
        SafeLog.d("api", "POST /api/voice (${audio.size} bytes)")
        val part = MultipartBody.Part.createFormData(
            "audio", fileName, audio.toRequestBody("audio/mp4".toMediaType()),
        )
        val body = MultipartBody.Builder().setType(MultipartBody.FORM).addPart(part).build()
        http.newCall(req("/api/voice").post(body).build()).execute().use { resp ->
            val raw = bodyOrThrow(resp.code, "/api/voice", resp.body?.string() ?: "")
            json.parseToJsonElement(raw).let {
                it.toString()
            }.let { raw2 ->
                // {transcript} — parse leniently.
                try {
                    json.decodeFromJsonElement(Transcript.serializer(), json.parseToJsonElement(raw2)).transcript
                } catch (_: Exception) {
                    throw ApiException(resp.code, "bad voice response")
                }
            }
        }
    }

    @kotlinx.serialization.Serializable
    private data class Transcript(val transcript: String = "")

    override suspend fun providers(): Providers =
        json.decodeFromString(Providers.serializer(), get("/api/providers"))

    override suspend fun addProvider(group: String, name: String, baseUrl: String): ProviderEntry =
        json.decodeFromString(
            ProviderEntry.serializer(),
            post(
                "/api/providers",
                """{"group":"$group","name":${json.encodeToString(String.serializer(), name)},"base_url":${json.encodeToString(String.serializer(), baseUrl)}}""",
            ),
        )

    override suspend fun moveProvider(id: String, position: Int): ProviderEntry =
        json.decodeFromString(
            ProviderEntry.serializer(),
            put("/api/providers/$id", """{"position":$position}"""),
        )

    private suspend fun put(path: String, bodyJson: String): String = withContext(Dispatchers.IO) {
        SafeLog.d("api", "PUT $path", key())
        val body = bodyJson.toRequestBody("application/json".toMediaType())
        http.newCall(req(path).put(body).build()).execute().use { resp ->
            bodyOrThrow(resp.code, path, resp.body?.string() ?: "")
        }
    }

    override suspend fun addProviderKey(id: String, key: String): String {
        val raw = post(
            "/api/providers/$id/keys",
            """{"key":${json.encodeToString(String.serializer(), key)}}""",
        )
        return try {
            json.decodeFromJsonElement(KeyId.serializer(), json.parseToJsonElement(raw)).key_id
        } catch (_: Exception) {
            raw.take(64)
        }
    }

    @kotlinx.serialization.Serializable
    private data class KeyId(val key_id: String = "")

    override suspend fun settings(): Map<String, String> =
        json.decodeFromString(MapSerializer(String.serializer(), String.serializer()), get("/api/settings"))
}
