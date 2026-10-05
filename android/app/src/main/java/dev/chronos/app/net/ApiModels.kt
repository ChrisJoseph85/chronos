package dev.chronos.app.net

/** Spec shapes for REST + WS frames. All parsing from JVal: JVM unit-testable. */
data class TimerSession(
    val id: Long,
    val mode: String,
    val label: String,
    val nodeId: Long?,
    val startedMs: Long,
    val targetMs: Long?,
    val voided: Boolean,
) {
    companion object {
        fun parse(o: JVal.Obj) = TimerSession(
            id = o.long("id"),
            mode = o.str("mode").ifEmpty { "stopwatch" },
            label = o.str("label"),
            nodeId = o.map["node_id"]?.let { (it as? JVal.Num)?.v?.toLong() },
            startedMs = o.long("started_ms").let { if (it == 0L) o.long("started_at_ms") else it },
            targetMs = o.map["target_ms"]?.let { (it as? JVal.Num)?.v?.toLong() },
            voided = o.bool("voided"),
        )
    }
}

data class NodeInfo(
    val id: Long,
    val title: String,
    val kind: String,
    val parentId: Long?,
    val tags: List<String>,
) {
    companion object {
        fun parse(o: JVal.Obj) = NodeInfo(
            id = o.long("id"),
            title = o.str("title"),
            kind = o.str("kind"),
            parentId = (o.map["parent_id"] as? JVal.Num)?.v?.toLong(),
            tags = o.arr("tags").mapNotNull { (it as? JVal.Str)?.v },
        )
    }
}

data class EventItem(
    val id: Long,
    val title: String,
    val fromMs: Long,
    val toMs: Long,
) {
    companion object {
        fun parse(o: JVal.Obj) = EventItem(
            id = o.long("id"),
            title = o.str("title"),
            fromMs = o.long("from_ms"),
            toMs = o.long("to_ms"),
        )
    }
}

data class Proposal(val id: String, val summary: String) {
    companion object {
        fun parse(o: JVal.Obj) = Proposal(
            id = o.str("proposal_id").ifEmpty { o.str("id") },
            summary = o.str("summary").ifEmpty { o.str("message") },
        )
    }
}

data class Question(val id: String, val text: String) {
    companion object {
        fun parse(o: JVal.Obj) = Question(
            id = o.str("id"),
            text = o.str("text"),
        )
    }
}

data class BreakdownChild(
    val nodeId: Long,
    val title: String,
    val kind: String,
    val totalMs: Long,
) {
    companion object {
        fun parse(o: JVal.Obj) = BreakdownChild(
            nodeId = o.long("node_id"),
            title = o.str("title"),
            kind = o.str("kind"),
            totalMs = o.long("total_ms"),
        )
    }
}

data class Summary(
    val nodeTotalMs: Long,
    val descendantTotalMs: Long,
    val projectTotalMs: Long,
) {
    companion object {
        fun parse(o: JVal.Obj) = Summary(
            nodeTotalMs = o.long("node_total_ms"),
            descendantTotalMs = o.long("descendant_total_ms"),
            projectTotalMs = o.long("project_total_ms"),
        )
    }
}

data class ProviderEntry(
    val id: String,
    val group: String,
    val name: String,
    val keyCount: Int,
) {
    companion object {
        fun parse(o: JVal.Obj) = ProviderEntry(
            id = o.str("id"),
            group = o.str("group"),
            name = o.str("name"),
            // Keys are never displayed: only counts/ids ever parsed.
            keyCount = o.long("key_count").toInt(),
        )
    }
}

/** WS server frames per API.md: state | patch | proposal | question | timer. */
sealed interface WsFrame {
    data class State(val raw: JVal.Obj) : WsFrame
    data class Patch(val ops: List<JVal>) : WsFrame
    data class ProposalF(val proposal: Proposal) : WsFrame
    data class QuestionF(val question: Question) : WsFrame
    data class Timer(val session: TimerSession?) : WsFrame
    data class Other(val type: String) : WsFrame

    companion object {
        fun parse(o: JVal.Obj): WsFrame {
            val t = o.str("type")
            return when (t) {
                "state" -> State(o)
                "patch" -> Patch(o.arr("ops"))
                "proposal" -> ProposalF(Proposal.parse(o.obj("proposal") ?: o))
                "question" -> QuestionF(Question.parse(o.obj("question") ?: o))
                "timer" -> {
                    val s = o.obj("session")
                    Timer(if (s == null || s.map.isEmpty()) null else TimerSession.parse(s))
                }
                else -> Other(t.ifEmpty { "unknown" })
            }
        }
    }
}

fun parseTimerOrNull(body: String): TimerSession? {
    val v = Json.parse(body)
    if (v is JVal.Null) return null
    return TimerSession.parse(v as JVal.Obj)
}
