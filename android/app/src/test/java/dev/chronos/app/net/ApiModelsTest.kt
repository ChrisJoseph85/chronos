package dev.chronos.app.net

import org.junit.Assert.*
import org.junit.Test

class ApiModelsTest {
    @Test fun timerSessionParsesVoidFlag() {
        val o = Json.parse(
            """{"id":7,"mode":"pomodoro","label":"deep work","node_id":3,"started_ms":1728000000000,"target_ms":1500000,"voided":true}"""
        ) as JVal.Obj
        val s = TimerSession.parse(o)
        assertEquals(7L, s.id)
        assertEquals("pomodoro", s.mode)
        assertEquals(3L, s.nodeId)
        assertTrue(s.voided)
    }

    @Test fun proposalParses() {
        val o = Json.parse("""{"proposal_id":"p1","summary":"Create task X"}""") as JVal.Obj
        assertEquals("p1", Proposal.parse(o).id)
    }

    @Test fun breakdownChildParses() {
        val o = Json.parse("""{"node_id":9,"title":"Proj","kind":"project","total_ms":2400000}""") as JVal.Obj
        val c = BreakdownChild.parse(o)
        assertEquals(2400000L, c.totalMs)
    }

    @Test fun wsTimerFrameParsesNullSession() {
        val o = Json.parse("""{"type":"timer"}""") as JVal.Obj
        val f = WsFrame.parse(o)
        assertTrue(f is WsFrame.Timer && f.session == null)
    }

    @Test fun wsTimerFrameParsesLiveSession() {
        val o = Json.parse("""{"type":"timer","session":{"id":1,"mode":"stopwatch","label":"t","started_ms":5,"voided":false}}""") as JVal.Obj
        val f = WsFrame.parse(o) as WsFrame.Timer
        assertEquals(1L, f.session!!.id)
    }

    @Test fun wsProposalAndQuestionParse() {
        val p = WsFrame.parse(Json.parse("""{"type":"proposal","proposal":{"proposal_id":"p9","summary":"s"}}""") as JVal.Obj)
        assertTrue(p is WsFrame.ProposalF)
        val q = WsFrame.parse(Json.parse("""{"type":"question","question":{"id":"q1","text":"Which?"}}""") as JVal.Obj)
        assertTrue(q is WsFrame.QuestionF)
    }

    @Test fun providerEntryNeverCarriesKeyValue() {
        val o = Json.parse("""{"id":"a","group":"text","name":"n","key_ids":["k1"],"key_count":2}""") as JVal.Obj
        val e = ProviderEntry.parse(o)
        assertEquals(2, e.keyCount)
        assertFalse(o.has("key"))
    }
}
