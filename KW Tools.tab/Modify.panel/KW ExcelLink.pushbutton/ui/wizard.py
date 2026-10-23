# -*- coding: utf-8 -*-

import os

from pyrevit import forms
from core.types import MODE_TYPES


class ParameterListItem(object):
    def __init__(self, name, usage):
        self.Key = name
        self.Name = usage.get("displayName", usage.get("name", name))
        self.DataType = usage.get("dataType") or "Unspecified"
        self.Coverage = (
            "{0}/{1} categories".format(usage["categoryCount"], usage["totalCategories"])
            if usage.get("totalCategories", 0) > 1 else ""
        )
        self.Details = "{0}\n{1}\n{2}".format(
            self.Name, self.DataType, ", ".join(usage.get("categoryNames") or []))
        if usage.get("isType") and usage.get("isInstance"):
            self.Mode = "Type + Instance"
            self.BadgeBackground = "#F0EAF8"
            self.BadgeForeground = "#62428A"
        elif usage.get("isType"):
            self.Mode = "Type"
            self.BadgeBackground = "#E5F0FC"
            self.BadgeForeground = "#205A91"
        else:
            self.Mode = "Instance" if usage.get("isInstance") else "Unavailable"
            self.BadgeBackground = "#EDF0F3"
            self.BadgeForeground = "#465260"

    def __str__(self):
        return self.Key


class ChoiceWizardWindow(forms.WPFWindow):
    def __init__(self, options, title, selected=None, multiple=False, back=True,
                 context_text=None, grid_layout=None):
        forms.WPFWindow.__init__(
            self, os.path.join(os.path.dirname(__file__), "choice.xaml")
        )
        from System.Windows import Visibility
        from System.Windows.Controls import SelectionMode
        self.Title = title
        self.lblTitle.Text = title
        self.lblContext.Text = context_text or ""
        self.action = "cancel"
        self.selected = []
        self._options = list(options)
        self._chosen = set(selected or [])
        self._multiple = multiple
        self._refreshing = False
        self.grid_layout = grid_layout
        self.btnBack.Visibility = Visibility.Visible if back else Visibility.Collapsed
        self.lstChoices.SelectionMode = SelectionMode.Multiple if multiple else SelectionMode.Single
        if grid_layout is not None:
            self.pnlGridLayout.Visibility = Visibility.Visible
            self.cboGridLayout.Items.Add("Separate category sheets")
            self.cboGridLayout.Items.Add("Combined grid")
            self.cboGridLayout.SelectedIndex = 1 if grid_layout == "combined" else 0
        self._refresh_choices()

    def _capture(self):
        if self._multiple:
            self._chosen.difference_update(str(item) for item in self.lstChoices.Items)
        else:
            self._chosen.clear()
        self._chosen.update(str(item) for item in self.lstChoices.SelectedItems)
        self.selected = [item for item in self._options if item in self._chosen]
        if self.grid_layout is not None:
            self.grid_layout = (
                "combined" if self.cboGridLayout.SelectedIndex == 1 else "separate"
            )

    def on_selection_changed(self, sender, args):
        if hasattr(self, "_refreshing") and not self._refreshing:
            self._capture()

    def on_search_changed(self, sender, args):
        if hasattr(self, "_options"):
            self._refresh_choices()

    def _refresh_choices(self):
        self._refreshing = True
        try:
            query = str(self.txtSearch.Text or "").strip().lower()
            self.lstChoices.Items.Clear()
            for option in self._options:
                if query not in option.lower():
                    continue
                self.lstChoices.Items.Add(option)
                if option in self._chosen:
                    if self._multiple:
                        self.lstChoices.SelectedItems.Add(option)
                    else:
                        self.lstChoices.SelectedItem = option
        finally:
            self._refreshing = False

    def on_back(self, sender, args):
        self._capture()
        self.action = "back"
        self.Close()

    def on_continue(self, sender, args):
        self._capture()
        if not self.selected:
            forms.alert("Choose at least one option.", title="KW ExcelLink")
            return
        self.action = "next"
        self.Close()

    def on_cancel(self, sender, args):
        self.Close()


