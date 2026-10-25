"""Parameter picker presentation and selection without WPF or Revit."""
import importlib.util
import os
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class Collection(list):
    @property
    def Count(self):
        return len(self)

    def Add(self, item):
        self.append(item)

    def Clear(self):
        self.clear()

    def RemoveAt(self, index):
        self.pop(index)


class Event(object):
    def __iadd__(self, callback):
        return self


class FakeWindow(object):
    def __init__(self, path):
        self.lstAvailable = types.SimpleNamespace(
            Items=Collection(), SelectedItems=Collection()
        )
        self.lstSelected = types.SimpleNamespace(
            Items=Collection(), SelectedItems=Collection()
        )
        self.btnContinue = types.SimpleNamespace(Content="")
        self.lblCategory = types.SimpleNamespace(Text="")
        self.lblMode = types.SimpleNamespace(Text="")
        self.lblCounts = types.SimpleNamespace(Text="")
        self.lblAvailableStatus = types.SimpleNamespace(Text="")
        self.pnlDataTypeFilter = types.SimpleNamespace(Visibility="Collapsed")
        self.lblDataTypeFilter = types.SimpleNamespace(Text="")
        self.txtSearch = types.SimpleNamespace(Text="")
        self.cboAvailability = types.SimpleNamespace(
            SelectionChanged=Event(),
            SelectedItem=types.SimpleNamespace(Content="All parameters"),
        )
        self.cboCoverage = types.SimpleNamespace(
            SelectionChanged=Event(), SelectedIndex=0, Visibility="Collapsed",
        )

    def Close(self):
        pass


