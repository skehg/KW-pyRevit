"""Run with IronPython 2.7 on Windows to exercise real grouped WPF moves.

    ipy.exe -B test_wpf_ordering.py

Uses the editor's actual methods with an in-memory family manager, not a Revit
document. CPython discovery skips these tests because it cannot load WPF.
"""
import ast
import io
import os
import time
import textwrap
import unittest

try:
    import clr
except ImportError:
    raise unittest.SkipTest("Requires IronPython and Windows WPF")

clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from System import Object
from System.Collections.Generic import List
from System.Collections.ObjectModel import ObservableCollection
from System.Windows import Size, Rect
from System.Windows.Controls import DataGrid, TextBox, ComboBox, CheckBox
from System.Windows.Data import ListCollectionView, PropertyGroupDescription


SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "script.py")


class State(object):
    def __init__(self, **values):
        self.__dict__.update(values)


class Parameter(object):
    def __init__(self, identifier, name, group):
        self.Id = identifier
        self.Name = name
        self.group = group
        self.Definition = self
        self.IsInstance = False
        self.Formula = ""
        self.Value = "1"


class Manager(object):
    def __init__(self, parameters):
        self.parameters = parameters
        self.CurrentType = object()
        self.reorders = []
        self.commits = []

    def ReorderParameters(self, parameters):
        self.parameters = list(parameters)
        self.reorders.append([p.Id for p in parameters])

    def MakeInstance(self, parameter):
        parameter.IsInstance = True

    def MakeType(self, parameter):
        parameter.IsInstance = False

    def SetFormula(self, parameter, formula):
        parameter.Formula = formula or ""

    def AddParameter(self, name, group, data_type, instance):
        parameter = Parameter(max(p.Id for p in self.parameters) + 1, name, group)
        parameter.IsInstance = instance
        self.parameters.append(parameter)
        return parameter


def group_parameters(parameters):
    grouped = {}
    for parameter in parameters:
        grouped.setdefault(parameter.group, []).append(parameter)
    return grouped, {}


def load_editor(manager):
    with io.open(SCRIPT, encoding="utf-8-sig") as source:
        script_text = source.read()
        tree = ast.parse(script_text)
    names = {
        "_reload_parameter_items", "_apply_parameter_filter", "_refresh_group_filter_options",
        "_preview_parameter_order", "_refresh_sort_preview", "_has_pending_order",
        "_update_sort_buttons", "_update_reorder_buttons", "_reorder_move",
        "on_group_sort", "on_reset_sorting", "on_apply_sorting", "on_apply_value",
        "_save_parameter_value", "on_toggle_instance_type", "_perform_toggle_single",
        "on_apply_param_settings", "on_apply_formula", "on_clear_formula",
        "on_create_parameter", "on_param_selected",
    }
    methods = []
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ParameterEditorWindow":
            methods = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in names]
        elif ((isinstance(node, ast.ClassDef) and node.name == "ParameterItem")
              or (isinstance(node, ast.FunctionDef) and node.name == "_move_parameter_items")):
            nodes.append(node)

    class Transaction(object):
        def __init__(self, *args):
            self.name = args[-1]
            self.status = "started"

        def Start(self):
            pass

        def Commit(self):
            self.status = "committed"
            manager.commits.append(self.name)
            return self.status

        def Dispose(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, kind, value, traceback):
            if kind is None:
                self.Commit()
            return False

    def apply_value(fm, parameter, text):
        parameter.Value = text
        return True, ""

    namespace = {
        "List": List, "ObservableCollection": ObservableCollection,
        "ListCollectionView": ListCollectionView,
        "PropertyGroupDescription": PropertyGroupDescription,
        "_parameter_group_display_key": lambda label: label,
        "_get_family_parameters": lambda fm: list(fm.parameters),
        "_sort_get_current_order": lambda fm: list(fm.parameters),
        "_sort_supports_reorder": lambda fm: True,
        "_sort_group_parameters": group_parameters,
        "_param_name": lambda p: p.Name, "_group_label": lambda p: p.group,
        "_parameter_data_type_label": lambda p: "Text",
        "_safe_formula": lambda p: p.Formula,
        "_is_shared_parameter": lambda p: False,
        "_read_value_for_display": lambda current, p: p.Value,
        "_apply_initial_value": apply_value,
        "_build_type_to_instance_chain": lambda fm, name: ([[name]], {}),
        "_build_instance_to_type_chain": lambda fm, name: ([[name]], {}),
        "_get_group_type": lambda definition: definition.group,
        "_group_values_equal": lambda a, b: a == b,
        "_label_for_group": lambda group: group,
        "_group_add_parameter_candidates": lambda group: [group],
        "_force_family_recalc": lambda doc: None,
        "_force_family_type_cycle": lambda fm: None,
        "revit": State(Transaction=Transaction), "Transaction": Transaction,
        "TransactionStatus": State(Committed="committed"),
        "doc": object(), "FamilyParameter": Object, "ElementId": type("ElementId", (), {}),
    }
    sort_path = os.path.join(os.path.dirname(SCRIPT), "..", "..", "..", "lib", "sort_param_utils.py")
    with io.open(sort_path, encoding="utf-8-sig") as source:
        sort_text = source.read()
        sort_tree = ast.parse(sort_text)
    sort_node = next(n for n in sort_tree.body
                     if isinstance(n, ast.FunctionDef) and n.name == "build_reordered_list")
    namespace.update(
        group_parameters=group_parameters, param_name=lambda p: p.Name,
        get_group_info=lambda p: (p.group, p.group))
    def extract(node, text):
        lines = text.splitlines(True)
        start = node.lineno - 1
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = start + 1
        while end < len(lines):
            line = lines[end]
            if line.strip() and not line.lstrip().startswith("#"):
                if len(line) - len(line.lstrip()) <= indent:
                    break
            end += 1
        return textwrap.dedent("".join(lines[start:end]))

    eval(compile(extract(sort_node, sort_text), sort_path, "exec"), namespace)
    namespace["_sort_build_reordered_list"] = namespace["build_reordered_list"]
    code = "\n".join(extract(node, script_text) for node in nodes + methods)
    eval(compile(code, SCRIPT, "exec"), namespace)
    return type("EditorHarness", (object,), dict((n.name, namespace[n.name]) for n in methods))


