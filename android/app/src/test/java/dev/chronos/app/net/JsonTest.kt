package dev.chronos.app.net

import org.junit.Assert.*
import org.junit.Test

class JsonTest {
    @Test fun parsesNestedObject() {
        val v = Json.parse("""{"a":1,"b":"x","c":true,"d":null,"e":{"f":[1,2]}}""") as JVal.Obj
        assertEquals(1L, v.long("a"))
        assertEquals("x", v.str("b"))
        assertTrue(v.bool("c"))
        assertEquals(2, v.obj("e")!!.arr("f").size)
    }

    @Test fun parsesEscapes() {
        val v = Json.parse("""{"t":"a\"b\nc"}""") as JVal.Obj
        assertEquals("a\"b\nc", v.str("t"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsTruncated() {
        Json.parse("""{"a":""")
    }
}
