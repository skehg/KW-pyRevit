"""Combined workbook schema tests without a Revit runtime."""
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CombinedWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.extracted = {}
        self.elements = []

        def extract_rows(doc, elements, mode, parameters, catalog, usage_map=None):
            self.extracted["usage_map"] = usage_map
            return [{"Category": element.Category.Name} for element in elements]

        def build_columns(parameters, usage, mode):
            return [
                {"title": "Category", "field": "Category", "visible": False},
                {"title": "Mark", "field": "p0_type", "columnType": "parameter"},
            ]

        def project_rows(rows, columns, catalog):
            return rows

        refs = types.ModuleType("core.element_refs")
        refs.ReferenceCatalog = type(
            "ReferenceCatalog", (), {"__init__": lambda self, doc: None}
        )
        refs.make_element_id = int
        column_builder = types.ModuleType("core.column_builder")
        column_builder.build_columns = build_columns
        column_builder.project_rows = project_rows
        extract = types.ModuleType("core.extract")
        extract.extract_rows = extract_rows
        parameter_map = types.ModuleType("core.parameter_map")
        parameter_map.build_parameter_usage_map = lambda doc, elements: {
            "param-key": {"name": "Mark", "displayName": "Mark", "isType": True,
                          "isInstance": True}
        }
        selection = types.ModuleType("core.selection")
        selection.category_key = lambda category: category.BuiltInCategory
        def category_options(elements):
            options = {}
            for element in elements:
                category = element.Category
                options[category.Id] = {
                    "category_id": category.Id,
                    "label": "{0} [{1}]".format(category.Name, category.Id),
                    "builtin": category.BuiltInCategory,
                }
            return [options[key] for key in sorted(options)]
        selection.category_options = category_options
        selection.elements_for_category = lambda elements, category_id: [
            element for element in elements
            if element.Category.Id == category_id
        ]
        core_types = types.ModuleType("core.types")
        core_types.MODE_INSTANCES = "Instances Mode"
        core_types.MODE_TYPES = "Types Mode"
        core_types.element_id_value = int
        type_names = types.ModuleType("core.type_names")
        type_names.attach_type_names = lambda doc, rows, catalog: {}
        modules = {
            "core.column_builder": column_builder,
            "core.element_refs": refs,
            "core.extract": extract,
            "core.parameter_map": parameter_map,
            "core.selection": selection,
            "core.types": core_types,
            "core.type_names": type_names,
        }
        path = os.path.join(ROOT, "core", "workbook_builder.py")
        spec = importlib.util.spec_from_file_location("tested_combined_workbook", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.module)

    def _element(self, element_id, category_id, name, key):
        category = types.SimpleNamespace(
            Id=category_id, Name=name, BuiltInCategory=key
        )
        return types.SimpleNamespace(
            Id=element_id, UniqueId="uid-{0}".format(element_id), Category=category
        )

    def test_combined_sheet_has_category_metadata_and_visible_category_column(self):
        categories = [
            {"categoryId": 10, "categoryKey": "OST_Doors", "name": "Doors"},
            {"categoryId": 20, "categoryKey": "OST_Walls", "name": "Walls"},
        ]
        sheet = self.module.build_sheet(
            None, None, "Combined categories", None,
            [self._element(1, 10, "Doors", "OST_Doors"),
             self._element(2, 20, "Walls", "OST_Walls")],
            ["param-key"], "Instances Mode", {"param-key": {"name": "Mark"}},
            categories=categories,
        )
        self.assertIsNone(sheet["categoryId"])
        self.assertEqual(sheet["categoryKey"], "combined:OST_Doors|OST_Walls")
        self.assertEqual(sheet["sheetKey"], sheet["categoryKey"])
        self.assertEqual(sheet["categories"], categories)
        self.assertTrue(next(
            column for column in sheet["columns"] if column["field"] == "Category"
        )["visible"])
        self.assertEqual(self.extracted["usage_map"], {"param-key": {"name": "Mark"}})

    def test_import_rebuilds_combined_sheet_from_parameter_keys_and_category_list(self):
        elements = [
            self._element(1, 10, "Doors", "OST_Doors"),
            self._element(2, 20, "Walls", "OST_Walls"),
        ]
        self.doc = types.SimpleNamespace(
            GetElement=lambda identifier: {
                "uid-1": elements[0], "uid-2": elements[1],
            }.get(identifier)
        )
        plan = {
            "parameterMode": "Instances Mode",
            "gridLayout": "combined",
            "sheets": [{
                "xlsxName": "Combined categories",
                "sheetKey": "combined:OST_Doors|OST_Walls",
                "gridLayout": "combined",
                "categoryId": None,
                "categoryKey": "combined:OST_Doors|OST_Walls",
                "categories": [
                    {"categoryId": 10, "categoryKey": "OST_Doors", "name": "Doors"},
                    {"categoryId": 20, "categoryKey": "OST_Walls", "name": "Walls"},
                ],
                "parameterKeys": ["param-key"],
                "parameterUsage": {
                    "param-key": {
                        "name": "Mark", "displayName": "Mark",
                        "identity": "identity", "specTypeId": "text",
                        "dataType": "Text", "isType": True, "isInstance": True,
                    },
                },
                "uniqueIds": ["uid-1", "uid-2"],
                "elementIds": [1, 2],
            }],
            "issues": [],
        }
        xlsx_import = types.ModuleType("core.xlsx_import")
        xlsx_import.read_import_plan = lambda path: plan
        xlsx_import.diff_xlsx = lambda workbook, path: {
            "updates": [], "summary": {}, "issues": [],
        }
        with patch.dict(sys.modules, {"core.xlsx_import": xlsx_import}):
            workbook, source, issues, missing = self.module.build_import_workbook(
                self.doc, "workbook.xlsx"
            )
        sheet = workbook["sheets"][0]
        self.assertEqual(workbook["gridLayout"], "combined")
        self.assertEqual(sheet["parameters"], ["param-key"])
        self.assertEqual(sheet["sheetKey"], "combined:OST_Doors|OST_Walls")
        self.assertEqual([item["name"] for item in sheet["categories"]], ["Doors", "Walls"])
        self.assertEqual(sheet["parameterUsage"]["param-key"]["identity"], "identity")
        self.assertEqual(len(source), 2)
        self.assertEqual(issues, [])
        self.assertEqual(missing, 0)

    def test_combined_preset_rebuilds_one_sheet_for_saved_categories(self):
        source = [
            self._element(1, 10, "Doors", "OST_Doors"),
            self._element(2, 20, "Walls", "OST_Walls"),
        ]
        for element in source:
            element.Id = element.Id
        presets = types.ModuleType("core.presets")
        presets.match_category = lambda requested, options: next(
            (option for option in options
             if option["builtin"] == requested.get("categoryKey")),
            None,
        )
        preset = {
            "parameterMode": "Instances Mode",
            "gridLayout": "combined",
            "sheets": [{
                "categoryName": "Combined categories",
                "categories": [
                    {"categoryId": 10, "categoryKey": "OST_Doors", "name": "Doors"},
                    {"categoryId": 20, "categoryKey": "OST_Walls", "name": "Walls"},
                ],
                "parameters": ["param-key"],
                "layout": {
                    "widths": {"Mark": 180},
                    "sort": [
                        {"title": "Mark", "dir": "desc"},
                        {"title": "Category", "dir": "asc"},
                    ],
                },
            }],
        }
        with patch.dict(sys.modules, {"core.presets": presets}):
            workbook, issues = self.module.build_preset_workbook(
                None, preset, "Current View", source
            )
        self.assertEqual(workbook["gridLayout"], "combined")
        self.assertEqual(len(workbook["sheets"]), 1)
        self.assertIsNone(workbook["sheets"][0]["categoryId"])
        self.assertEqual(workbook["sheets"][0]["parameters"], ["param-key"])
        self.assertEqual(
            workbook["sheets"][0]["categoryKey"],
            "combined:OST_Doors|OST_Walls",
        )
        self.assertEqual(workbook["sheets"][0]["layout"], preset["sheets"][0]["layout"])
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
