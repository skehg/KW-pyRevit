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

    def test_old_presets_and_invalid_rules(self):
        self.assertEqual(presets._clean_layout({})["formulas"], {})
        self.assertEqual(presets._clean_formulas({
            "Bad": {"expression": "B1", "columns": []},
            "Bad columns": {"expression": "=B1", "columns": [None]},
            "Bad rule": 1,
        }), {})


if __name__ == "__main__":
    unittest.main()
