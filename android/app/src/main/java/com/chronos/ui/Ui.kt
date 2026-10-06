package com.chronos.ui

import android.content.Context
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel

fun Context.toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

fun Fragment.main(): MainActivity = requireActivity() as MainActivity

fun col(ctx: Context, block: LinearLayout.() -> Unit): ScrollView {
    val sv = ScrollView(ctx)
    val ll = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(24, 24, 24, 24)
        block()
    }
    sv.addView(ll, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
    return sv
}

fun LinearLayout.title(text: String): TextView {
    val t = TextView(context).apply {
        this.text = text
        textSize = 20f
        setPadding(0, 16, 0, 8)
    }
    addView(t)
    return t
}

fun LinearLayout.row(vararg views: View) {
    val r = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
    views.forEach { r.addView(it) }
    addView(r)
}

fun LinearLayout.btn(text: String, onClick: () -> Unit): Button {
    val b = Button(context).apply { this.text = text; setOnClickListener { onClick() } }
    addView(b)
    return b
}

fun LinearLayout.edit(hint: String, initial: String = ""): EditText {
    val e = EditText(context).apply {
        this.hint = hint
        setText(initial)
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        )
    }
    addView(e)
    return e
}

fun LinearLayout.text(initial: String = ""): TextView {
    val t = TextView(context).apply { text = initial }
    addView(t)
    return t
}

fun LinearLayout.switchRow(label: String, initial: Boolean, onChange: (Boolean) -> Unit): Switch {
    val s = Switch(context).apply {
        text = label
        isChecked = initial
        setOnCheckedChangeListener { _, v -> onChange(v) }
    }
    addView(s)
    return s
}

/** Per-fragment coroutine scope, cancelled with the fragment. */
open class ScopedFragment : Fragment() {
    protected val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
