"""Host-independent checks for sorting from grid group headers."""
import ast
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from test_value_editing import SCRIPT, TREE, load_functions


class Event:
    def __iadd__(self, handler):
        self.handler = handler
        return self


class MenuItem:
    def __init__(self):
        self.Click = Event()


class NetList(list):
    def Add(self, item):
        self.append(item)


class ContextMenu:
    def __init__(self):
        self.Items = NetList()


class GroupSortMenuTests(unittest.TestCase):
    def setUp(self):
        self.namespace = {
            "_sort_supports_reorder": lambda manager: True,
            "_sort_group_parameters": lambda parameters: (
                {parameter.group: [] for parameter in parameters}, {}),
            "_sort_apply_parameter_sort": Mock(
                return_value=(True, "ok", ["Dimensions"], 3)),
            "doc": object(),
        }
        self.functions = load_functions(
            ["on_group_header_right_click", "on_group_sort"], self.namespace)
        self.window = SimpleNamespace(
            fm=object(), _set_status=Mock(), on_group_sort=Mock(),
            _selected_parameter_item=lambda: SimpleNamespace(Name="Width"),
            _reload_parameter_items=Mock())
        controls = ModuleType("System.Windows.Controls")
        controls.ContextMenu = ContextMenu
        controls.MenuItem = MenuItem
        self.modules = patch.dict("sys.modules", {
            "System": ModuleType("System"),
            "System.Windows": ModuleType("System.Windows"),
            "System.Windows.Controls": controls,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_header_menu_targets_clicked_group_not_selected_rows(self):
        header = SimpleNamespace(DataContext=SimpleNamespace(Items=[
            SimpleNamespace(Param=SimpleNamespace(group="dimensions"))]))
        args = SimpleNamespace(Handled=False)
        self.functions.on_group_header_right_click(self.window, header, args)
        self.assertTrue(args.Handled)
        self.assertTrue(header.ContextMenu.IsOpen)
        self.assertIs(header.ContextMenu.PlacementTarget, header)
        self.assertEqual(
            [item.Tag for item in header.ContextMenu.Items],
            [({"dimensions"}, mode, descending)
             for mode in ("Name Only", "Type then Instance")
             for descending in (False, True)])
        for item in header.ContextMenu.Items:
            self.assertIs(item.Click.handler, self.window.on_group_sort)

    def test_unsupported_revit_or_empty_group_shows_error(self):
        for supported, items in ((False, [object()]), (True, [])):
            with self.subTest(supported=supported):
                self.namespace["_sort_supports_reorder"] = lambda manager: supported
                header = SimpleNamespace(DataContext=SimpleNamespace(Items=items))
                self.functions.on_group_header_right_click(
                    self.window, header, SimpleNamespace())
                self.assertFalse(hasattr(header, "ContextMenu"))
                self.assertEqual(self.window._set_status.call_args.args[1], "error")

    def test_action_only_stages_sort_and_refreshes_preview(self):
        self.window._pending_group_sorts = {}
        self.window._pending_group_orders = {"dimensions": [9, 2]}
        self.window._has_pending_order = lambda: bool(self.window._pending_group_sorts)
        self.window._refresh_sort_preview = Mock()
        for mode in ("Name Only", "Type then Instance"):
            for descending in (False, True):
                sender = SimpleNamespace(Tag=({"dimensions"}, mode, descending))
                self.functions.on_group_sort(self.window, sender, None)
                self.assertEqual(self.window._pending_group_sorts,
                                 {"dimensions": (mode, descending)})
                self.window._refresh_sort_preview.assert_called_with()
        self.namespace["_sort_apply_parameter_sort"].assert_not_called()
        self.assertEqual(self.window._pending_group_orders, {})

    def test_real_sort_includes_hidden_group_members_and_preserves_other_groups(self):
        path = SCRIPT.parents[3] / "lib" / "sort_param_utils.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "build_reordered_list")
        namespace = {
            "param_name": lambda parameter: parameter.name,
            "get_group_info": lambda parameter: (parameter.group, parameter.group),
        }

        def group_parameters(parameters):
            grouped = {}
            for parameter in parameters:
                grouped.setdefault(parameter.group, []).append(parameter)
            return grouped, {}

        namespace["group_parameters"] = group_parameters
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
             namespace)
        parameters = [
            SimpleNamespace(name=name, group=group, IsInstance=instance)
            for name, group, instance in (
                ("Z", "dimensions", False), ("Other Z", "other", False),
                ("A", "dimensions", True), ("B", "dimensions", False),
                ("Other A", "other", False))]
        for mode, descending, expected in (
                ("Name Only", False, ["A", "B", "Z"]),
                ("Name Only", True, ["Z", "B", "A"]),
                ("Type then Instance", False, ["B", "Z", "A"]),
                ("Type then Instance", True, ["Z", "B", "A"])):
            with self.subTest(mode=mode, descending=descending):
                groups, reordered = namespace["build_reordered_list"](
                    parameters, {"dimensions"}, mode, descending)
                self.assertEqual([p.name for p in groups["dimensions"]], expected)
                self.assertIs(reordered[1], parameters[1])
                self.assertIs(reordered[4], parameters[4])
                self.assertEqual(len(reordered), len(parameters))

    def test_xaml_replaces_sort_tab_and_old_controls_are_not_referenced(self):
        root = ET.parse(str(SCRIPT.with_name("ParameterEditor.xaml"))).getroot()
        headers = [element for element in root.iter()
                   if element.get("PreviewMouseRightButtonUp")
                   == "on_group_header_right_click"]
        self.assertEqual(len(headers), 1)
        self.assertTrue(headers[0].tag.endswith("}ToggleButton"))
        self.assertFalse(any(element.get("Header") == "Sort Parameters"
                             for element in root.iter()))
        obsolete = {
            "_populate_sort_groups", "sortGroupPanel", "_sort_group_checkboxes",
            "rbSortNameOnly", "rbSortTypeThenInstance", "rbSortDescending",
            "rbSortAscending",
        }
        self.assertFalse(any(isinstance(node, ast.Attribute)
                             and node.attr in obsolete for node in ast.walk(TREE)))


if __name__ == "__main__":
    unittest.main()
