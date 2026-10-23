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
        self.txtSearch = types.SimpleNamespace(Text="")
        self.cboAvailability = types.SimpleNamespace(
            SelectionChanged=Event(),
            SelectedItem=types.SimpleNamespace(Content="All parameters"),
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

    def window(self, mode="Instances Mode", selected=None):
        return self.module.ParameterWizardWindow("Doors", self.usage, mode, selected)

    def names(self, collection):
        return [str(item) for item in collection]

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


if __name__ == "__main__":
    unittest.main()
