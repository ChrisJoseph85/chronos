package dev.chronos.app.net

import dev.chronos.app.data.AuthStore
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resumeWithException

class ApiException(val status: Int, message: String) : IOException("$status $message")

/** OkHttp REST client. Key travels only in X-Chronos-Key; never logged. */
class ChronosApi(
    private val auth: AuthStore,
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build(),
) {
    private fun base() = auth.serverUrl
    private fun key() = auth.instanceKey

    private suspend fun execute(req: Request): Pair<Int, String> =
        suspendCancellableCoroutine { cont ->
            val call = http.newCall(req)
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (!cont.isCompleted) cont.resumeWithException(e)
                }
                override fun onResponse(call: Call, resp: Response) {
                    resp.use {
                        val body = it.body?.string() ?: ""
                        if (!cont.isCompleted) cont.resumeWith(Result.success(it.code to body))
                    }
                }
            })
        }

    private suspend fun call(req: Request): String {
        val (code, body) = execute(req)
        when (code) {
            in 200..299 -> return body
            404 -> throw ApiException(404, "not found")
            409 -> throw ApiException(409, body.ifEmpty { "timer running" })
            401 -> throw ApiException(401, "invalid key")
            else -> throw ApiException(code, body.take(200))
        }
    }

    private fun obj(body: String): JVal.Obj = Json.parse(body) as JVal.Obj

    suspend fun getHealth(): String = call(ApiRoutes.health(base()))

    suspend fun getEvents(from: String, to: String): Pair<List<EventItem>, String> {
        val body = try {
            call(ApiRoutes.events(base(), key(), from, to))
        } catch (e: Exception) {
            throw e
        }
        return (Json.parse(body) as JVal.Arr).items.mapNotNull {
            (it as? JVal.Obj)?.let(EventItem::parse)
        } to body
    }

    suspend fun getNodes(parent: Long? = null, tag: String? = null): List<NodeInfo> {
        val body = call(ApiRoutes.nodes(base(), key(), parent, tag))
        return (Json.parse(body) as JVal.Arr).items.mapNotNull {
            (it as? JVal.Obj)?.let(NodeInfo::parse)
        }
    }

    suspend fun getBriefing(date: String): Pair<JVal.Obj, String> {
        val body = call(ApiRoutes.briefing(base(), key(), date))
        return obj(body) to body
    }

    suspend fun getTimer(): TimerSession? {
        val body = call(ApiRoutes.timerGet(base(), key()))
        return parseTimerOrNull(body)
    }

    suspend fun startTimer(label: String, mode: String, nodeId: Long?, targetMs: Long?): TimerSession {
        val body = call(ApiRoutes.timerStart(base(), key(), label, mode, nodeId, targetMs, "android"))
        return TimerSession.parse(obj(body))
    }

    suspend fun stopTimer(void: Boolean): TimerSession {
        val body = call(ApiRoutes.timerStop(base(), key(), "android", void))
        return TimerSession.parse(obj(body))
    }

    suspend fun getSummary(nodeId: Long? = null): Summary =
        Summary.parse(obj(call(ApiRoutes.timerSummary(base(), key(), nodeId))))

    suspend fun getPresets(): List<Triple<String, Long, Long>> {
        val body = call(ApiRoutes.presets(base(), key()))
        return (Json.parse(body) as JVal.Arr).items.mapNotNull {
            val o = it as? JVal.Obj ?: return@mapNotNull null
            Triple(o.str("name"), o.long("focus_minutes"), o.long("break_minutes"))
        }
    }

    suspend fun say(text: String, deviceId: String? = null): JVal.Obj =
        obj(call(ApiRoutes.say(base(), key(), text, deviceId)))

    suspend fun voice(audio: File): String {
        val body = call(ApiRoutes.voice(base(), key(), audio))
        return obj(body).str("transcript")
    }

    suspend fun getProviders(): Triple<List<ProviderEntry>, List<ProviderEntry>, List<ProviderEntry>> {
        val o = obj(call(ApiRoutes.providers(base(), key())))
        fun list(k: String) = o.arr(k).mapNotNull { (it as? JVal.Obj)?.let(ProviderEntry::parse) }
        return Triple(list("stt"), list("text"), list("embeddings"))
    }

    suspend fun providerAdd(group: String, name: String, url: String, model: String?): ProviderEntry =
        ProviderEntry.parse(obj(call(ApiRoutes.providerAdd(base(), key(), group, name, url, model))))

    suspend fun providerReorder(id: String, position: Int) {
        call(ApiRoutes.providerUpdate(base(), key(), id, position))
    }

    /** Breakdown via v1.2 endpoint; 404 maps to EndpointMissing ("server too old"). */
    suspend fun breakdownAdapter(): BreakdownRepository.BreakdownApi =
        object : BreakdownRepository.BreakdownApi {
            override suspend fun breakdown(
                nodeId: Long?, from: String, to: String,
            ): BreakdownRepository.BreakdownResult = try {
                val body = call(ApiRoutes.statsBreakdown(base(), key(), nodeId, from, to))
                val kids = (Json.parse(body) as JVal.Arr).items.mapNotNull {
                    (it as? JVal.Obj)?.let(BreakdownChild::parse)
                }
                BreakdownRepository.BreakdownResult.Ok(kids)
            } catch (e: ApiException) {
                if (e.status == 404) BreakdownRepository.BreakdownResult.EndpointMissing
                else BreakdownRepository.BreakdownResult.Error(e.message ?: "error")
            } catch (e: Exception) {
                BreakdownRepository.BreakdownResult.Error(e.message ?: "error")
            }
        }
}
