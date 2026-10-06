package com.chronos.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.util.AttributeSet
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.chronos.ChronosApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Global voice bar (present on every tab).
 * Mic -> POST /api/voice -> transcript appended -> POST /api/say ->
 * proposal diff card -> accept/reject/skip over WS. Never silent-commits:
 * ambiguous input always lands on the proposal card first.
 */
class VoiceBar @JvmOverloads constructor(
    ctx: Context,
    attrs: AttributeSet? = null,
) : LinearLayout(ctx, attrs) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val input: EditText
    private val card: LinearLayout
    private val cardText: TextView
    private var proposalId: String? = null
    private var recorder: MediaRecorder? = null
    private var audioFile: File? = null
    private var recording = false

    var onVoiceError: (String) -> Unit = {}

    init {
        orientation = VERTICAL
        val row = LinearLayout(ctx).apply { orientation = HORIZONTAL }
        input = EditText(ctx).apply {
            hint = "say something…"
            layoutParams = LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f)
        }
        val mic = Button(ctx).apply {
            text = "mic"
            setOnClickListener { toggleMic() }
        }
        val send = Button(ctx).apply {
            text = "send"
            setOnClickListener { say() }
        }
        row.addView(input)
        row.addView(mic)
        row.addView(send)
        addView(row)
        card = LinearLayout(ctx).apply {
            orientation = VERTICAL
            visibility = GONE
        }
        cardText = TextView(ctx)
        val btnRow = LinearLayout(ctx).apply { orientation = HORIZONTAL }
        val accept = Button(ctx).apply { text = "accept"; setOnClickListener { verdict("accept") } }
        val reject = Button(ctx).apply { text = "reject"; setOnClickListener { verdict("reject") } }
        val skip = Button(ctx).apply { text = "skip"; setOnClickListener { verdict("skip") } }
        btnRow.addView(accept)
        btnRow.addView(reject)
        btnRow.addView(skip)
        card.addView(cardText)
        card.addView(btnRow)
        addView(card)
    }

    fun prefill(text: String) {
        input.setText(text)
    }

    private fun app(): ChronosApp = context.applicationContext as ChronosApp

    private fun toggleMic() {
        if (recording) {
            stopRecording(upload = true)
        } else {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                onVoiceError("mic permission needed")
                return
            }
            startRecording()
        }
        recording = !recording
    }

    private fun startRecording() {
        try {
            audioFile = File.createTempFile("voice", ".m4a", context.cacheDir)
            recorder = MediaRecorder().apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setOutputFile(audioFile!!.absolutePath)
                prepare()
                start()
            }
        } catch (e: Exception) {
            onVoiceError("mic failed: ${e.message}")
            recording = true // so toggle flips back
        }
    }

    private fun stopRecording(upload: Boolean) {
        try {
            recorder?.stop()
            recorder?.release()
        } catch (_: Exception) {
        }
        recorder = null
        if (upload) {
            val f = audioFile ?: return
            scope.launch {
                try {
                    val t = withContext(Dispatchers.IO) { app().api().voice(f.readBytes()) }
                    input.setText((input.text.toString() + " " + t).trim())
                } catch (e: Exception) {
                    onVoiceError("voice upload failed")
                } finally {
                    f.delete()
                }
            }
        }
    }

    fun say() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        scope.launch {
            try {
                val r = withContext(Dispatchers.IO) { app().api().say(text) }
                if (r.committed) {
                    input.setText("")
                    onVoiceError(r.message.ifEmpty { "done" })
                } else {
                    val p = r.proposal
                    proposalId = r.proposal_id ?: p?.proposal_id
                    val id = proposalId
                    if (r.question != null) {
                        showCard("Q: ${r.question.text}")
                        proposalId = null
                    } else if (id != null) {
                        showCard(p?.summary ?: r.message.ifEmpty { "proposal $id" })
                    } else {
                        onVoiceError(r.message.ifEmpty { "no proposal" })
                    }
                }
            } catch (e: Exception) {
                onVoiceError("say failed")
            }
        }
    }

    fun showCard(summary: String) {
        cardText.text = summary
        card.visibility = VISIBLE
    }

    private fun verdict(kind: String) {
        val id = proposalId ?: run {
            card.visibility = GONE
            return
        }
        when (kind) {
            "accept" -> app().ws.accept(id)
            "reject" -> app().ws.reject(id)
            else -> app().ws.skip(id)
        }
        proposalId = null
        card.visibility = GONE
        input.setText("")
    }

    fun onDetach() = scope.cancel()
}
