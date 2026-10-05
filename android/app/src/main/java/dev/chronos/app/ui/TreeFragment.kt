package dev.chronos.app.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment
import dev.chronos.app.ChronosApp
import dev.chronos.app.net.NodeInfo
import kotlinx.coroutines.launch

/**
 * Shared tree component for Tasks and Projects (different roots).
 * Project -> subproject -> task -> subtask; tags shown (never on projects).
 */
class TreeFragment : Fragment() {
    private val app get() = requireContext().applicationContext as ChronosApp
    private lateinit var list: LinearLayout

    companion object {
        const val ROOT_TASKS = "tasks"
        const val ROOT_PROJECTS = "projects"
        fun newInstance(root: String) = TreeFragment().apply {
            arguments = Bundle().apply { putString("root", root) }
        }
    }

    override fun onCreateView(inf: LayoutInflater, c: ViewGroup?, s: Bundle?): View {
        val root = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        list = LinearLayout(requireContext()).apply { orientation = LinearLayout.VERTICAL }
        root.addView(list)
        load()
        return root
    }

    private fun load() {
        app.io.launch {
            val nodes: List<NodeInfo> = try {
                app.api.getNodes()
            } catch (_: Exception) {
                emptyList()
            }
            val wantProject = (arguments?.getString("root") ?: ROOT_TASKS) == ROOT_PROJECTS
            val filtered = nodes.filter {
                if (wantProject) it.kind.contains("project", ignoreCase = true)
                else !it.kind.contains("project", ignoreCase = true)
            }
            activity?.runOnUiThread {
                list.removeAllViews()
                if (filtered.isEmpty()) list.addView(TextView(requireContext()).apply {
                    text = if (app.health.serverDown) "server is down" else "Nothing here"
                })
                renderLevel(filtered, null, 0)
            }
        }
    }

    private fun renderLevel(all: List<NodeInfo>, parent: Long?, depth: Int) {
        all.filter { it.parentId == parent }.forEach { n ->
            val tags = if (n.kind.contains("project", ignoreCase = true)) "" else n.tags.joinToString(" ") { "#$it" }
            list.addView(TextView(requireContext()).apply {
                text = "${"  ".repeat(depth)}• ${n.title} $tags"
                textSize = 16f
            })
            renderLevel(all, n.id, depth + 1)
        }
    }
}
