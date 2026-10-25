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
                 context_text=None, grid_layout=None, separator_before=None):
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
        self._separator_before = set(separator_before or [])
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
            pending_separator = False
            for option in self._options:
                if option in self._separator_before:
                    pending_separator = True
                if query not in option.lower():
                    continue
                if pending_separator and self.lstChoices.Items.Count:
                    from System.Windows import HorizontalAlignment, Thickness
                    from System.Windows.Controls import ListBoxItem, Separator
                    divider = ListBoxItem()
                    divider.Content = Separator()
                    divider.IsEnabled = False
                    divider.Focusable = False
                    divider.HorizontalContentAlignment = HorizontalAlignment.Stretch
                    divider.Padding = Thickness(0)
                    divider.Margin = Thickness(4, 6, 4, 6)
                    self.lstChoices.Items.Add(divider)
                pending_separator = False
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
                 selected=None, last=True, context_text=None, field_options=None,
                 combined_categories=False):
        from core.optional_fields import field_options as normalize_options, select_usage
        from System.Windows import Visibility
        self._visibility = Visibility
        xaml_path = os.path.join(os.path.dirname(__file__), "wizard.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        self._all_usage = usage_map
        self._parameter_mode = parameter_mode
        self.field_options = normalize_options(field_options)
        usage_map = select_usage(usage_map, self.field_options)
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
        self._highlighted_available = set()
        self._refreshing_available = False
        self._sort_by = "name"
        self._data_type_filter = None
        self.selected_parameters = None
        self.action = "cancel"
        self.btnContinue.Content = "Open Grid" if last else "Next category"
        self.lblCategory.Text = category_label
        self.lblMode.Text = context_text or parameter_mode
        if parameter_mode == MODE_TYPES:
            self.lblMode.Text += " | Instance-only parameters are hidden."
        self.cboAvailability.SelectionChanged += self.on_filter_changed
        if hasattr(self, "cboCoverage"):
            from System.Windows import Visibility
            self.cboCoverage.Visibility = (
                Visibility.Visible if combined_categories else Visibility.Collapsed
            )
            self.cboCoverage.SelectionChanged += self.on_filter_changed
        for control, key in (("chkCoordinates", "coordinates"),
                             ("chkUsefulFields", "usefulFields"),
                             ("chkFalsePositives", "filterFalsePositives")):
            if hasattr(self, control):
                checkbox = getattr(self, control)
                checkbox.IsChecked = self.field_options[key]
                checkbox.Checked += self.on_field_options_changed
                checkbox.Unchecked += self.on_field_options_changed
                if key != "filterFalsePositives":
                    checkbox.IsEnabled = parameter_mode != MODE_TYPES

        for name in self._parameter_names:
            self._items[name] = ParameterListItem(name, self._usage_map[name])
            self._available_displays.add(name)
        for name in selected or []:
            if name in self._items:
                self.lstSelected.Items.Add(self._items[name])
                self._available_displays.discard(name)
        self._refresh_available()

    def on_field_options_changed(self, sender, args):
        from core.optional_fields import select_usage
        self._capture_available_selection()
        selected = [str(item) for item in self.lstSelected.Items]
        self.field_options = {
            "coordinates": bool(self.chkCoordinates.IsChecked),
            "usefulFields": bool(self.chkUsefulFields.IsChecked),
            "filterFalsePositives": bool(self.chkFalsePositives.IsChecked),
        }
        self._usage_map = select_usage(self._all_usage, self.field_options)
        self._parameter_names = [
            key for key, usage in self._usage_map.items()
            if self._parameter_mode != MODE_TYPES or usage.get("isType")
        ]
        removed = [key for key in selected if key not in self._parameter_names]
        self._items = dict((key, ParameterListItem(key, self._usage_map[key]))
                           for key in self._parameter_names)
        self.lstSelected.Items.Clear()
        for key in selected:
            if key in self._items:
                self.lstSelected.Items.Add(self._items[key])
        self._available_displays = set(self._items) - set(selected)
        self._refresh_available()
        if removed:
            forms.alert(
                "{0} selected field(s) were removed by these options. "
                "Disable filtering or re-enable API fields to make them available again."
                .format(len(removed)), title="KW ExcelLink")

    def on_filter_changed(self, sender, args):
        if hasattr(self, "_usage_map"):
            self._refresh_available()

    def on_search_changed(self, sender, args):
        if not hasattr(self, "_available_displays"):
            return
        self._refresh_available()

    def on_add(self, sender, args):
        self._capture_available_selection()
        items = sorted(self._highlighted_available, key=self._available_sort_key)
        if not items:
            return
        for key in items:
            self.lstSelected.Items.Add(self._items[key])
        self.lstSelected.SelectedItems.Clear()
        for key in items:
            self.lstSelected.SelectedItems.Add(self._items[key])
        self._available_displays.difference_update(items)
        self._highlighted_available.clear()
        self._refresh_available()

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

    def _capture_available_selection(self):
        self._highlighted_available.difference_update(
            str(item) for item in self.lstAvailable.Items)
        self._highlighted_available.update(
            str(item) for item in self.lstAvailable.SelectedItems)
        self._highlighted_available.intersection_update(self._available_displays)

    def on_available_selection_changed(self, sender, args):
        if (not hasattr(self, "_highlighted_available")
                or self._refreshing_available):
            return
        self._capture_available_selection()
        self._update_available_status()

    def _available_sort_key(self, key):
        item = self._items[key]
        name_key = (item.Name.lower(), item.Name, key)
        if self._sort_by == "dataType":
            return (item.DataType.lower(), item.DataType) + name_key
        return name_key

    def on_available_right_click(self, sender, args):
        # Keep ListBoxItem's right-click handling from replacing a bulk selection.
        args.Handled = True

    def on_available_menu_opening(self, sender, args):
        from System.Windows.Controls import MenuItem
        menu = sender.ContextMenu
        menu.Items.Clear()
        sort_menu = MenuItem()
        sort_menu.Header = "Sort by"
        for key, label in (("name", "Name A-Z"),
                           ("dataType", "Data type, then name A-Z")):
            option = MenuItem()
            option.Header = label
            option.Tag = key
            option.IsCheckable = True
            option.IsChecked = self._sort_by == key
            option.Click += self.on_sort_available
            sort_menu.Items.Add(option)
        menu.Items.Add(sort_menu)
        filter_menu = MenuItem()
        filter_menu.Header = "Data type"
        data_types = set(item.DataType for item in self._items.values())
        if self._data_type_filter is not None:
            data_types.add(self._data_type_filter)
        for data_type in [None] + sorted(data_types, key=lambda value: (value.lower(), value)):
            option = MenuItem()
            option.Header = data_type if data_type is not None else "All data types"
            option.Tag = data_type
            option.IsCheckable = True
            option.IsChecked = self._data_type_filter == data_type
            option.Click += self.on_filter_data_type
            filter_menu.Items.Add(option)
        menu.Items.Add(filter_menu)

    def on_sort_available(self, sender, args):
        self._sort_by = str(sender.Tag)
        sender.IsChecked = True
        self._refresh_available()

    def on_filter_data_type(self, sender, args):
        self._data_type_filter = sender.Tag
        sender.IsChecked = True
        self._refresh_available()

    def on_clear_data_type_filter(self, sender, args):
        self._data_type_filter = None
        self._refresh_available()

    def _update_available_status(self):
        self.pnlDataTypeFilter.Visibility = (
            self._visibility.Visible if self._data_type_filter is not None
            else self._visibility.Collapsed
        )
        self.lblDataTypeFilter.Text = (
            "Data type filter: {0}".format(self._data_type_filter)
            if self._data_type_filter is not None else ""
        )
        visible = set(str(item) for item in self.lstAvailable.Items)
        hidden_count = len(self._highlighted_available - visible)
        self.lblAvailableStatus.Text = (
            "Sort: {0} | Filter: {1}\n"
            "{2} highlighted ({3} hidden). Add includes hidden highlights.".format(
                "Data type, then name" if self._sort_by == "dataType" else "Name A-Z",
                self._data_type_filter if self._data_type_filter is not None else "All data types",
                len(self._highlighted_available), hidden_count,
            )
        )

    def _refresh_available(self):
        self._capture_available_selection()
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
                and (self._data_type_filter is None
                     or self._items[item].DataType == self._data_type_filter)
                and matches_usage(item)
            ],
            key=self._available_sort_key,
        )
        self._refreshing_available = True
        try:
            self.lstAvailable.Items.Clear()
            for item in items:
                self.lstAvailable.Items.Add(self._items[item])
            self.lstAvailable.SelectedItems.Clear()
            for item in items:
                if item in self._highlighted_available:
                    self.lstAvailable.SelectedItems.Add(self._items[item])
        finally:
            self._refreshing_available = False
        self._update_available_status()
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
