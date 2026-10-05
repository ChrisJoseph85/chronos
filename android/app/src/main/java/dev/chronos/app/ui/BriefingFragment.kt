package dev.chronos.app.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment
import dev.chronos.app.ChronosApp
import dev.chronos.app.net.JVal
import dev.chronos.app.net.Question
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * Briefing: GET /api/briefing?date, rollover/due-reviews, <=1 question card
 * (accept/skip = clarification budget).
 */
class BriefingFragment : Fragment() {
    private val app get() = requireContext().applicationContext as ChronosApp
    private lateinit var body: LinearLayout

    override fun onCreateView(inf: LayoutInflater, c: ViewGroup?, s: Bundle?): View {
        body = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        load()
        return body
    }

    private fun load() {
        val date = LocalDate.now().toString()
        app.io.launch {
            val b: JVal.Obj? = try {
                val (obj, raw) = app.api.getBriefing(date)
                app.cache.put("briefing", raw)
                obj
            } catch (_: Exception) {
                app.cache.get("briefing")?.let {
                    try { dev.chronos.app.net.Json.parse(it) as? JVal.Obj } catch (_: Exception) { null }
                }
            }
            activity?.runOnUiThread {
                body.removeAllViews()
                if (b == null) {
                    body.addView(TextView(requireContext()).apply { text = "server is down" })
                    return@runOnUiThread
                }
                body.addView(TextView(requireContext()).apply {
                    text = "Briefing $date"
                    textSize = 20f
                })
                body.addView(TextView(requireContext()).apply {
                    text = "Rollover: ${b.arr("rollover").size}  Due reviews: ${b.arr("due_reviews").size}"
                })
                b.obj("question")?.let { q ->
                    val question = Question.parse(q)
                    body.addView(TextView(requireContext()).apply { text = question.text })
                    val row = LinearLayout(requireContext()).apply { orientation = LinearLayout.HORIZONTAL }
                    val accept = Button(requireContext()).apply { text = "Accept" }
                    accept.setOnClickListener { }
                    val skip = Button(requireContext()).apply { text = "Skip" }
                    skip.setOnClickListener { }
                    row.addView(accept)
                    row.addView(skip)
                    body.addView(row)
                }
            }
        }
    }
}
