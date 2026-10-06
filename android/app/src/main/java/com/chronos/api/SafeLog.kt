package com.chronos.api

import android.util.Log

/**
 * All logging goes through here so the instance key can NEVER leak.
 * Every call site passes secrets explicitly; tests enforce redaction.
 */
object SafeLog {
    /** Swappable in unit tests (android.util.Log stubs throw on JVM). */
    var sink: (tag: String, msg: String) -> Unit = { tag, msg -> Log.d(tag, msg) }

    fun d(tag: String, msg: String, vararg secrets: String) {
        sink(tag, redact(msg, secrets.toList()))
    }

    fun redact(msg: String, secrets: List<String>): String {
        var out = msg
        for (s in secrets) {
            if (s.isNotEmpty()) out = out.replace(s, "***")
        }
        return out
    }
}