class ParameterPickerTests(unittest.TestCase):
    def setUp(self):
        pyrevit = types.ModuleType("pyrevit")
        self.forms = types.SimpleNamespace(WPFWindow=FakeWindow, alert=Mock())
        pyrevit.forms = self.forms
        core_types = types.ModuleType("core.types")
        core_types.MODE_TYPES = "Types Mode"
        spec = importlib.util.spec_from_file_location(
            "tested_wizard", os.path.join(ROOT, "ui", "wizard.py")
        )
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"pyrevit": pyrevit, "core.types": core_types}):
            spec.loader.exec_module(self.module)
        self.usage = {
            "Width": {"isType": True},
            "Comments": {"isInstance": True},
            "Mark": {"isType": True, "isInstance": True},
        }

    def window(self, mode="Instances Mode", selected=None, combined_categories=False):
        windows = types.ModuleType("System.Windows")
        windows.Visibility = types.SimpleNamespace(Visible="Visible", Collapsed="Collapsed")
        with patch.dict(sys.modules, {"System.Windows": windows}):
            return self.module.ParameterWizardWindow(
                "Doors", self.usage, mode, selected,
                combined_categories=combined_categories,
            )

    def test_category_coverage_is_visible_only_for_combined_grids(self):
        self.assertEqual(self.window().cboCoverage.Visibility, "Collapsed")
        combined = self.window(combined_categories=True)
        self.assertEqual(combined.cboCoverage.Visibility, "Visible")
        self.assertEqual(combined.cboCoverage.SelectedIndex, 0)

    def names(self, collection):
        return [str(item) for item in collection]

    def choice_window(self, query=""):
        window = self.module.ChoiceWizardWindow.__new__(self.module.ChoiceWizardWindow)
        window._options = [
            "Selected Elements", "Current View", "Entire Model",
            "Entire Project File", "Import XLSX...", "Load Preset...",
            "Manage presets...",
        ]
        window._separator_before = {"Import XLSX...", "Load Preset..."}
        window._chosen = {"Current View"}
        window._multiple = False
        window.grid_layout = None
        window.txtSearch = types.SimpleNamespace(Text=query)
        window.lstChoices = types.SimpleNamespace(
            Items=Collection(), SelectedItems=Collection(), SelectedItem=None,
        )
        windows = types.ModuleType("System.Windows")
        windows.HorizontalAlignment = types.SimpleNamespace(Stretch="Stretch")
        windows.Thickness = lambda *values: values
        controls = types.ModuleType("System.Windows.Controls")
        controls.ListBoxItem = types.SimpleNamespace
        controls.Separator = types.SimpleNamespace
        with patch.dict(sys.modules, {
            "System.Windows": windows, "System.Windows.Controls": controls,
        }):
            window._refresh_choices()
        return window

    def test_choice_groups_have_disabled_full_width_separators(self):
        window = self.choice_window()
        items = window.lstChoices.Items
        self.assertEqual([item for item in items if isinstance(item, str)], window._options)
        self.assertEqual(len(items), 9)
        for index in (4, 6):
            self.assertFalse(items[index].IsEnabled)
            self.assertFalse(items[index].Focusable)
            self.assertEqual(items[index].HorizontalContentAlignment, "Stretch")
        self.assertEqual(window.lstChoices.SelectedItem, "Current View")
        window.lstChoices.SelectedItems.Add("Current View")
        window._capture()
        self.assertEqual(window.selected, ["Current View"])

    def test_filtered_choice_groups_have_no_orphan_separators(self):
        for query, expected in (
            ("xlsx", ["Import XLSX..."]),
            ("preset", ["Load Preset...", "Manage presets..."]),
            ("missing", []),
        ):
            window = self.choice_window(query)
            self.assertEqual(window.lstChoices.Items, expected)
        window = self.choice_window("s")
        items = window.lstChoices.Items
        self.assertEqual(items[0], "Selected Elements")
        self.assertFalse(items[1].IsEnabled)
        self.assertEqual(items[2], "Import XLSX...")
        self.assertFalse(items[3].IsEnabled)
        self.assertEqual(items[4], "Load Preset...")
        self.assertEqual(items[5], "Manage presets...")
        self.assertEqual(len(items), 6)

    def test_badges_separate_names_from_availability(self):
        window = self.window()
        self.assertEqual(self.names(window.lstAvailable.Items), ["Comments", "Mark", "Width"])
        for name, mode in (("Width", "Type"), ("Comments", "Instance"),
                           ("Mark", "Type + Instance")):
            self.assertEqual(window._items[name].Name, name)
            self.assertEqual(window._items[name].Mode, mode)
        self.assertEqual(len(set(item.BadgeBackground for item in window._items.values())), 3)

    def test_optional_fields_toggle_rebuilds_list_and_can_restore_raw_parameters(self):
        self.usage["Category"] = {
            "isInstance": True, "usefulInstance": False, "name": "Category"}
        self.usage["derived:internal_0"] = {
            "isInstance": True, "name": "Internal X", "derivedGroup": "coordinates"}
        window = self.window()
        self.assertNotIn("Category", window._items)
        self.assertNotIn("derived:internal_0", window._items)
        window.chkCoordinates = types.SimpleNamespace(IsChecked=True)
        window.chkUsefulFields = types.SimpleNamespace(IsChecked=False)
        window.chkFalsePositives = types.SimpleNamespace(IsChecked=False)
        window.on_field_options_changed(None, None)
        self.assertIn("Category", window._items)
        self.assertIn("derived:internal_0", window._items)
        window.lstSelected.Items.Add(window._items["derived:internal_0"])
        window.chkCoordinates.IsChecked = False
        window.on_field_options_changed(None, None)
        self.assertEqual(window.lstSelected.Items.Count, 0)
        self.forms.alert.assert_called_once()

    def test_semantic_type_badges_display_names_and_category_coverage(self):
        self.usage = {
            "opaque-width": {
                "name": "Width", "displayName": "Width", "dataType": "Length",
                "isType": True, "categoryCount": 1, "totalCategories": 2,
                "categoryNames": ["Doors"],
            },
            "opaque-flag": {
                "name": "Enabled", "displayName": "Enabled", "dataType": "Yes/No",
                "isInstance": True, "categoryCount": 2, "totalCategories": 2,
                "categoryNames": ["Doors", "Windows"],
            },
        }
        window = self.window()
        self.assertEqual(window._items["opaque-width"].Name, "Width")
        self.assertEqual(window._items["opaque-width"].DataType, "Length")
        self.assertEqual(window._items["opaque-width"].Coverage, "1/2 categories")
        self.assertEqual(str(window._items["opaque-width"]), "opaque-width")
        window.txtSearch.Text = "width"
        window.on_search_changed(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), ["opaque-width"])
        window.txtSearch.Text = ""
        window.cboCoverage = types.SimpleNamespace(SelectedIndex=1)
        window.on_filter_changed(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), ["opaque-flag"])

    def test_types_mode_hides_instance_only_including_restored_selections(self):
        window = self.window("Types Mode", ["Comments", "Mark"])
        self.assertEqual(self.names(window.lstAvailable.Items), ["Width"])
        self.assertEqual(self.names(window.lstSelected.Items), ["Mark"])
        self.assertIn("Instance-only parameters are hidden", window.lblMode.Text)
        window.on_continue(None, None)
        self.assertEqual(window.selected_parameters, ["Mark"])
        self.assertEqual(window.action, "next")

    def test_types_mode_common_filter_counts_type_availability_not_instance_coverage(self):
        self.usage = {"Width": {
            "name": "Width", "isType": True, "isInstance": True,
            "categoryCount": 2, "totalCategories": 2,
            "categoryIds": [1, 2], "categoryNames": ["Doors", "Windows"],
            "typeCategoryIds": [1], "instanceCategoryIds": [2],
        }}
        window = self.window("Types Mode")
        self.assertEqual(window._items["Width"].Coverage, "1/2 categories")
        window.cboCoverage = types.SimpleNamespace(SelectedIndex=1)
        window.on_filter_changed(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), [])
        self.assertEqual(self.usage["Width"]["categoryCount"], 2)

    def test_types_mode_filters_cannot_restore_hidden_parameters(self):
        window = self.window("Types Mode")
        window.cboAvailability.SelectedItem.Content = "Instance parameters"
        window.on_filter_changed(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), ["Mark"])
        window.txtSearch.Text = "comments"
        window.on_search_changed(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), [])

    def test_search_and_filters_preserve_selected_item_objects(self):
        window = self.window()
        window.lstAvailable.SelectedItems.Add(window._items["Mark"])
        window.txtSearch.Text = "ma"
        window.on_search_changed(None, None)
        self.assertEqual(window.lstAvailable.Items, [window._items["Mark"]])
        self.assertEqual(window.lstAvailable.SelectedItems, [window._items["Mark"]])
        window.txtSearch.Text = ""
        window.cboAvailability.SelectedItem.Content = "Type parameters"
        window.on_filter_changed(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), ["Mark", "Width"])

    def typed_window(self, selected=None):
        self.usage = {
            "width": {"name": "Width", "dataType": "Length", "isType": True},
            "height": {"name": "Height", "dataType": "Length", "isType": True},
            "comments": {"name": "Comments", "dataType": "Text", "isInstance": True},
            "mark": {"name": "Mark", "dataType": "Text", "isInstance": True},
            "enabled": {"name": "Enabled", "dataType": "Yes/No", "isInstance": True},
        }
        return self.window(selected=selected)

    def sort_available(self, window, key):
        window.on_sort_available(types.SimpleNamespace(Tag=key), None)

    def filter_data_type(self, window, data_type):
        window.on_filter_data_type(types.SimpleNamespace(Tag=data_type), None)

    def test_sorting_by_data_type_then_name_preserves_bulk_highlights_and_right_panel(self):
        window = self.typed_window(selected=["mark", "height"])
        window.lstSelected.SelectedItems.Add(window._items["height"])
        window.lstAvailable.SelectedItems.extend(
            [window._items["width"], window._items["comments"]])
        self.sort_available(window, "dataType")
        self.assertEqual(self.names(window.lstAvailable.Items), ["width", "comments", "enabled"])
        self.assertEqual(set(self.names(window.lstAvailable.SelectedItems)), {"width", "comments"})
        self.assertEqual(self.names(window.lstSelected.Items), ["mark", "height"])
        self.assertEqual(self.names(window.lstSelected.SelectedItems), ["height"])
        self.sort_available(window, "name")
        self.assertEqual(self.names(window.lstAvailable.Items), ["comments", "enabled", "width"])
        self.assertEqual(set(self.names(window.lstAvailable.SelectedItems)), {"width", "comments"})

    def test_add_includes_hidden_highlights_in_sort_order_and_retains_data_type_filter(self):
        window = self.typed_window(selected=["mark"])
        window.lstAvailable.SelectedItems.extend(
            [window._items["comments"], window._items["width"], window._items["height"]])
        self.filter_data_type(window, "Length")
        self.assertIn("3 highlighted (1 hidden)", window.lblAvailableStatus.Text)
        self.sort_available(window, "dataType")
        window.on_add(None, None)
        self.assertEqual(self.names(window.lstSelected.Items), ["mark", "height", "width", "comments"])
        self.assertEqual(self.names(window.lstSelected.SelectedItems), ["height", "width", "comments"])
        self.assertEqual(window._highlighted_available, set())
        self.assertEqual(window.lstAvailable.SelectedItems, [])
        self.assertEqual(window.lstAvailable.Items, [])
        self.assertEqual(window._sort_by, "dataType")
        self.assertEqual(window._data_type_filter, "Length")
        self.assertEqual(window.pnlDataTypeFilter.Visibility, "Visible")
        window.on_clear_data_type_filter(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), ["enabled"])
        self.assertEqual(window.lstAvailable.SelectedItems, [])

    def test_successive_adds_keep_filter_and_append_in_user_chosen_order(self):
        window = self.typed_window(selected=["mark"])
        self.filter_data_type(window, "Length")
        for key in ("width", "height"):
            window.lstAvailable.SelectedItems.Add(window._items[key])
            window.on_add(None, None)
            self.assertEqual(window._data_type_filter, "Length")
            self.assertEqual(window.pnlDataTypeFilter.Visibility, "Visible")
            self.assertEqual(window.lstAvailable.SelectedItems, [])
            self.assertEqual(window._highlighted_available, set())
        self.assertEqual(self.names(window.lstSelected.Items), ["mark", "width", "height"])
        self.assertEqual(window.lstAvailable.Items, [])

    def test_filtering_restores_hidden_highlights_and_respects_visible_deselection(self):
        window = self.typed_window()
        window.lstAvailable.SelectedItems.extend(
            [window._items["width"], window._items["comments"]])
        self.filter_data_type(window, "Length")
        self.assertEqual(self.names(window.lstAvailable.SelectedItems), ["width"])
        window.lstAvailable.SelectedItems.Clear()
        window.on_available_selection_changed(None, None)
        self.assertEqual(window._highlighted_available, {"comments"})
        self.filter_data_type(window, None)
        self.assertEqual(self.names(window.lstAvailable.SelectedItems), ["comments"])
        window.txtSearch.Text = "not found"
        window.on_search_changed(None, None)
        self.assertIn("1 highlighted (1 hidden)", window.lblAvailableStatus.Text)
        window.on_add(None, None)
        self.assertEqual(self.names(window.lstSelected.Items), ["comments"])
        self.assertEqual(window.txtSearch.Text, "not found")

    def test_refresh_selection_events_do_not_discard_hidden_highlights(self):
        window = self.typed_window()

        class SelectionCollection(Collection):
            def Clear(self):
                super(SelectionCollection, self).Clear()
                window.on_available_selection_changed(None, None)

            def Add(self, item):
                super(SelectionCollection, self).Add(item)
                window.on_available_selection_changed(None, None)

        window.lstAvailable.SelectedItems = SelectionCollection()
        window.lstAvailable.SelectedItems.Add(window._items["width"])
        window.lstAvailable.SelectedItems.Add(window._items["comments"])
        self.filter_data_type(window, "Text")
        self.assertEqual(window._highlighted_available, {"width", "comments"})
        self.assertEqual(self.names(window.lstAvailable.SelectedItems), ["comments"])
        self.filter_data_type(window, None)
        self.assertEqual(set(self.names(window.lstAvailable.SelectedItems)), {"width", "comments"})
        window.on_add(None, None)
        self.assertEqual(window._highlighted_available, set())
        self.assertEqual(window.lstAvailable.SelectedItems, [])

    def test_disabling_optional_fields_discards_highlights_for_unavailable_fields(self):
        self.usage["derived:internal_0"] = {
            "name": "Internal X", "dataType": "Length", "isInstance": True,
            "derivedGroup": "coordinates",
        }
        window = self.window()
        window.chkCoordinates = types.SimpleNamespace(IsChecked=True)
        window.chkUsefulFields = types.SimpleNamespace(IsChecked=False)
        window.chkFalsePositives = types.SimpleNamespace(IsChecked=False)
        window.on_field_options_changed(None, None)
        window.lstAvailable.SelectedItems.Add(window._items["derived:internal_0"])
        self.filter_data_type(window, "Text")
        window.chkCoordinates.IsChecked = False
        window.on_field_options_changed(None, None)
        self.assertEqual(window._highlighted_available, set())
        self.assertEqual(window._data_type_filter, "Text")
        window.on_add(None, None)
        self.assertEqual(window.lstSelected.Items, [])
        self.assertEqual(window._data_type_filter, "Text")

    def test_usage_and_coverage_filters_also_preserve_hidden_highlights(self):
        window = self.typed_window()
        window.lstAvailable.SelectedItems.Add(window._items["comments"])
        window.cboAvailability.SelectedItem.Content = "Type parameters"
        window.on_filter_changed(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), ["height", "width"])
        self.assertEqual(window._highlighted_available, {"comments"})
        window.cboAvailability.SelectedItem.Content = "All parameters"
        window._usage_map["comments"].update(categoryCount=1, totalCategories=2)
        window.cboCoverage.SelectedIndex = 1
        window.on_filter_changed(None, None)
        self.assertNotIn("comments", self.names(window.lstAvailable.Items))
        window.on_add(None, None)
        self.assertEqual(self.names(window.lstSelected.Items), ["comments"])
        self.assertEqual(window.cboCoverage.SelectedIndex, 1)

    def test_remove_does_not_restore_highlights_or_reset_sort_and_filter(self):
        window = self.typed_window()
        self.sort_available(window, "dataType")
        self.filter_data_type(window, "Length")
        window.lstAvailable.SelectedItems.Add(window._items["width"])
        window.on_add(None, None)
        window.on_remove(None, None)
        self.assertEqual(self.names(window.lstAvailable.Items), ["height", "width"])
        self.assertEqual(window.lstAvailable.SelectedItems, [])
        self.assertEqual(window._highlighted_available, set())
        self.assertEqual(window._sort_by, "dataType")
        self.assertEqual(window._data_type_filter, "Length")

    def test_filter_banner_stays_visible_for_empty_results_and_clear_keeps_other_settings(self):
        window = self.typed_window(selected=["mark"])
        self.assertEqual(window.pnlDataTypeFilter.Visibility, "Collapsed")
        self.sort_available(window, "dataType")
        window.txtSearch.Text = "missing"
        window.cboAvailability.SelectedItem.Content = "Type parameters"
        window.cboCoverage.SelectedIndex = 1
        self.filter_data_type(window, "Length")
        self.assertEqual(window.lstAvailable.Items, [])
        self.assertEqual(window.pnlDataTypeFilter.Visibility, "Visible")
        self.assertEqual(window.lblDataTypeFilter.Text, "Data type filter: Length")
        window.on_clear_data_type_filter(None, None)
        self.assertIsNone(window._data_type_filter)
        self.assertEqual(window.pnlDataTypeFilter.Visibility, "Collapsed")
        self.assertEqual(window.lblDataTypeFilter.Text, "")
        self.assertEqual(window.txtSearch.Text, "missing")
        self.assertEqual(window.cboAvailability.SelectedItem.Content, "Type parameters")
        self.assertEqual(window.cboCoverage.SelectedIndex, 1)
        self.assertEqual(window._sort_by, "dataType")
        self.assertEqual(self.names(window.lstSelected.Items), ["mark"])

    def test_clear_filter_restores_hidden_highlights_without_adding_them(self):
        window = self.typed_window()
        window.lstAvailable.SelectedItems.Add(window._items["width"])
        self.filter_data_type(window, "Text")
        window.on_clear_data_type_filter(None, None)
        self.assertEqual(self.names(window.lstAvailable.SelectedItems), ["width"])
        self.assertEqual(window.lstSelected.Items, [])

    def test_successful_add_retains_search_usage_and_coverage(self):
        window = self.typed_window()
        self.sort_available(window, "dataType")
        self.filter_data_type(window, "Length")
        window.txtSearch.Text = "width"
        window.cboAvailability.SelectedItem.Content = "Type parameters"
        window.cboCoverage.SelectedIndex = 1
        window.on_search_changed(None, None)
        window.lstAvailable.SelectedItems.Add(window._items["width"])
        window.on_add(None, None)
        self.assertEqual(window._data_type_filter, "Length")
        self.assertEqual(window.txtSearch.Text, "width")
        self.assertEqual(window.cboAvailability.SelectedItem.Content, "Type parameters")
        self.assertEqual(window.cboCoverage.SelectedIndex, 1)
        self.assertEqual(window._sort_by, "dataType")
        self.assertEqual(self.names(window.lstSelected.Items), ["width"])

    def test_filter_banner_clear_button_is_wired_above_available_list(self):
        root = ET.parse(os.path.join(ROOT, "ui", "wizard.xaml")).getroot()
        wpf = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        x = "{http://schemas.microsoft.com/winfx/2006/xaml}"
        banner = next(node for node in root.iter(wpf + "Border")
                      if node.get(x + "Name") == "pnlDataTypeFilter")
        self.assertEqual(banner.get("Visibility"), "Collapsed")
        self.assertEqual(banner.get("DockPanel.Dock"), "Top")
        button = next(banner.iter(wpf + "Button"))
        self.assertEqual(button.get("Click"), "on_clear_data_type_filter")

    def test_field_option_refresh_keeps_browsing_settings_and_remaining_highlights(self):
        window = self.typed_window()
        self.sort_available(window, "dataType")
        self.filter_data_type(window, "Text")
        window.lstAvailable.SelectedItems.Add(window._items["comments"])
        window.chkCoordinates = types.SimpleNamespace(IsChecked=False)
        window.chkUsefulFields = types.SimpleNamespace(IsChecked=False)
        window.chkFalsePositives = types.SimpleNamespace(IsChecked=False)
        window.on_field_options_changed(None, None)
        self.assertEqual(window._sort_by, "dataType")
        self.assertEqual(window._data_type_filter, "Text")
        self.assertEqual(self.names(window.lstAvailable.Items), ["comments", "mark"])
        self.assertEqual(self.names(window.lstAvailable.SelectedItems), ["comments"])

    def test_right_click_does_not_replace_bulk_selection(self):
        window = self.typed_window()
        window.lstAvailable.SelectedItems.extend(
            [window._items["width"], window._items["comments"]])
        args = types.SimpleNamespace(Handled=False)
        window.on_available_right_click(window.lstAvailable, args)
        self.assertTrue(args.Handled)
        self.assertEqual(self.names(window.lstAvailable.SelectedItems), ["width", "comments"])

    def test_context_menu_lists_unique_data_types_and_current_choices_even_when_empty(self):
        window = self.typed_window()
        self.sort_available(window, "dataType")
        self.filter_data_type(window, "Length")
        window._items = {}
        menu = types.SimpleNamespace(Items=Collection())
        sender = types.SimpleNamespace(ContextMenu=menu)

        class MenuItem(object):
            def __init__(self):
                self.Items = Collection()
                self.Click = Event()

        controls = types.ModuleType("System.Windows.Controls")
        controls.MenuItem = MenuItem
        with patch.dict(sys.modules, {"System.Windows.Controls": controls}):
            window.on_available_menu_opening(sender, None)
        self.assertEqual([item.Header for item in menu.Items], ["Sort by", "Data type"])
        self.assertEqual([item.IsChecked for item in menu.Items[0].Items], [False, True])
        self.assertEqual([item.Header for item in menu.Items[1].Items], ["All data types", "Length"])
        self.assertEqual([item.IsChecked for item in menu.Items[1].Items], [False, True])
        window = self.typed_window()
        with patch.dict(sys.modules, {"System.Windows.Controls": controls}):
            window.on_available_menu_opening(sender, None)
        self.assertEqual([item.Header for item in menu.Items[1].Items],
                         ["All data types", "Length", "Text", "Yes/No"])

    def test_context_menu_is_only_on_available_list_and_handlers_are_wired(self):
        root = ET.parse(os.path.join(ROOT, "ui", "wizard.xaml")).getroot()
        wpf = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        x = "{http://schemas.microsoft.com/winfx/2006/xaml}"
        available = next(node for node in root.iter(wpf + "ListBox")
                         if node.get(x + "Name") == "lstAvailable")
        selected = next(node for node in root.iter(wpf + "ListBox")
                        if node.get(x + "Name") == "lstSelected")
        self.assertEqual(available.get("SelectionMode"), "Extended")
        for event, handler in (
            ("SelectionChanged", "on_available_selection_changed"),
            ("PreviewMouseRightButtonDown", "on_available_right_click"),
            ("ContextMenuOpening", "on_available_menu_opening"),
        ):
            self.assertEqual(available.get(event), handler)
        self.assertEqual(len(list(available.iter(wpf + "ContextMenu"))), 1)
        self.assertEqual(len(list(selected.iter(wpf + "ContextMenu"))), 0)

    def test_context_menu_uses_native_templates_instead_of_pyrevit_header_only_style(self):
        root = ET.parse(os.path.join(ROOT, "ui", "wizard.xaml")).getroot()
        wpf = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        menu = next(root.iter(wpf + "ContextMenu"))
        self.assertEqual(menu.get("Style"), "{x:Null}")
        resources = menu.find(wpf + "ContextMenu.Resources")
        style = resources.find(wpf + "Style")
        self.assertEqual(style.get("TargetType"), "{x:Type MenuItem}")
        self.assertIsNone(style.get("BasedOn"))
        self.assertEqual(len(style), 0)

    def test_multi_add_remove_and_reorder_preserve_badges_and_names(self):
        window = self.window(selected=["Width"])
        window.lstAvailable.SelectedItems.extend(
            [window._items["Mark"], window._items["Comments"]]
        )
        window.on_add(None, None)
        self.assertEqual(self.names(window.lstSelected.Items), ["Width", "Comments", "Mark"])
        window.on_move_up(None, None)
        self.assertEqual(self.names(window.lstSelected.Items), ["Comments", "Mark", "Width"])
        window.on_move_down(None, None)
        self.assertEqual(self.names(window.lstSelected.Items), ["Width", "Comments", "Mark"])
        for item in window.lstSelected.Items:
            self.assertIs(item, window._items[str(item)])
        window.on_remove(None, None)
        self.assertEqual(self.names(window.lstSelected.Items), ["Width"])
        self.assertEqual(self.names(window.lstAvailable.Items), ["Comments", "Mark"])
        window.on_back(None, None)
        self.assertEqual(window.selected_parameters, ["Width"])
        self.assertEqual(window.action, "back")

    def test_empty_selection_does_not_continue(self):
        window = self.window("Types Mode", ["Comments"])
        window.on_continue(None, None)
        self.forms.alert.assert_called_once()
        self.assertEqual(window.action, "cancel")

    def test_action_arrows_share_geometry_and_preserve_buttons(self):
        root = ET.parse(os.path.join(ROOT, "ui", "wizard.xaml")).getroot()
        wpf = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        x = "{http://schemas.microsoft.com/winfx/2006/xaml}"
        style = next(node for node in root.iter(wpf + "Style")
                     if node.get(x + "Key") == "ActionArrowStyle")
        setters = {node.get("Property"): node.get("Value") for node in style}
        self.assertEqual(setters["Width"], "18")
        self.assertEqual(setters["Height"], "18")
        self.assertEqual(setters["Data"],
                         "M0,3.5 L11,3.5 L11,0 L18,5 L11,10 L11,6.5 L0,6.5 Z")
        self.assertIn("AncestorType=Button", setters["Fill"])
        expected = {
            "on_add": ("82", "Add", None),
            "on_remove": ("82", "Remove", "180"),
            "on_move_up": ("38", None, "-90"),
            "on_move_down": ("38", None, "90"),
        }
        for handler, (width, label, angle) in expected.items():
            button = next(node for node in root.iter(wpf + "Button")
                          if node.get("Click") == handler)
            self.assertEqual(button.get("Width"), width)
            self.assertEqual(button.get("Height"), "32")
            self.assertTrue(button.get("AutomationProperties.Name"))
            arrow = next(button.iter(wpf + "Path"))
            self.assertEqual(arrow.get("Style"), "{StaticResource ActionArrowStyle}")
            rotations = list(arrow.iter(wpf + "RotateTransform"))
            self.assertEqual([node.get("Angle") for node in rotations],
                             [] if angle is None else [angle])
            self.assertEqual([node.get("Text") for node in button.iter(wpf + "TextBlock")],
                             [] if label is None else [label])

    def test_both_lists_share_template_and_stretched_rows(self):
        root = ET.parse(os.path.join(ROOT, "ui", "wizard.xaml")).getroot()
        x = "{http://schemas.microsoft.com/winfx/2006/xaml}"
        wpf = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        lists = [node for node in root.iter(wpf + "ListBox")
                 if node.get(x + "Name") in ("lstAvailable", "lstSelected")]
        self.assertEqual(len(lists), 2)
        for node in lists:
            self.assertEqual(node.get("ItemTemplate"), "{StaticResource ParameterRowTemplate}")
            self.assertEqual(node.get("ItemContainerStyle"), "{StaticResource ParameterRowStyle}")
            self.assertEqual(node.get("ScrollViewer.HorizontalScrollBarVisibility"), "Disabled")

    def test_navigation_buttons_are_grouped_in_cancel_back_next_order(self):
        wpf = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        for filename in ("choice.xaml", "wizard.xaml"):
            root = ET.parse(os.path.join(ROOT, "ui", filename)).getroot()
            footer = next(node for node in root.iter(wpf + "StackPanel")
                          if any(child.get("Click") == "on_continue" for child in node))
            self.assertEqual(footer.get("Orientation"), "Horizontal")
            self.assertEqual(footer.get("HorizontalAlignment"), "Right")
            self.assertEqual([child.get("Click") for child in footer],
                             ["on_cancel", "on_back", "on_continue"])

    def test_forward_buttons_rotate_back_arrow_and_keep_dynamic_labels(self):
        wpf = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        for filename, label in (("choice.xaml", "Next"), ("wizard.xaml", "Open Grid")):
            root = ET.parse(os.path.join(ROOT, "ui", filename)).getroot()
            back = next(node for node in root.iter(wpf + "Button")
                        if node.get("Click") == "on_back")
            forward = next(node for node in root.iter(wpf + "Button")
                           if node.get("Click") == "on_continue")
            self.assertEqual(forward.get("Content"), label)
            self.assertIn("Binding Content", forward.get("AutomationProperties.Name"))
            template = forward.find(wpf + "Button.ContentTemplate")
            self.assertIsNotNone(template)
            arrow = next(template.iter(wpf + "Path"))
            back_arrow = next(back.iter(wpf + "Path"))
            for attribute in ("Data", "Width", "Height", "Stretch", "Fill"):
                self.assertEqual(arrow.get(attribute), back_arrow.get(attribute))
            self.assertEqual(arrow.get("RenderTransformOrigin"), "0.5,0.5")
            self.assertEqual(next(arrow.iter(wpf + "RotateTransform")).get("Angle"), "180")
            self.assertEqual(next(template.iter(wpf + "TextBlock")).get("Text"), "{Binding}")


if __name__ == "__main__":
    unittest.main()
