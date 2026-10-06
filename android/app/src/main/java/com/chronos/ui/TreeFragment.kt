package com.chronos.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import com.chronos.ChronosApp
import com.chronos.api.Node
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * One shared tree component, different roots.
 * Project -> subproject -> task -> subtask. Tags shown on tasks, never on projects.
 */
open class TreeFragment : ScopedFragment() {
    var root: String? = null
    var screenTitle: String = "Tree"
    private lateinit var list: android.widget.LinearLayout

    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        return col(requireContext()) {
            title(screenTitle)
            list = android.widget.LinearLayout(context).apply {
                orientation = android.widget.LinearLayout.VERTICAL
            }
            addView(list)
        }
    }

    override fun onResume() {
        super.onResume()
        load(null, 0)
    }

    private fun load(parent: String?, depth: Int) {
        val act = activity as? MainActivity ?: return
        scope.launch {
            val app = act.application as ChronosApp
            val nodes: List<Node> = try {
                withContext(Dispatchers.IO) { app.api().nodes(parent ?: root) }
            } catch (_: Exception) {
                emptyList()
            }
            if (!isAdded) return@launch
            if (depth == 0) list.removeAllViews()
            if (nodes.isEmpty() && depth == 0) {
                list.addView(TextView(context).apply { text = "(empty)" })
            }
            for (n in nodes) {
                val indent = "  ".repeat(depth)
                // Tags shown on tasks, never on projects (server rule mirrored).
                val tags = if (n.kind == "project") "" else n.tags.joinToString(" ").let { if (it.isEmpty()) "" else " $it" }
                list.addView(
                    TextView(context).apply {
                        text = "$indent• ${n.title} [${n.kind}]$tags"
                        setPadding(0, 8, 0, 8)
                    },
                )
                loadChildren(n, depth + 1)
            }
        }
    }

    private fun loadChildren(n: Node, depth: Int) {
        val act = activity as? MainActivity ?: return
        scope.launch {
            val app = act.application as ChronosApp
            val kids: List<Node> = try {
                withContext(Dispatchers.IO) { app.api().nodes(n.id) }
            } catch (_: Exception) {
                emptyList()
            }
            if (!isAdded) return@launch
            for (k in kids) {
                val indent = "  ".repeat(depth)
                val tags = if (k.kind == "project") "" else k.tags.joinToString(" ").let { if (it.isEmpty()) "" else " $it" }
                list.addView(
                    TextView(context).apply {
                        text = "$indent• ${k.title} [${k.kind}]$tags"
                        setOnClickListener { act.voicePrefill("log time on ${k.title} ") }
                    },
                )
            }
        }
    }
}

class TasksFragment : TreeFragment() {
    override fun onCreate(s: Bundle?) {
        super.onCreate(s)
        screenTitle = "Tasks"
    }
}

class ProjectsFragment : TreeFragment() {
    override fun onCreate(s: Bundle?) {
        super.onCreate(s)
        screenTitle = "Projects"
    }
}
