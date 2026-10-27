"""Host-independent tests for import tab defaults."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from test_value_editing import load_functions


BUNDLE = Path(__file__).resolve().parents[1]


class ImportDefaultsTests(unittest.TestCase):
    def test_import_tab_label(self):
        root = ET.parse(str(BUNDLE / "ParameterEditor.xaml")).getroot()
        name_key = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
        tab = next(node for node in root.iter() if node.get(name_key) == "tabImport")
        self.assertEqual(tab.get("Header"), "Import")

    def test_parameters_start_unchecked_and_remain_selectable(self):
        path = BUNDLE / "family_param_transfer.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        item_class = next(node for node in tree.body
                          if isinstance(node, ast.ClassDef) and node.name == "SourceParamItem")
        namespace = {
            "_NotifyBase": type("NotifyBase", (object,), {"_notify": Mock()}),
            "_group_label": lambda parameter: "Dimensions",
            "_is_likely_nontransferable": lambda parameter: parameter.nontransferable,
        }
        exec(compile(ast.Module(body=[item_class], type_ignores=[]), str(path), "exec"),
             namespace)
        functions = load_functions(
            ["on_import_params_select_all", "on_import_params_select_none"], {})
        items = []
        for nontransferable in (False, True):
            parameter = SimpleNamespace(
                Definition=SimpleNamespace(Name="Width"), IsInstance=False,
                Formula=None, IsShared=False, GUID=None,
                nontransferable=nontransferable)
            item = namespace["SourceParamItem"](parameter)
            self.assertFalse(item.IsSelected)
            items.append(item)
        window = SimpleNamespace(lstImportParams=SimpleNamespace(ItemsSource=items))
        functions.on_import_params_select_all(window, None, None)
        self.assertTrue(all(item.IsSelected for item in items))
        functions.on_import_params_select_none(window, None, None)
        self.assertTrue(all(not item.IsSelected for item in items))


if __name__ == "__main__":
    unittest.main()
