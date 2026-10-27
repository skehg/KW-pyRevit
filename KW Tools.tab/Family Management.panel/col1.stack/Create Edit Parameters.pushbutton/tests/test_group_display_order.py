"""Host-independent checks for the Revit 2026 parameter group display order."""
import ast
import io
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace

from test_value_editing import TREE, SCRIPT, load_functions


EXPECTED_ORDER = """Sub-division
Constraints
Construction
Rebar Set
Set
Graphics
Text
Materials and Finishes
Division Geometry
Electrical
Electrical Engineering
Electrical - Lighting
Electrical - Loads
Segments and Fittings
Plumbing
Secondary End
Structural
Layers
Slab Shape Edit
Dimensions
Mechanical
Mechanical - Flow
Mechanical - Loads
Analytical Model
Analytical Alignment
Releases / Member Forces
Structural Analysis
Forces
Moments
Phasing
Energy Analysis
IFC Parameters
Fire Protection
Title Text
Green Building Properties
Photometrics
Analysis Results
Model Properties
General
Electrical - Circuiting
Data
Visibility
Overall Legend
Electrical Analysis
Life Safety
Structural Section Dimensions
View to Sheet Positioning
Visualization
Other
Identity Data""".splitlines()


class GroupDisplayOrderTests(unittest.TestCase):
    def setUp(self):
        namespace = {"io": io}
        loader = load_functions(["_load_parameter_group_display_order"], namespace)
        order_path = SCRIPT.parents[3] / "lib" / "RevitGroupOrder.txt"
        namespace["_PARAMETER_GROUP_DISPLAY_ORDER"] = loader._load_parameter_group_display_order(order_path)
        names = {"_PARAMETER_GROUP_DISPLAY_RANK"}
        assignments = [
            node for node in TREE.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names
                    for target in node.targets)
        ]
        exec(compile(ast.Module(body=assignments, type_ignores=[]), str(SCRIPT), "exec"), namespace)
        self.namespace = namespace
        self.functions = load_functions(
            ["_parameter_group_display_key",
             "_refresh_group_filter_options",
             "_apply_parameter_filter"], namespace)
        self.key = self.functions._parameter_group_display_key

    def test_all_fifty_groups_follow_requested_sequence(self):
        self.assertEqual(len(EXPECTED_ORDER), 50)
        self.assertEqual(sorted(reversed(EXPECTED_ORDER), key=self.key), EXPECTED_ORDER)

    def test_absent_groups_are_not_added_and_unknown_groups_follow(self):
        labels = ["Unknown Z", "Identity Data", "Dimensions", "Unknown A", "Constraints", "Other"]
        self.assertEqual(sorted(labels, key=self.key),
                         ["Constraints", "Dimensions", "Other", "Identity Data",
                          "Unknown A", "Unknown Z"])
        self.assertEqual(self.key(" Dimensions "), self.key("dimensions"))

    def test_filter_preserves_selection_and_only_lists_present_groups(self):
        combo = SimpleNamespace(SelectedItem="Dimensions")
        window = SimpleNamespace(
            cmbGroupFilter=combo, _all_groups_label="All Groups",
            _all_items=[SimpleNamespace(GroupLabel=label)
                        for label in ["Identity Data", "Dimensions", "Constraints", "Dimensions"]])
        self.functions._refresh_group_filter_options(window)
        self.assertEqual(combo.ItemsSource,
                         ["All Groups", "Constraints", "Dimensions", "Identity Data"])
        self.assertEqual(combo.SelectedItem, "Dimensions")

    def test_grid_presorts_groups_stably_before_wpf_grouping(self):
        class NetList(list):
            def Add(self, item):
                self.append(item)

        class GenericList:
            def __class_getitem__(cls, item):
                return NetList

        class View:
            def __init__(self, items):
                self.items = items
                self.GroupDescriptions = NetList()
                self.SortDescriptions = NetList()

        class Grouping:
            def __init__(self, name):
                self.name = name
                self.GroupNames = NetList()

        self.namespace.update(
            ObservableCollection=GenericList, ListCollectionView=View,
            PropertyGroupDescription=Grouping)
        items = [SimpleNamespace(Name=name, GroupLabel=group, Formula="")
                 for name, group in [("Z", "Dimensions"), ("A", "Constraints"), ("B", "Dimensions")]]
        window = SimpleNamespace(
            txtSearch=SimpleNamespace(Text=""),
            cmbGroupFilter=SimpleNamespace(SelectedItem="All Groups"),
            _all_groups_label="All Groups", _all_items=items,
            _update_reorder_buttons=lambda: None,
            lstParameters=SimpleNamespace())
        self.functions._apply_parameter_filter(window)
        self.assertEqual(window._param_view.SortDescriptions, [])
        grouping = window._param_view.GroupDescriptions[0]
        self.assertEqual(grouping.name, "GroupLabel")
        self.assertEqual(grouping.GroupNames, ["Constraints", "Dimensions"])
        self.assertEqual(window._param_view.items, [items[1], items[0], items[2]])

    def test_all_versions_use_file_order_without_2022_override(self):
        labels = ["Visibility", "Constraints", "Materials and Finishes", "Graphics",
                  "Construction", "Dimensions", "Identity Data", "Other"]
        expected = [label for label in EXPECTED_ORDER if label in labels]
        for version in [2022, 2026]:
            self.namespace["_revit_major_version"] = lambda: version
            self.assertEqual(sorted(labels, key=self.key), expected)

    def test_loader_reads_bom_and_rejects_missing_empty_and_duplicate_files(self):
        loader = self.namespace["_load_parameter_group_display_order"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "order.txt"
            with self.assertRaises(IOError):
                loader(path)
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                loader(path)
            path.write_text("Dimensions\n dimensions \n", encoding="utf-8")
            with self.assertRaises(ValueError):
                loader(path)
            path.write_text("Visibility\n\n Constraints \n", encoding="utf-8-sig")
            self.assertEqual(loader(path), ("Visibility", "Constraints"))


if __name__ == "__main__":
    unittest.main()
