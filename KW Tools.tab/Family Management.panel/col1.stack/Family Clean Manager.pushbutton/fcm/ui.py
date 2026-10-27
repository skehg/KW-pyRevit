# -*- coding: utf-8 -*-

import os

from pyrevit import forms


class FamilyCleanManagerWindow(forms.WPFWindow):
    def __init__(self, vm):
        xaml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "FamilyCleanManager.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        self._vm = vm
        self._rows = {}
        self._fill_options = []

        self.txtFamilyName.Text = "Family: {0}".format(vm.doc.Title)
        self._analyze()

    def _update_family_header(self):
        active_doc = self._vm.get_active_family_doc()
        if active_doc is None:
            self.txtFamilyName.Text = "Family: <No active family>"
        else:
            self.txtFamilyName.Text = "Family: {0}".format(active_doc.Title)

    def _selected_rows(self, list_box):
        return [row for row in list_box.SelectedItems]

    def _set_rows(self, list_box, rows):
        list_box.ItemsSource = rows

    def _refresh_fill_pattern_options(self):
        self._fill_options = self._vm.get_fill_pattern_options()
        self.cmbFillPatternReplacement.ItemsSource = self._fill_options
        if self._fill_options:
            self.cmbFillPatternReplacement.SelectedIndex = 0

    def _analyze(self):
        self._update_family_header()
        self._rows = self._vm.analyze_family()
        self._set_rows(self.lstMaterials, self._rows.get("materials", []))
        self._set_rows(self.lstFillPatterns, self._rows.get("fill_patterns", []))
        self._set_rows(self.lstSubcategories, self._rows.get("subcategories", []))
        self._set_rows(self.lstDwgs, self._rows.get("dwg_imports", []))
        self._set_rows(self.lstNestedFamilies, self._rows.get("nested_families", []))
        self._refresh_fill_pattern_options()
        if self._vm.get_active_family_doc() is None:
            self.txtStatus.Text = "No active family document. Activate a family and click Analyse Family."
        else:
            self.txtStatus.Text = "Family analysis completed."

    def _run_delete(self, rows, transaction_name):
        if not rows:
            self.txtStatus.Text = "Nothing selected."
            return
        deleted_count = self._vm.delete_issues(rows, transaction_name)
        self._analyze()
        if deleted_count == 0:
            self.txtStatus.Text = "No items were deleted. Ensure the active document is a family and items are deletable."
        else:
            self.txtStatus.Text = "Deleted {0} selected item(s).".format(deleted_count)

    def on_analyze_click(self, sender, args):
        self._analyze()

    def on_deep_scan_click(self, sender, args):
        nested_rows = self._vm.deep_scan_nested_families()
        self._set_rows(self.lstNestedFamilies, nested_rows)
        self.txtStatus.Text = "Deep scan completed."

    def on_delete_materials_click(self, sender, args):
        self._run_delete(self._selected_rows(self.lstMaterials), "Delete Materials")

    def on_delete_fill_patterns_click(self, sender, args):
        self._run_delete(self._selected_rows(self.lstFillPatterns), "Delete Fill Patterns")

    def on_delete_subcategories_click(self, sender, args):
        self._run_delete(self._selected_rows(self.lstSubcategories), "Delete Subcategories")

    def on_delete_dwgs_click(self, sender, args):
        self._run_delete(self._selected_rows(self.lstDwgs), "Delete DWG Imports")

    def on_replace_fill_patterns_click(self, sender, args):
        selected_rows = self._selected_rows(self.lstFillPatterns)
        if not selected_rows:
            self.txtStatus.Text = "Select fill patterns to replace."
            return

        replacement = self.cmbFillPatternReplacement.SelectedItem
        if replacement is None:
            self.txtStatus.Text = "Select a replacement fill pattern."
            return

        changes = self._vm.replace_fill_patterns(selected_rows, replacement.ElementId)
        self._analyze()
        self.txtStatus.Text = "Updated {0} fill pattern reference(s).".format(changes)

    def on_open_nested_click(self, sender, args):
        selected = self._selected_rows(self.lstNestedFamilies)
        if not selected:
            self.txtStatus.Text = "Select one nested family to open."
            return

        message = self._vm.open_nested_family(selected[0])
        self._analyze()
        self.txtStatus.Text = message

    def on_close_click(self, sender, args):
        self.Close()
