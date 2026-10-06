package dev.chronos.app.net

import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.IOException
import kotlin.coroutines.resume

/** OkHttp probes for discovery: ≤1s timeouts set by caller client. Key only in header. */
internal class RealProbeHttp(private val http: OkHttpClient) {
    private suspend fun code(req: Request): Int =
        suspendCancellableCoroutine { cont ->
            val call = http.newCall(req)
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (!cont.isCompleted) cont.resume(-1)
                }

                override fun onResponse(call: Call, resp: Response) {
                    resp.use { if (!cont.isCompleted) cont.resume(it.code) }
                }
            })
        }

    /** Unauthenticated health gate. */
    suspend fun healthOk(baseUrl: String): Boolean =
        code(ApiRoutes.health(baseUrl)) in 200..299

    /** ONE authenticated probe with the SAVED key; 401 = not authorized here. */
    suspend fun authOk(baseUrl: String, key: String): Boolean {
        if (key.isEmpty()) return false
        return code(ApiRoutes.nodes(baseUrl, key)) in 200..299
    }
}
