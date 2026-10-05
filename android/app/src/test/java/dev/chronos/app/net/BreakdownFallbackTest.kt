package dev.chronos.app.net

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class BreakdownFallbackTest {
    @Test fun missingEndpointShowsServerTooOld() = runTest {
        val repo = BreakdownRepository(api = object : BreakdownRepository.BreakdownApi {
            override suspend fun breakdown(nodeId: Long?, from: String, to: String) =
                BreakdownRepository.BreakdownResult.EndpointMissing
        })
        val s = repo.load(null, "2026-10-01", "2026-10-31")
        assertEquals(BreakdownRepository.UiState.Notice("server too old"), s)
    }

    @Test fun dataPassesThrough() = runTest {
        val kids = listOf(BreakdownChild(1, "A", "project", 1000L))
        val repo = BreakdownRepository(api = object : BreakdownRepository.BreakdownApi {
            override suspend fun breakdown(nodeId: Long?, from: String, to: String) =
                BreakdownRepository.BreakdownResult.Ok(kids)
        })
        val s = repo.load(null, "2026-10-01", "2026-10-31")
        assertEquals(BreakdownRepository.UiState.Data(kids), s)
    }
}
