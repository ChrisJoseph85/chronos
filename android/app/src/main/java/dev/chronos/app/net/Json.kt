package dev.chronos.app.net

/** Minimal JSON parser producing plain values. No Android deps: JVM unit-testable. */
sealed interface JVal {
    data class Obj(val map: Map<String, JVal>) : JVal {
        fun str(key: String): String = (map[key] as? Str)?.v ?: ""
        fun strOrNull(key: String): String? = (map[key] as? Str)?.v
        fun long(key: String, def: Long = 0L): Long = when (val x = map[key]) {
            is Num -> x.v.toLong()
            is Str -> x.v.toLongOrNull() ?: def
            else -> def
        }
        fun bool(key: String, def: Boolean = false): Boolean = (map[key] as? Bool)?.v ?: def
        fun obj(key: String): Obj? = map[key] as? Obj
        fun arr(key: String): List<JVal> = (map[key] as? Arr)?.items ?: emptyList()
        fun has(key: String): Boolean = map.containsKey(key) && map[key] !is Null
    }
    data class Arr(val items: List<JVal>) : JVal
    data class Str(val v: String) : JVal
    data class Num(val v: Double) : JVal
    data class Bool(val v: Boolean) : JVal
    data object Null : JVal
}

object Json {
    fun parse(s: String): JVal {
        val p = Parser(s)
        p.ws()
        val v = p.value()
        p.ws()
        return v
    }

    private class Parser(val s: String) {
        var i = 0
        fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
        fun value(): JVal {
            if (i >= s.length) throw IllegalArgumentException("unexpected end of JSON")
            return when (s[i]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> JVal.Str(str())
                't' -> run { expect("true"); JVal.Bool(true) }
                'f' -> run { expect("false"); JVal.Bool(false) }
                'n' -> run { expect("null"); JVal.Null }
                else -> num()
            }
        }
        fun obj(): JVal.Obj {
            i++ // {
            val m = LinkedHashMap<String, JVal>()
            ws()
            if (i < s.length && s[i] == '}') { i++; return JVal.Obj(m) }
            while (true) {
                ws()
                val k = str()
                ws()
                if (i >= s.length || s[i] != ':') throw IllegalArgumentException("expected ':' in object")
                i++
                ws()
                m[k] = value()
                ws()
                if (i >= s.length) throw IllegalArgumentException("unterminated object")
                if (s[i] == '}') { i++; return JVal.Obj(m) }
                if (s[i] != ',') throw IllegalArgumentException("expected ',' in object")
                i++
            }
        }
        fun arr(): JVal.Arr {
            i++ // [
            val l = ArrayList<JVal>()
            ws()
            if (i < s.length && s[i] == ']') { i++; return JVal.Arr(l) }
            while (true) {
                ws()
                l.add(value())
                ws()
                if (i >= s.length) throw IllegalArgumentException("unterminated array")
                if (s[i] == ']') { i++; return JVal.Arr(l) }
                if (s[i] != ',') throw IllegalArgumentException("expected ',' in array")
                i++
            }
        }
        fun str(): String {
            val sb = StringBuilder()
            i++ // opening quote
            while (i < s.length) {
                val c = s[i++]
                if (c == '"') return sb.toString()
                if (c == '\\') {
                    if (i >= s.length) break
                    when (val e = s[i++]) {
                        '"', '\\', '/' -> sb.append(e)
                        'n' -> sb.append('\n')
                        't' -> sb.append('\t')
                        'r' -> sb.append('\r')
                        'b' -> sb.append('\b')
                        'u' -> {
                            sb.append(s.substring(i, i + 4).toInt(16).toChar())
                            i += 4
                        }
                        else -> sb.append(e)
                    }
                } else sb.append(c)
            }
            throw IllegalArgumentException("unterminated string")
        }
        fun num(): JVal.Num {
            val start = i
            while (i < s.length && (s[i].isDigit() || s[i] in "+-eE.")) i++
            return JVal.Num(s.substring(start, i).toDouble())
        }
        fun expect(w: String) {
            if (!s.startsWith(w, i)) throw IllegalArgumentException("expected $w")
            i += w.length
        }
    }
}
