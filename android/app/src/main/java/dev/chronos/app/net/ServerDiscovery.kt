package dev.chronos.app.net

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ensureActive
import okhttp3.OkHttpClient
import java.net.NetworkInterface
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

/**
 * Server auto-discovery (§9): 127.0.0.1 first, then device LAN /24 hosts,
 * same port throughout (editable, default 693). Per host: GET /api/health,
 * then ONE authenticated probe with the SAVED instance key. First
 * healthy+authorized host wins. Unreachable hosts are skipped, not failures.
 * Sweep is a suspend function: cancel the coroutine to stop it.
 */
class ServerDiscovery(
    private val healthCheck: suspend (baseUrl: String) -> Boolean,
    private val authCheck: suspend (baseUrl: String, key: String) -> Boolean,
) {
    companion object {
        const val DEFAULT_PORT = 693

        fun baseUrl(host: String, port: Int): String = "http://$host:$port"

        /** 127.0.0.1 first, then /24 hosts derived from the device LAN IP. */
        fun candidates(port: Int, localIp: String?): List<String> {
            val out = mutableListOf(baseUrl("127.0.0.1", port))
            for (h in subnet24Hosts(localIp)) {
                val u = baseUrl(h, port)
                if (u !in out) out.add(u)
            }
            return out
        }

        /** All .1..254 of the local /24, excluding network/broadcast-self noise. */
        fun subnet24Hosts(localIp: String?): List<String> {
            val ip = localIp?.trim().orEmpty()
            val parts = ip.split(".")
            if (parts.size != 4) return emptyList()
            val oct = parts.map { it.toIntOrNull() }
            if (oct.any { it == null || it !in 0..255 }) return emptyList()
            val prefix = "${oct[0]}.${oct[1]}.${oct[2]}"
            if (prefix == "127.0.0") return emptyList()
            return (1..254).map { "$prefix.$it" }
        }

        /** Device LAN IPv4 (site-local, non-loopback), null if none. */
        fun deviceLanIp(): String? = try {
            NetworkInterface.getNetworkInterfaces()?.toList()?.flatMap { nic ->
                nic.inetAddresses?.toList().orEmpty()
            }?.firstOrNull { a ->
                !a.isLoopbackAddress && a.hostAddress?.contains('.') == true &&
                    a.isSiteLocalAddress
            }?.hostAddress
        } catch (_: Exception) {
            null
        }

        /** Real network probes: health = GET /api/health 200; auth = one GET with saved key. */
        fun realProbes(): ServerDiscovery {
            val http = OkHttpClient.Builder()
                .connectTimeout(1, TimeUnit.SECONDS)
                .readTimeout(1, TimeUnit.SECONDS)
                .callTimeout(1, TimeUnit.SECONDS)
                .build()
            val api = RealProbeHttp(http)
            return ServerDiscovery(api::healthOk, api::authOk)
        }
    }

    /**
     * Sweep [hosts] in order. Returns winning base URL or null.
     * Throws CancellationException when cancelled; unreachable hosts are skipped.
     */
    suspend fun findFirst(
        hosts: List<String>,
        savedKey: String,
        onProgress: (checked: Int, total: Int, host: String) -> Unit = { _, _, _ -> },
    ): String? {
        hosts.forEachIndexed { i, base ->
            coroutineContext.ensureActive()
            val healthy = try {
                healthCheck(base)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                false // unreachable -> skip, not fail
            }
            if (healthy) {
                val authorized = try {
                    authCheck(base, savedKey)
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    false
                }
                onProgress(i + 1, hosts.size, base)
                if (authorized) return base
            } else {
                onProgress(i + 1, hosts.size, base)
            }
        }
        return null
    }
}
