# -*- coding: utf-8 -*-

import os

from pyrevit import forms


class ChoiceWizardWindow(forms.WPFWindow):
    def __init__(self, options, title, selected=None, multiple=False, back=True):
        forms.WPFWindow.__init__(
            self, os.path.join(os.path.dirname(__file__), "choice.xaml")
        )
        from System.Windows import Visibility
        from System.Windows.Controls import SelectionMode
        self.Title = title
        self.lblTitle.Text = title
        self.action = "cancel"
        self.selected = []
        self._options = list(options)
        self._chosen = set(selected or [])
        self._multiple = multiple
        self._refreshing = False
        self.btnBack.Visibility = Visibility.Visible if back else Visibility.Collapsed
        self.lstChoices.SelectionMode = SelectionMode.Multiple if multiple else SelectionMode.Single
        self._refresh_choices()

    def _capture(self):
        if self._multiple:
            self._chosen.difference_update(str(item) for item in self.lstChoices.Items)
        else:
            self._chosen.clear()
        self._chosen.update(str(item) for item in self.lstChoices.SelectedItems)
        self.selected = [item for item in self._options if item in self._chosen]

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
                 selected=None, last=True):
        xaml_path = os.path.join(os.path.dirname(__file__), "wizard.xaml")
        forms.WPFWindow.__init__(self, xaml_path)
        self.Title = "Step 4 of 5 - Parameters - {0}".format(category_label)
        self._parameter_names = sorted(
            usage_map.keys(), key=lambda value: value.lower()
        )
        self._display_names = {}
        self._available_displays = set()
        self.selected_parameters = None
        self.action = "cancel"
        self.btnContinue.Content = "Open Grid" if last else "Next category"
        self.lblCategory.Text = category_label
        self.lblMode.Text = parameter_mode

        for name in self._parameter_names:
            usage = usage_map[name]
            labels = []
            if usage.get("isType"):
                labels.append("Type")
            if usage.get("isInstance"):
                labels.append("Instance")
            display = "{0}  [{1}]".format(name, ", ".join(labels))
            self._display_names[display] = name
            self._available_displays.add(display)
            self.lstAvailable.Items.Add(display)
        by_name = dict((name, display) for display, name in self._display_names.items())
        for name in selected or []:
            if name in by_name:
                display = by_name[name]
                self.lstSelected.Items.Add(display)
                self._available_displays.discard(display)
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
                destination.Items.Add(item)

        if destination is self.lstSelected:
            destination.SelectedItems.Clear()
            for item in selected_order:
                destination.SelectedItems.Add(item)
        self._refresh_available()

    def _refresh_available(self):
        selected_items = set(
            str(item) for item in self.lstAvailable.SelectedItems
        )
        search_text = str(self.txtSearch.Text or "").strip().lower()
        items = sorted(
            [
                item for item in self._available_displays
                if search_text in self._display_names[item].lower()
            ],
            key=lambda value: self._display_names[value].lower(),
        )
        self.lstAvailable.Items.Clear()
        for item in items:
            self.lstAvailable.Items.Add(item)
        self.lstAvailable.SelectedItems.Clear()
        for item in items:
            if item in selected_items:
                self.lstAvailable.SelectedItems.Add(item)

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
            list_box.Items.Add(item)
        list_box.SelectedItems.Clear()
        for index in sorted(selected_indexes):
            list_box.SelectedItems.Add(list_box.Items[index])

    def on_continue(self, sender, args):
        self.selected_parameters = [
            self._display_names[str(item)] for item in self.lstSelected.Items
        ]
        if not self.selected_parameters:
            forms.alert("Select at least one parameter.", title="KW ExcelLink")
            return
        self.action = "next"
        self.DialogResult = True
        self.Close()

    def on_back(self, sender, args):
        self.selected_parameters = [
            self._display_names[str(item)] for item in self.lstSelected.Items
        ]
        self.action = "back"
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()
