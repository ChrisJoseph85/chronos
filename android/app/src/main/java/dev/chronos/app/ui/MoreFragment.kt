package dev.chronos.app.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import androidx.fragment.app.Fragment
import dev.chronos.app.R

/**
 * Overflow screen: BottomNavigationView supports max 5 items, so Projects,
 * Stats and Settings live here (7 destinations total). Buttons route through
 * MainActivity.open() so behavior matches the bottom tabs.
 */
class MoreFragment : Fragment() {
    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?,
    ): View {
        val ctx = requireContext()
        return LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            val open = activity as? MainActivity
            addView(Button(ctx).apply {
                text = "Projects"
                setOnClickListener { open?.open(MainActivity.DEST_PROJECTS) }
            })
            addView(Button(ctx).apply {
                text = "Stats"
                setOnClickListener { open?.open(MainActivity.DEST_STATS) }
            })
            addView(Button(ctx).apply {
                text = "Settings"
                setOnClickListener { open?.open(MainActivity.DEST_SETTINGS) }
            })
        }
    }
}
