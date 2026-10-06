package com.chronos.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import com.chronos.ChronosApp
import com.chronos.api.Briefing
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate

/** Briefing: GET /api/briefing?date + rollover/due-reviews + ≤1 question card. */
class BriefingFragment : ScopedFragment() {
    private lateinit var body: android.widget.LinearLayout
    private lateinit var dateInput: EditText

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        return col(requireContext()) {
            title("Briefing")
            dateInput = edit("date YYYY-MM-DD", LocalDate.now().toString())
            btn("Load") { load() }
            body = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.VERTICAL
            }
            addView(body)
        }
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    private fun load() {
        val act = activity as? MainActivity ?: return
        val date = dateInput.text.toString().ifBlank { LocalDate.now().toString() }
        scope.launch {
            val app = act.application as ChronosApp
            val b: Briefing? = try {
                withContext(Dispatchers.IO) { app.api().briefing(date) }
            } catch (_: Exception) {
                null
            }
            if (!isAdded) return@launch
            body.removeAllViews()
            if (b == null) {
                body.addView(TextView(context).apply { text = "(unavailable offline)" })
                return@launch
            }
            body.addView(TextView(context).apply { text = "Rollover:"; textSize = 16f })
            b.rollover.forEach { body.addView(TextView(context).apply { text = "• ${it.title}" }) }
            body.addView(TextView(context).apply { text = "Due reviews:"; textSize = 16f })
            b.due_reviews.forEach { body.addView(TextView(context).apply { text = "• ${it.title}" }) }
            body.addView(TextView(context).apply { text = "Unallocated:"; textSize = 16f })
            b.unallocated_tasks.forEach { body.addView(TextView(context).apply { text = "• ${it.title}" }) }
            // ≤1 question card (accept/skip = clarification budget).
            val q = b.question
            if (q != null) {
                body.addView(TextView(context).apply { text = "Q: ${q.text}"; textSize = 16f })
                val r = android.widget.LinearLayout(context).apply { orientation = android.widget.LinearLayout.HORIZONTAL }
                r.addView(
                    android.widget.Button(context).apply {
                        text = "accept"
                        setOnClickListener {
                            if (!act.blockedWrite()) app.ws.accept(q.id)
                        }
                    },
                )
                r.addView(
                    android.widget.Button(context).apply {
                        text = "skip"
                        setOnClickListener { app.ws.skip(q.id) }
                    },
                )
                body.addView(r)
            }
        }
    }
}