class ParameterWizardWindow(forms.WPFWindow):
    def __init__(self, category_label, usage_map, parameter_mode,
                 selected=None, last=True, context_text=None):
        xaml_path = os.path.join(os.path.dirname(__file__), "wizard.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        self.Title = "Step 4 of 5 - Parameters - {0}".format(category_label)
        self._parameter_names = sorted(
            (name for name, usage in usage_map.items()
             if parameter_mode != MODE_TYPES or usage.get("isType")),
            key=lambda value: usage_map[value].get("displayName", value).lower()
        )
        self._usage_map = dict((key, dict(value)) for key, value in usage_map.items())
        if parameter_mode == MODE_TYPES:
            for usage in self._usage_map.values():
                if "typeCategoryIds" in usage:
                    included = set(usage["typeCategoryIds"])
                    usage["categoryCount"] = len(included)
                    usage["categoryNames"] = [
                        label for category_id, label in zip(usage["categoryIds"], usage["categoryNames"])
                        if category_id in included
                    ]
        self._items = {}
        self._available_displays = set()
        self.selected_parameters = None
        self.action = "cancel"
        self.btnContinue.Content = "Open Grid" if last else "Next category"
        self.lblCategory.Text = category_label
        self.lblMode.Text = context_text or parameter_mode
        if parameter_mode == MODE_TYPES:
            self.lblMode.Text += " | Instance-only parameters are hidden."
        self.cboAvailability.SelectionChanged += self.on_filter_changed
        if hasattr(self, "cboCoverage"):
            self.cboCoverage.SelectionChanged += self.on_filter_changed

        for name in self._parameter_names:
            self._items[name] = ParameterListItem(name, self._usage_map[name])
            self._available_displays.add(name)
        for name in selected or []:
            if name in self._items:
                self.lstSelected.Items.Add(self._items[name])
                self._available_displays.discard(name)
        self._refresh_available()

    def on_filter_changed(self, sender, args):
        if hasattr(self, "_usage_map"):
            self._refresh_available()

    def on_search_changed(self, sender, args):
        if not hasattr(self, "_available_displays"):
            return
        self._refresh_available()

    def on_add(self, sender, args):
        self._transfer_selected(self.lstAvailable, self.lstSelected)

    def on_remove(self, sender, args):
        self._transfer_selected(self.lstSelected, self.lstAvailable)

    def _transfer_selected(self, source, destination):
        selected_items = set(str(item) for item in source.SelectedItems)
        if not selected_items:
            return

        selected_order = [
            str(item) for item in source.Items
            if str(item) in selected_items
        ]
        for index in range(source.Items.Count - 1, -1, -1):
            item = str(source.Items[index])
            if item in selected_items:
                source.Items.RemoveAt(index)

        if source is self.lstAvailable:
            self._available_displays.difference_update(selected_items)
        elif destination is self.lstAvailable:
            self._available_displays.update(selected_order)

        existing_items = set(str(item) for item in destination.Items)
        selected_order = [
            item for item in selected_order if item not in existing_items
        ]
        if destination is not self.lstAvailable:
            for item in selected_order:
                destination.Items.Add(self._items[item])

        if destination is self.lstSelected:
            destination.SelectedItems.Clear()
            for item in selected_order:
                destination.SelectedItems.Add(self._items[item])
        self._refresh_available()

    def _refresh_available(self):
        selected_items = set(
            str(item) for item in self.lstAvailable.SelectedItems
        )
        search_text = str(self.txtSearch.Text or "").strip().lower()
        selected_filter = self.cboAvailability.SelectedItem
        filter_mode = str(
            selected_filter.Content if selected_filter is not None
            else "All parameters"
        )

        def matches_usage(name):
            usage = self._usage_map[name]
            coverage = getattr(self, "cboCoverage", None)
            if (coverage is not None and coverage.SelectedIndex == 1
                    and usage.get("categoryCount", 0) < usage.get("totalCategories", 0)):
                return False
            is_type = bool(usage.get("isType"))
            is_instance = bool(usage.get("isInstance"))
            if filter_mode == "Type parameters":
                return is_type
            if filter_mode == "Instance parameters":
                return is_instance
            if filter_mode == "Mixed-use parameters":
                return is_type and is_instance
            return True

        items = sorted(
            [
                item for item in self._available_displays
                if search_text in self._items[item].Name.lower()
                and matches_usage(item)
            ],
            key=lambda value: self._items[value].Name.lower(),
        )
        self.lstAvailable.Items.Clear()
        for item in items:
            self.lstAvailable.Items.Add(self._items[item])
        self.lstAvailable.SelectedItems.Clear()
        for item in items:
            if item in selected_items:
                self.lstAvailable.SelectedItems.Add(self._items[item])
        self.lblCounts.Text = (
            "{0} shown of {1} available · {2} selected".format(
                len(items), len(self._available_displays), self.lstSelected.Items.Count
            )
        )

    def on_move_up(self, sender, args):
        self._move_selected(-1)

    def on_move_down(self, sender, args):
        self._move_selected(1)

    def _move_selected(self, direction):
        list_box = self.lstSelected
        count = list_box.Items.Count
        selected_items = set(str(item) for item in list_box.SelectedItems)
        selected_indexes = set(
            index for index in range(count)
            if str(list_box.Items[index]) in selected_items
        )
        if not selected_indexes:
            return

        items = [str(item) for item in list_box.Items]
        if direction < 0:
            for index in range(1, count):
                if index in selected_indexes and index - 1 not in selected_indexes:
                    items[index - 1], items[index] = items[index], items[index - 1]
                    selected_indexes.remove(index)
                    selected_indexes.add(index - 1)
        else:
            for index in range(count - 2, -1, -1):
                if index in selected_indexes and index + 1 not in selected_indexes:
                    items[index], items[index + 1] = items[index + 1], items[index]
                    selected_indexes.remove(index)
                    selected_indexes.add(index + 1)

        list_box.Items.Clear()
        for item in items:
            list_box.Items.Add(self._items[item])
        list_box.SelectedItems.Clear()
        for index in sorted(selected_indexes):
            list_box.SelectedItems.Add(list_box.Items[index])
        self._refresh_available()

    def on_continue(self, sender, args):
        self.selected_parameters = [
            str(item) for item in self.lstSelected.Items
        ]
        if not self.selected_parameters:
            forms.alert("Select at least one parameter.", title="KW ExcelLink")
            return
        self.action = "next"
        self.DialogResult = True
        self.Close()

    def on_back(self, sender, args):
        self.selected_parameters = [
            str(item) for item in self.lstSelected.Items
        ]
        self.action = "back"
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()