class WpfOrderingTests(unittest.TestCase):
    def setUp(self):
        self.manager = Manager([
            Parameter(1, "A", "dimensions"), Parameter(2, "B", "dimensions"),
            Parameter(3, "C", "dimensions"), Parameter(4, "D", "other"),
            Parameter(5, "E", "other"), Parameter(6, "F", "other")])
        self.editor = load_editor(self.manager)()
        editor = self.editor
        editor.fm = self.manager
        editor._ui_ready = True
        editor._refreshing_order = False
        editor._pending_group_sorts = {}
        editor._pending_group_orders = {}
        editor._all_groups_label = "All Groups"
        editor._all_items = []
        editor.lstParameters = DataGrid()
        editor.lstParameters.AutoGenerateColumns = False
        editor.lstParameters.SelectionMode = __import__(
            "System.Windows.Controls", fromlist=["DataGridSelectionMode"]).DataGridSelectionMode.Extended
        editor.txtSearch = TextBox()
        editor.chkSearchFormula = CheckBox()
        editor.cmbGroupFilter = ComboBox()
        for name in ("btnApplySorting", "btnResetSorting", "btnReorderTop",
                     "btnReorderUp", "btnReorderDown", "btnReorderBottom"):
            setattr(editor, name, State(IsEnabled=False))
        editor._set_status = lambda message, tone: setattr(editor, "status", (message, tone))
        editor._set_editor_from_selected = lambda: None
        editor._update_batch_panel = lambda: None
        editor.popupSuggestions = State(IsOpen=False)
        editor._selected_parameter_items = lambda: list(editor.lstParameters.SelectedItems)
        editor._selected_parameter_item = lambda: editor.lstParameters.SelectedItem
        editor.lstParameters.SelectionChanged += editor.on_param_selected
        editor._reload_parameter_items()
        editor.lstParameters.Measure(Size(800, 600))
        editor.lstParameters.Arrange(Rect(0, 0, 800, 600))
        editor.lstParameters.UpdateLayout()

    def select(self, *identifiers):
        self.editor.lstParameters.SelectedItems.Clear()
        for identifier in identifiers:
            row = next(row for row in self.editor._all_items if row.Param.Id == identifier)
            self.editor.lstParameters.SelectedItems.Add(row)

    def assert_group(self, group, expected):
        self.editor.lstParameters.UpdateLayout()
        actual = next(g for g in self.editor._param_view.Groups if g.Name == group)
        self.assertEqual([row.Param.Id for row in actual.Items], expected)

    def test_real_wpf_moves_update_grouped_rows_without_reset(self):
        editor = self.editor
        notifications = []
        editor._param_view.CollectionChanged += lambda sender, args: notifications.append(str(args.Action))
        original_view = editor._param_view
        original_rows = list(editor._all_items)
        self.select(3, 6)
        editor._reorder_move("top")
        self.assert_group("dimensions", [3, 1, 2])
        self.assert_group("other", [6, 4, 5])
        self.assertEqual(set(row.Param.Id for row in editor.lstParameters.SelectedItems), set([3, 6]))
        editor._reorder_move("down")
        self.assert_group("dimensions", [1, 3, 2])
        self.assert_group("other", [4, 6, 5])
        self.assertIs(editor._param_view, original_view)
        self.assertTrue(all(any(row is old for old in original_rows) for row in editor._all_items))
        self.assertTrue(notifications)
        self.assertNotIn("Reset", notifications)
        self.assertEqual(self.manager.commits, [])
        self.assertEqual(self.manager.reorders, [])
        editor.on_reset_sorting(None, None)
        self.assert_group("dimensions", [1, 2, 3])
        self.assert_group("other", [4, 5, 6])

    def test_reorder_then_all_modifications_then_create_before_apply(self):
        editor = self.editor
        self.select(3, 6)
        editor._reorder_move("top")
        self.select(1)
        editor.currentValueEditor = State(Content="42")
        editor._value_editor_value = lambda value: value
        editor._can_edit_value = lambda item: True
        editor.on_apply_value(None, None)
        self.assertEqual(self.manager.parameters[0].Value, "42")
        self.assert_group("dimensions", [3, 1, 2])
        editor.on_toggle_instance_type(None, None)
        self.assertTrue(self.manager.parameters[0].IsInstance)
        self.assert_group("dimensions", [3, 1, 2])
        editor.on_toggle_instance_type(None, None)
        self.assertFalse(self.manager.parameters[0].IsInstance)
        editor._selected_edit_group_value = lambda: "other"
        editor._do_group_move = lambda parameter, group: setattr(parameter, "group", group)
        editor.on_apply_param_settings(None, None)
        self.assert_group("dimensions", [3, 2])
        self.assert_group("other", [6, 4, 5, 1])
        editor._formula_get_text = lambda: "2 + 3"
        editor.on_apply_formula(None, None)
        self.assertEqual(self.manager.parameters[0].Formula, "2 + 3")
        self.assert_group("other", [6, 4, 5, 1])
        editor._formula_set_text = lambda value: setattr(editor, "_formula_get_text", lambda: value)
        editor.on_clear_formula(None, None)
        editor.on_apply_formula(None, None)
        self.assertEqual(self.manager.parameters[0].Formula, "")
        editor.chkNewShared = State(IsChecked=False)
        editor.chkNewInstance = State(IsChecked=False)
        editor.txtNewName = State(Text="New Parameter")
        editor.txtNewInitialValue = State(Text="99")
        editor.txtNewFormula = object()
        editor._selected_group_value = lambda: "other"
        editor._selected_type_value = lambda: "Text"
        editor._rtb_get_text = lambda control: ""
        editor._rtb_set_text = lambda control, text: None
        editor.on_create_parameter(None, None)
        self.assertEqual(len(self.manager.parameters), 7)
        self.assertEqual(self.manager.parameters[-1].Value, "99")
        self.assert_group("dimensions", [3, 2])
        self.assert_group("other", [6, 4, 5, 1, 7])
        self.assertEqual(self.manager.reorders, [])
        self.assertTrue(editor._has_pending_order())
        editor.on_apply_sorting(None, None)
        self.assertEqual(len(self.manager.reorders), 1)
        self.assertEqual(self.manager.reorders[0], [6, 3, 2, 4, 5, 1, 7])
        self.assertFalse(editor._has_pending_order())
        self.assert_group("dimensions", [3, 2])
        self.assert_group("other", [6, 4, 5, 1, 7])

    def test_real_wpf_all_arrow_directions_sort_and_group_filter(self):
        editor = self.editor
        self.select(2)
        for action, expected in (
                ("up", [2, 1, 3]), ("down", [1, 2, 3]),
                ("bottom", [1, 3, 2]), ("top", [2, 1, 3])):
            editor._reorder_move(action)
            self.assert_group("dimensions", expected)
        editor.cmbGroupFilter.SelectedItem = "other"
        editor._apply_parameter_filter()
        self.select(6)
        editor._reorder_move("top")
        self.assert_group("other", [6, 4, 5])
        self.assertEqual(len(editor._param_view.Groups), 1)
        editor.on_group_sort(State(Tag=(set(["other"]), "Name Only", True)), None)
        self.assert_group("other", [6, 5, 4])
        editor.on_reset_sorting(None, None)
        self.assert_group("other", [4, 5, 6])
        self.assertEqual(self.manager.commits, [])

    def test_five_hundred_row_move_timing(self):
        self.manager.parameters = [Parameter(i, str(i), "dimensions") for i in range(500)]
        self.editor._reload_parameter_items()
        self.select(250)
        start = time.time()
        for unused in range(10):
            self.editor._reorder_move("up")
            self.editor.lstParameters.UpdateLayout()
        elapsed = time.time() - start
        self.assert_group("dimensions",
                          list(range(240)) + [250] + list(range(240, 250)) + list(range(251, 500)))
        print("500 rows, 10 WPF preview moves: {:.3f}s".format(elapsed))


if __name__ == "__main__":
    unittest.main()
