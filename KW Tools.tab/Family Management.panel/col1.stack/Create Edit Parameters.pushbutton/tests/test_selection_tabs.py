"""Host-independent tests for selection-driven editor tabs."""
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from test_value_editing import SCRIPT, load_functions


class SelectionTabTests(unittest.TestCase):
    def setUp(self):
        windows = ModuleType("System.Windows")
        windows.Visibility = SimpleNamespace(Visible="visible", Collapsed="collapsed")
        media = ModuleType("System.Windows.Media")
        media.SolidColorBrush = lambda color: color
        media.Color = SimpleNamespace(FromRgb=lambda *rgb: rgb)
        self.modules = patch.dict("sys.modules", {
            "System": ModuleType("System"),
            "System.Windows": windows,
            "System.Windows.Media": media,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.update = load_functions(["_update_batch_panel"], {})._update_batch_panel

    def make_window(self, count, active="single"):
        items = [
            SimpleNamespace(InstanceTypeLabel="Type", GroupLabel="Data")
            for _ in range(count)
        ]
        window = SimpleNamespace(
            _selected_parameter_items=lambda: items,
            _set_batch_group_combo=Mock(),
            tabEditExisting=SimpleNamespace(
                Visibility="visible", IsSelected=active == "single"),
            tabBatchEdit=SimpleNamespace(
                Visibility="collapsed", IsSelected=active == "batch"),
        )
        for name in (
                "txtBatchSummary", "btnBatchToggle", "txtBatchToggleInfo",
                "btnBatchChangeGroup", "btnBatchRename", "btnBatchDuplicate",
                "btnBatchDelete"):
            setattr(window, name, SimpleNamespace())
        return window

    def test_multiple_selection_shows_and_selects_batch(self):
        for count in (2, 5):
            with self.subTest(count=count):
                window = self.make_window(count)
                self.update(window)
                self.assertEqual(window.tabEditExisting.Visibility, "collapsed")
                self.assertEqual(window.tabBatchEdit.Visibility, "visible")
                self.assertTrue(window.tabBatchEdit.IsSelected)
                self.assertTrue(window.btnBatchRename.IsEnabled)
                self.assertEqual(
                    window.txtBatchSummary.Text,
                    "{} parameter(s) selected.".format(count))

    def test_single_or_empty_selection_returns_to_single_editor(self):
        for count in (0, 1):
            with self.subTest(count=count):
                window = self.make_window(count, active="batch")
                self.update(window)
                self.assertEqual(window.tabEditExisting.Visibility, "visible")
                self.assertEqual(window.tabBatchEdit.Visibility, "collapsed")
                self.assertTrue(window.tabEditExisting.IsSelected)
                self.assertEqual(window.btnBatchRename.IsEnabled, count == 1)

    def test_other_active_tabs_are_not_replaced(self):
        for count in (0, 1, 3):
            with self.subTest(count=count):
                window = self.make_window(count, active="other")
                self.update(window)
                self.assertFalse(window.tabEditExisting.IsSelected)
                self.assertFalse(window.tabBatchEdit.IsSelected)

    def test_mixed_scope_keeps_batch_toggle_disabled(self):
        window = self.make_window(2)
        window._selected_parameter_items()[0].InstanceTypeLabel = "Instance"
        self.update(window)
        self.assertEqual(window.tabBatchEdit.Visibility, "visible")
        self.assertFalse(window.btnBatchToggle.IsEnabled)

    def test_initial_tab_selection_does_not_access_unloaded_controls(self):
        handler = load_functions(
            ["on_tab_selection_changed"], {}).on_tab_selection_changed
        window = SimpleNamespace(_ui_ready=False, _update_batch_panel=Mock())
        handler(window, None, SimpleNamespace())
        window._update_batch_panel.assert_not_called()

    def test_tab_selection_refreshes_after_initialization(self):
        handler = load_functions(
            ["on_tab_selection_changed"], {}).on_tab_selection_changed
        controls = ModuleType("System.Windows.Controls")
        controls.TabItem = type("TabItem", (), {})
        window = SimpleNamespace(
            _ui_ready=True, _update_batch_panel=Mock(),
            tabImport=SimpleNamespace(IsSelected=False))
        with patch.dict("sys.modules", {"System.Windows.Controls": controls}):
            handler(window, None, SimpleNamespace(AddedItems=[controls.TabItem()]))
        window._update_batch_panel.assert_called_once_with()

    def test_xaml_names_tabs_and_hides_batch_initially(self):
        root = ET.parse(str(SCRIPT.with_name("ParameterEditor.xaml"))).getroot()
        name_key = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
        tabs = {
            element.get(name_key): element
            for element in root.iter()
            if element.tag.endswith("}TabItem")
        }
        self.assertIn("tabEditExisting", tabs)
        self.assertEqual(tabs["tabEditExisting"].get("IsSelected"), "True")
        self.assertEqual(tabs["tabBatchEdit"].get("Visibility"), "Collapsed")

    def test_batch_and_single_edit_share_leftmost_visible_position(self):
        root = ET.parse(str(SCRIPT.with_name("ParameterEditor.xaml"))).getroot()
        namespace = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
        name_key = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
        editor = next(
            element for element in root.iter(namespace + "TabControl")
            if element.get("SelectionChanged") == "on_tab_selection_changed"
        )
        tabs = list(editor)
        self.assertEqual(
            [tab.get(name_key) for tab in tabs[:2]],
            ["tabBatchEdit", "tabEditExisting"])
        for hidden in ("tabEditExisting", "tabBatchEdit"):
            visible = [tab for tab in tabs if tab.get(name_key) != hidden]
            self.assertIn(
                visible[0].get(name_key), ("tabBatchEdit", "tabEditExisting"))


if __name__ == "__main__":
    unittest.main()
