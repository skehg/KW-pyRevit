"""Preset formula persistence tests; no Revit runtime required."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import presets


class FormulaPresetTests(unittest.TestCase):
    def test_formula_survives_disk_roundtrip(self):
        rule = {
            "expression": "=B1*2",
            "columns": ["Name", "Width", "Result"],
            "scope": "visible",
        }
        workbook = {
            "parameterMode": "Instances",
            "sheets": [{
                "categoryKey": "OST_Doors", "name": "Doors",
                "parameters": ["Width", "Result"],
                "rows": [{"ElementId": 123, "value": 99}],
            }],
        }
        data = presets.preset_from_workbook(
            workbook, [{"formulas": {"Result": rule}}], "Formula test", "view"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "test.json")
            presets._write_json(path, data)
            loaded = presets.load_preset(path)
        self.assertEqual(loaded["sheets"][0]["layout"]["formulas"], {"Result": rule})
        self.assertNotIn("rows", loaded["sheets"][0])

    def test_combined_preset_keeps_grid_layout_categories_and_parameter_keys(self):
        workbook = {
            "parameterMode": "Instances Mode",
            "gridLayout": "combined",
            "sheets": [{
                "name": "Combined categories",
                "categoryId": None,
                "categoryKey": "combined:OST_Doors|OST_Walls",
                "sheetKey": "combined:OST_Doors|OST_Walls",
                "categories": [
                    {"categoryId": 10, "categoryKey": "OST_Doors", "name": "Doors"},
                    {"categoryId": 20, "categoryKey": "OST_Walls", "name": "Walls"},
                ],
                "parameters": ["opaque-param-key"],
                "rows": [{"ElementId": 1}],
            }],
        }
        data = presets.preset_from_workbook(
            workbook, [{}], "Combined", "Current View"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "combined.json")
            presets._write_json(path, data)
            loaded = presets.load_preset(path)
        sheet = loaded["sheets"][0]
        self.assertEqual(loaded["gridLayout"], "combined")
        self.assertEqual(sheet["categories"], workbook["sheets"][0]["categories"])
        self.assertEqual(sheet["parameters"], ["opaque-param-key"])
        self.assertIsNone(sheet["categoryId"])
        self.assertNotIn("rows", sheet)

    def test_old_presets_and_invalid_rules(self):
        self.assertEqual(presets._clean_layout({})["formulas"], {})
        self.assertEqual(presets._clean_formulas({
            "Bad": {"expression": "B1", "columns": []},
            "Bad columns": {"expression": "=B1", "columns": [None]},
            "Bad rule": 1,
        }), {})

    def test_v1_entire_model_preset_migrates_to_entire_project(self):
        legacy_preset = {
            "version": 1,
            "name": "Legacy",
            "selectionMode": "Entire Model",
            "sheets": [],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "legacy.json")
            presets._write_json(path, legacy_preset)
            loaded = presets.load_preset(path)
        self.assertEqual(loaded["selectionMode"], "Entire Project File")
        self.assertEqual(loaded["version"], presets.PRESET_VERSION)

    def test_previous_project_label_loads_with_new_name(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "project.json")
            presets._write_json(path, {
                "version": 2, "selectionMode": "Entire Project", "sheets": [],
            })
            loaded = presets.load_preset(path)
        self.assertEqual(loaded["selectionMode"], "Entire Project File")

    def test_schedule_column_order_filters_and_sort_survive_disk_roundtrip(self):
        parameters = ["Door Number", "Width", "Level"]
        filters = {"advanced": {"join": "and", "rules": [
            {"title": "Door Number (Instance)", "op": "startsWith", "value": "D", "value2": ""},
            {"title": "Door Number (Instance)", "op": "notStartsWith", "value": "X", "value2": ""},
            {"title": "Door Number (Instance)", "op": "notEndsWith", "value": "ZZ", "value2": ""},
            {"title": "Level (Instance)", "op": "equals", "value": "Level 01", "value2": ""},
        ]}, "show": "topLevelInstances"}
        sort = [
            {"title": "Level (Instance)", "dir": "asc"},
            {"title": "Door Number (Instance)", "dir": "desc"},
            {"title": "Width (Instance)", "dir": "asc"},
        ]
        workbook = {
            "parameterMode": "Instances Mode",
            "sheets": [{
                "categoryKey": "OST_Doors", "name": "Doors",
                "parameters": parameters,
            }],
        }
        data = presets.preset_from_workbook(
            workbook, [{"filters": filters, "sort": sort}], "Schedule", "Entire Model"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "schedule.json")
            presets._write_json(path, data)
            loaded = presets.load_preset(path)
        sheet = loaded["sheets"][0]
        self.assertEqual(loaded["selectionMode"], "Entire Model")
        self.assertEqual(sheet["parameters"], parameters)
        self.assertEqual(sheet["layout"]["filters"]["show"], "topLevelInstances")
        self.assertEqual(sheet["layout"]["filters"]["advanced"], filters["advanced"])
        self.assertEqual(sheet["layout"]["sort"], sort)

    def test_each_sheet_keeps_its_own_sort_order_and_cleared_sort(self):
        workbook = {
            "parameterMode": "Instances Mode",
            "sheets": [
                {"categoryKey": key, "name": key, "parameters": ["Mark", "Level"]}
                for key in ("Doors", "Walls", "Floors")
            ],
        }
        sort_orders = [
            [{"title": "Mark", "dir": "desc"}, {"title": "Level", "dir": "asc"}],
            [{"title": "Level", "dir": "desc"}, {"title": "Mark", "dir": "asc"}],
            [],
        ]
        data = presets.preset_from_workbook(
            workbook, [{"sort": order} for order in sort_orders], "Sorts", "Current View"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "sorts.json")
            presets._write_json(path, data)
            loaded = presets.load_preset(path)
        self.assertEqual(
            [sheet["layout"]["sort"] for sheet in loaded["sheets"]],
            sort_orders,
        )


if __name__ == "__main__":
    unittest.main()
