package dev.chronos.app.net

/** Breakdown drilldown with graceful fallback when the v1.2 endpoint is absent. */
class BreakdownRepository(private val api: BreakdownApi) {

    interface BreakdownApi {
        suspend fun breakdown(nodeId: Long?, from: String, to: String): BreakdownResult
    }

    sealed interface BreakdownResult {
        data class Ok(val children: List<BreakdownChild>) : BreakdownResult
        data object EndpointMissing : BreakdownResult
        data class Error(val message: String) : BreakdownResult
    }

    sealed interface UiState {
        data class Data(val children: List<BreakdownChild>) : UiState
        data class Notice(val text: String) : UiState
    }

    suspend fun load(nodeId: Long?, from: String, to: String): UiState =
        when (val r = api.breakdown(nodeId, from, to)) {
            is BreakdownResult.Ok -> UiState.Data(r.children)
            is BreakdownResult.EndpointMissing -> UiState.Notice("server too old")
            is BreakdownResult.Error -> UiState.Notice(r.message)
        }
}
