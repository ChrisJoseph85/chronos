package dev.chronos.app.ui

import android.content.Context
import android.media.MediaRecorder
import android.util.AttributeSet
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import dev.chronos.app.ChronosApp
import dev.chronos.app.net.Proposal
import dev.chronos.app.net.Question
import kotlinx.coroutines.launch
import java.io.File

/**
 * Global voice bar (every tab): Mic -> POST /api/voice -> transcript appended
 * to text box -> POST /api/say -> proposal diff card -> accept/reject/skip
 * over WS. Never silent-commits.
 */
class VoiceBarView @JvmOverloads constructor(
    ctx: Context, attrs: AttributeSet? = null,
) : LinearLayout(ctx, attrs) {
    var onPrefill: ((String) -> Unit)? = null
    private val app get() = context.applicationContext as ChronosApp

    private val input = EditText(ctx).apply { hint = "Say or type…"; layoutParams = LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f) }
    private val mic = Button(ctx).apply { text = "🎤" }
    private val send = Button(ctx).apply { text = "➤" }
    private val card = LinearLayout(ctx).apply {
        orientation = VERTICAL
        visibility = GONE
    }
    private var recorder: MediaRecorder? = null
    private var audioFile: File? = null
    private var pendingProposal: Proposal? = null
    var wsResolve: ((proposalId: String, verb: String) -> Unit)? = null

    init {
        orientation = VERTICAL
        val row = LinearLayout(ctx).apply { orientation = HORIZONTAL }
        row.addView(mic)
        row.addView(input)
        row.addView(send)
        addView(row)
        addView(card)
        mic.setOnClickListener { toggleMic() }
        send.setOnClickListener { say() }
    }

    fun prefill(text: String) {
        input.setText(text)
        onPrefill?.invoke(text)
    }

    private fun toggleMic() {
        if (recorder != null) {
            try {
                recorder?.stop()
                recorder?.release()
            } catch (_: Exception) { }
            recorder = null
            mic.text = "🎤"
            transcribe()
            return
        }
        try {
            val f = File(context.cacheDir, "voice_${System.currentTimeMillis()}.m4a")
            audioFile = f
            recorder = MediaRecorder().apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setOutputFile(f.absolutePath)
                prepare()
                start()
            }
            mic.text = "⏹"
        } catch (_: Exception) {
            recorder = null
            mic.text = "🎤"
        }
    }

    private fun transcribe() {
        val f = audioFile ?: return
        app.io.launch {
            try {
                val t = app.api.voice(f)
                post { input.setText(((if (input.text.isEmpty()) "" else input.text.toString() + " ") + t)) }
            } catch (_: Exception) { }
        }
    }

    private fun say() {
        val text = input.text.toString()
        if (text.isBlank() || !app.health.writesAllowed()) return
        app.io.launch {
            try {
                val r = app.api.say(text)
                val proposalId = r.strOrNull("proposal_id")
                val committed = r.bool("committed")
                if (!committed && proposalId != null) {
                    val p = Proposal(proposalId, r.str("message"))
                    post { showProposal(p) }
                }
            } catch (_: Exception) { }
        }
    }

    fun showProposal(p: Proposal) {
        pendingProposal = p
        renderCard(p.summary, isQuestion = false, id = p.id)
    }

    fun showQuestion(q: Question) {
        renderCard(q.text, isQuestion = true, id = q.id)
    }

    private fun renderCard(summary: String, isQuestion: Boolean, id: String) {
        card.removeAllViews()
        card.visibility = VISIBLE
        card.addView(TextView(context).apply { text = summary })
        val row = LinearLayout(context).apply { orientation = HORIZONTAL }
        val accept = Button(context).apply { text = "Accept" }
        val reject = Button(context).apply { text = "Reject" }
        val skip = Button(context).apply { text = "Skip" }
        accept.setOnClickListener { resolve(id, "accept"); card.visibility = GONE }
        reject.setOnClickListener { resolve(id, "reject"); card.visibility = GONE }
        skip.setOnClickListener { resolve(id, "skip"); card.visibility = GONE }
        row.addView(accept)
        if (!isQuestion) row.addView(reject)
        row.addView(skip)
        card.addView(row)
    }

    private fun resolve(id: String, verb: String) {
        val q = id.replace("\\", "\\\\").replace("\"", "\\\"")
        wsResolve?.invoke(q, verb)
        pendingProposal = null
    }
    private fun post(fn: () -> Unit) = (context as? android.app.Activity)?.runOnUiThread(fn) ?: fn()
}
