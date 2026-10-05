package dev.chronos.app.net

import dev.chronos.app.data.AuthStore
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** WS listener: state/patch/proposal/question/timer frames drive the UI cards. */
class WsClient(
    private val auth: AuthStore,
    private val http: OkHttpClient,
    val onFrame: (WsFrame) -> Unit,
    val onClosed: (needKeyRenew: Boolean) -> Unit = {},
) : WebSocketListener() {
    private var ws: WebSocket? = null

    fun connect() {
        val req = Request.Builder()
            .url(ApiRoutes.wsUrl(auth.serverUrl))
            .header(ApiRoutes.KEY_HEADER, auth.instanceKey)
            .build()
        ws = http.newWebSocket(req, this)
    }

    fun send(text: String) {
        ws?.send(text)
    }

    fun acceptRejectSkip(proposalId: String, verb: String) {
        val q = proposalId.replace("\\", "\\\\").replace("\"", "\\\"")
        send("{\"$verb\":\"$q\"}")
    }

    fun close() {
        ws?.close(1000, "bye")
        ws = null
    }

    override fun onMessage(webSocket: WebSocket, text: String) {
        try {
            val v = Json.parse(text)
            if (v is JVal.Obj) onFrame(WsFrame.parse(v))
        } catch (_: Exception) { }
    }

    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
        onClosed(false)
    }

    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
        // 4001 = key rotated via /api/keys/renew -> drop WS, user re-enters key.
        onClosed(response?.code == 4001)
    }
}
