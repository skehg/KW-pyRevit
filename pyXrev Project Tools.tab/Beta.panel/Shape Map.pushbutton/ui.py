# -*- coding: utf-8 -*-
import os

from pyrevit import forms


class ShapeMapWindow(forms.WPFWindow):
    def __init__(self, source_label, destination_label, default_grid_spacing_display, default_edge_spacing_display, grid_unit_label):
        xaml_path = os.path.join(os.path.dirname(__file__), "ui.xaml")
        forms.WPFWindow.__init__(self, xaml_path)

        self._result = None

        self.txtSource.Text = source_label or "<unknown source>"
        self.txtDestination.Text = destination_label or "<unknown destination>"
        self.txtGridLabel.Text = "Internal grid spacing ({0})".format(grid_unit_label)
        self.txtEdgeLabel.Text = "Edge point spacing ({0})".format(grid_unit_label)
        self.txtPointOffsetLabel.Text = "Global Z offset applied to all mapped points ({0})".format(grid_unit_label)
        self.txtGridSpacing.Text = "{0:.3f}".format(float(default_grid_spacing_display))
        self.txtEdgeSpacing.Text = "{0:.3f}".format(float(default_edge_spacing_display))
        self.cmbSamplingMode.SelectedIndex = 0
        self.chkUseInteriorGrid.IsChecked = True
        self.cmbSamplingMode.SelectionChanged += self.on_sampling_mode_changed
        self.chkUseInteriorGrid.Click += self.on_use_interior_grid_changed
        self._sync_sampling_controls()

    @property
    def result(self):
        return self._result

    def _selected_tag(self, combo_box, fallback):
        try:
            selected = combo_box.SelectedItem
            if selected is not None and hasattr(selected, "Tag") and selected.Tag:
                return str(selected.Tag)
        except Exception:
            pass
        return fallback

    def _sync_sampling_controls(self):
        sampling_mode = self._selected_tag(self.cmbSamplingMode, "hybrid")
        use_interior_grid = bool(self.chkUseInteriorGrid.IsChecked)

        if sampling_mode in ("source_vertices_only", "destination_vertices_only"):
            self.chkUseInteriorGrid.IsChecked = False
            self.chkUseInteriorGrid.IsEnabled = False
            use_interior_grid = False
            self.txtGridLabel.IsEnabled = False
            self.txtGridSpacing.IsEnabled = False
            self.txtEdgeLabel.IsEnabled = False
            self.txtEdgeSpacing.IsEnabled = False
            self.txtEdgeHelp.IsEnabled = False
        elif sampling_mode == "edge_only":
            self.chkUseInteriorGrid.IsChecked = False
            self.chkUseInteriorGrid.IsEnabled = False
            self.txtGridLabel.IsEnabled = False
            self.txtGridSpacing.IsEnabled = False
            self.txtEdgeLabel.IsEnabled = True
            self.txtEdgeSpacing.IsEnabled = True
            self.txtEdgeHelp.IsEnabled = True
        else:
            self.chkUseInteriorGrid.IsEnabled = True
            self.txtGridLabel.IsEnabled = use_interior_grid
            self.txtGridSpacing.IsEnabled = use_interior_grid
            self.txtEdgeLabel.IsEnabled = True
            self.txtEdgeSpacing.IsEnabled = True
            self.txtEdgeHelp.IsEnabled = True

    def on_sampling_mode_changed(self, sender, args):
        self._sync_sampling_controls()

    def on_use_interior_grid_changed(self, sender, args):
        self._sync_sampling_controls()

    def on_run(self, sender, args):
        sampling_mode = self._selected_tag(self.cmbSamplingMode, "hybrid")
        use_interior_grid = bool(self.chkUseInteriorGrid.IsChecked) and sampling_mode == "hybrid"

        grid_spacing = None
        if use_interior_grid:
            try:
                grid_spacing = float((self.txtGridSpacing.Text or "").strip())
            except Exception:
                forms.alert("Grid spacing must be a numeric value.", title="Shape Map")
                return

            if grid_spacing <= 0.0:
                forms.alert("Grid spacing must be greater than zero.", title="Shape Map")
                return

        edge_spacing = None
        if sampling_mode in ("hybrid", "edge_only"):
            try:
                edge_spacing = float((self.txtEdgeSpacing.Text or "").strip())
            except Exception:
                forms.alert("Edge spacing must be a numeric value.", title="Shape Map")
                return

            if edge_spacing <= 0.0:
                forms.alert("Edge spacing must be greater than zero.", title="Shape Map")
                return

        try:
            point_offset = float((self.txtPointOffset.Text or "").strip())
        except Exception:
            forms.alert("Global point offset must be a numeric value.", title="Shape Map")
            return

        z_mode = "relative_level_offset"
        z_mode = self._selected_tag(self.cmbZMode, "relative_level_offset")

        self._result = {
            "align_level_offset": bool(self.chkAlignLevelOffset.IsChecked),
            "sampling_mode": sampling_mode,
            "use_interior_grid": use_interior_grid,
            "grid_spacing_display": grid_spacing,
            "edge_spacing_display": edge_spacing,
            "point_offset_display": point_offset,
            "z_mode": z_mode,
            "skip_zero_offsets": bool(self.chkSkipZeroOffsets.IsChecked),
            "debug_fallback": bool(self.chkDebugFallback.IsChecked),
        }
        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()
