package com.chronos.api

import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * WS /ws client. Auth on upgrade via X-Chronos-Key header, then a hello frame.
 * `timer` frames drive the home card; `proposal`/`question` drive cards.
 * Every mutation broadcasts to all clients, so remote stop/void reflects here.
 */
class WsClient(
    private val baseUrl: String,
    private val key: () -> String,
    private val http: OkHttpClient = OkHttpClient(),
    private val json: Json = Json { ignoreUnknownKeys = true },
) {
    interface Listener {
        fun onTimer(session: TimerSession?)
        fun onProposal(proposal: Proposal)
        fun onQuestion(question: Question)
        fun onOpen()
        fun onClosed()
    }

    private var ws: WebSocket? = null
    var listener: Listener? = null

    fun connect() {
        val b = baseUrl.trim().trimEnd('/')
        if (b.isEmpty()) return // unconfigured: health gate shows Settings first
        val url = (if (b.startsWith("http")) b.replaceFirst("http", "ws") else "ws://$b") + "/ws"
        SafeLog.d("ws", "connect $url", key())
        val req = Request.Builder().url(url).header("X-Chronos-Key", key()).build()
        ws = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send("""{"hello":{"key":"***","device":"android"}}""")
                listener?.onOpen()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val el = json.parseToJsonElement(text)
                    val obj = el as? kotlinx.serialization.json.JsonObject ?: return
                    when {
                        obj.containsKey("timer") -> {
                            val t = obj["timer"].toString()
                            listener?.onTimer(
                                if (t == "null") null
                                else json.decodeFromJsonElement(TimerSession.serializer(), obj["timer"]!!),
                            )
                        }
                        obj.containsKey("proposal") ->
                            listener?.onProposal(json.decodeFromJsonElement(Proposal.serializer(), obj["proposal"]!!))
                        obj.containsKey("question") ->
                            listener?.onQuestion(json.decodeFromJsonElement(Question.serializer(), obj["question"]!!))
                    }
                } catch (e: Exception) {
                    SafeLog.d("ws", "bad frame: ${e.message}")
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                listener?.onClosed()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                SafeLog.d("ws", "failure, will reconnect on next resume")
                listener?.onClosed()
            }
        })
    }

    fun send(text: String) {
        ws?.send(text)
    }

    fun accept(proposalId: String) = send("""{"accept":"$proposalId"}""")
    fun reject(proposalId: String) = send("""{"reject":"$proposalId"}""")
    fun skip(proposalId: String) = send("""{"skip":"$proposalId"}""")

    fun close() {
        ws?.close(1000, "pause")
        ws = null
    }
}
