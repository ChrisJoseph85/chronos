package com.chronos.api

import kotlinx.serialization.Serializable

@Serializable
data class Health(
    val status: String = "",
    val version: String = "",
    val db_path: String = "",
    val uptime_seconds: Long = 0,
)

@Serializable
data class TimerSession(
    val id: String = "",
    val node_id: String? = null,
    val label: String = "",
    val mode: String = "stopwatch",
    val target_ms: Long? = null,
    val start_ms: Long = 0,
    val end_ms: Long? = null,
    val voided: Boolean = false,
    val source: String = "",
)

@Serializable
data class TimerStart(
    val label: String,
    val mode: String,
    val node_id: String? = null,
    val target_ms: Long? = null,
    val source: String = "android",
)

@Serializable
data class TimerStop(val source: String = "android", val void: Boolean = false)

@Serializable
data class TimerPreset(
    val name: String = "",
    val focus_minutes: Int = 25,
    val break_minutes: Int = 5,
    val cycles: Int = 4,
)

@Serializable
data class TimerSummary(
    val node_total_ms: Long = 0,
    val descendant_total_ms: Long = 0,
    val project_total_ms: Long = 0,
)

@Serializable
data class BreakdownItem(
    val node_id: String = "",
    val title: String = "",
    val kind: String = "",
    val total_ms: Long = 0,
)

@Serializable
data class Node(
    val id: String = "",
    val title: String = "",
    val kind: String = "task",
    val parent_id: String? = null,
    val tags: List<String> = emptyList(),
)

@Serializable
data class CalEvent(
    val id: String = "",
    val title: String = "",
    val from_ms: Long = 0,
    val to_ms: Long = 0,
)

@Serializable
data class Question(val id: String = "", val text: String = "")

@Serializable
data class Proposal(
    val proposal_id: String = "",
    val summary: String = "",
    val diff: String = "",
)

@Serializable
data class SayResult(
    val intent: String = "",
    val message: String = "",
    val proposal_id: String? = null,
    val proposal: Proposal? = null,
    val question: Question? = null,
    val committed: Boolean = false,
)

@Serializable
data class Briefing(
    val date: String = "",
    val unallocated_tasks: List<Node> = emptyList(),
    val rollover: List<Node> = emptyList(),
    val due_reviews: List<Node> = emptyList(),
    val question: Question? = null,
)

@Serializable
data class ProviderEntry(
    val id: String = "",
    val name: String = "",
    val base_url: String = "",
    val model: String? = null,
    val position: Int = 0,
    val key_count: Int = 0,
    val key_ids: List<String> = emptyList(),
)

@Serializable
data class Providers(
    val stt: List<ProviderEntry> = emptyList(),
    val text: List<ProviderEntry> = emptyList(),
    val embeddings: List<ProviderEntry> = emptyList(),
)
