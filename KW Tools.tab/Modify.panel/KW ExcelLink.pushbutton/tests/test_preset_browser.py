"""Preset tree grouping, filtering and selection without WPF."""
import importlib.util
import os
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TreeItem(object):
    def __init__(self):
        self.Items = Collection()
        self.Tag = None


class Collection(list):
    def Add(self, item):
        self.append(item)

    def Clear(self):
        self.clear()


class PresetBrowserTests(unittest.TestCase):
    def setUp(self):
        pyrevit = types.ModuleType("pyrevit")
        pyrevit.forms = types.SimpleNamespace(WPFWindow=object)
        spec = importlib.util.spec_from_file_location(
            "tested_preset_browser", os.path.join(ROOT, "ui", "preset_browser.py")
        )
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"pyrevit": pyrevit}):
            spec.loader.exec_module(self.module)
        self.items = [
            {"source": "enterprise", "name": "Door audit",
             "relativePath": os.path.join("Doors", "Checks", "Audit.json")},
            {"source": "enterprise", "name": "Renumber",
             "relativePath": os.path.join("Renumbering", "Doors.json")},
            {"source": "user", "name": "Door audit",
             "relativePath": os.path.join("Doors", "Audit.json")},
            {"source": "user", "name": "Root preset", "relativePath": "Root.json"},
        ]

    def window(self):
        window = self.module.PresetBrowserWindow.__new__(self.module.PresetBrowserWindow)
        window._items = self.items
        window.txtSearch = types.SimpleNamespace(Text="")
        window.treePresets = types.SimpleNamespace(Items=Collection(), SelectedItem=None)
        window.btnSelect = types.SimpleNamespace(IsEnabled=False)
        window.lblSelected = types.SimpleNamespace(Text="")
        window.Close = Mock()
        controls = types.ModuleType("System.Windows.Controls")
        controls.TreeViewItem = TreeItem
        patcher = patch.dict(sys.modules, {"System.Windows.Controls": controls})
        patcher.start()
        self.addCleanup(patcher.stop)
        return window

    def test_tree_has_enterprise_and_user_roots_with_nested_subfolders(self):
        roots = self.module.library_tree(self.items)
        self.assertEqual([node["label"] for node in roots], ["Enterprise", "User"])
        checks = roots[0]["children"][0]["children"][0]
        self.assertEqual(checks["label"], "Checks")
        self.assertIs(checks["children"][0]["item"], self.items[0])
        self.assertIsNone(checks["item"])

    def test_search_matches_folder_paths_names_and_library_across_both_roots(self):
        roots = self.module.library_tree(self.items, "doors")
        self.assertEqual(len(roots[0]["children"]), 2)
        self.assertEqual(len(roots[1]["children"]), 1)
        roots = self.module.library_tree(self.items, "user")
        self.assertEqual(roots[0]["children"], [])
        self.assertEqual(len(roots[1]["children"]), 2)
        roots = self.module.library_tree(self.items, "renumber")
        self.assertEqual(roots[1]["children"], [])
        self.assertEqual(roots[0]["children"][0]["label"], "Renumbering")

    def test_only_preset_leaves_can_be_loaded_and_search_expands_folders(self):
        window = self.window()
        window._refresh()
        root = window.treePresets.Items[0]
        self.assertTrue(root.IsExpanded)
        folder = root.Items[0]
        self.assertFalse(folder.IsExpanded)
        window.treePresets.SelectedItem = folder
        window.on_selection_changed(None, None)
        window.on_select(None, None)
        self.assertFalse(window.btnSelect.IsEnabled)
        window.Close.assert_not_called()
        leaf = folder.Items[0].Items[0]
        window.treePresets.SelectedItem = leaf
        window.on_selection_changed(None, None)
        self.assertTrue(window.btnSelect.IsEnabled)
        window.on_select(None, None)
        self.assertIs(window.selected, self.items[0])
        window.Close.assert_called_once()
        window.txtSearch.Text = "audit"
        window._refresh()
        self.assertTrue(window.treePresets.Items[0].Items[0].IsExpanded)

    def test_xaml_wires_search_selection_and_buttons(self):
        tree = ET.parse(os.path.join(ROOT, "ui", "preset_browser.xaml"))
        attributes = [node.attrib for node in tree.iter()]
        self.assertTrue(any(node.get("TextChanged") == "on_search_changed" for node in attributes))
        self.assertTrue(any(node.get("SelectedItemChanged") == "on_selection_changed" for node in attributes))
        self.assertTrue(any(node.get("Click") == "on_select" for node in attributes))


if __name__ == "__main__":
    unittest.main()
