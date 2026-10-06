package com.chronos.api

/** Thrown for HTTP error responses. [body] is truncated and NEVER contains the key. */
class ApiException(val code: Int, message: String, val body: String = "") : Exception(message)

/** A v1.2 route is missing: the server is too old. Callers degrade gracefully. */
class ServerTooOld(route: String) : Exception("server too old for $route")

/** Narrow timer surface: everything TimerEngine needs (fakes stay small). */
interface TimerApi {
    suspend fun timerGet(): TimerSession?
    suspend fun timerStart(body: TimerStart): TimerSession
    suspend fun timerStop(source: String, void: Boolean): TimerSession
    suspend fun timerPresets(): List<TimerPreset>
}

interface ChronosApi : TimerApi {
    suspend fun health(): Health
    suspend fun timerSummary(nodeId: String? = null): TimerSummary
    suspend fun breakdown(nodeId: String?, from: String, to: String): List<BreakdownItem>
    suspend fun events(from: String, to: String): List<CalEvent>
    suspend fun nodes(parent: String? = null): List<Node>
    suspend fun briefing(date: String): Briefing
    suspend fun say(text: String): SayResult
    suspend fun voice(audio: ByteArray, fileName: String = "mic.m4a"): String
    suspend fun providers(): Providers
    suspend fun addProvider(group: String, name: String, baseUrl: String): ProviderEntry
    suspend fun moveProvider(id: String, position: Int): ProviderEntry
    suspend fun addProviderKey(id: String, key: String): String
    suspend fun settings(): Map<String, String>
}
