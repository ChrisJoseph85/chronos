package com.chronos.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup

/** More screen: holds Projects, Stats, Settings (same fragments, 5-tab limit). */
class MoreFragment : ScopedFragment() {
    override fun onCreateView(inf: LayoutInflater, ctn: ViewGroup?, st: Bundle?): View {
        val act = activity as MainActivity
        return col(requireContext()) {
            title("More")
            btn("Projects") { act.open(ProjectsFragment()) }
            btn("Stats") { act.open(StatsFragment()) }
            btn("Settings") { act.open(SettingsFragment()) }
        }
    }
}
