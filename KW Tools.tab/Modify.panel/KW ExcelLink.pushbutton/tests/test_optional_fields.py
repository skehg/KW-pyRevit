"""Optional API fields and reversible filtering, without a Revit runtime."""
import ast
import math
import os
import sys
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.optional_fields import DerivedReader, derived_descriptors, field_options, select_usage


class Point(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z

    def Subtract(self, other):
        return Point(self.X - other.X, self.Y - other.Y, self.Z - other.Z)


class LocationPoint(object):
    Point = Point(20, 30, 40)
    Rotation = math.pi / 2


class ElementType(object):
    pass


class FamilyInstance(object):
    Location = LocationPoint()
    Pinned = True
    Category = types.SimpleNamespace(Name="Doors")
    Host = types.SimpleNamespace(Id=123)
    FacingOrientation = Point(0, 1, 0)
    HandOrientation = Point(1, 0, 0)

    def GetTypeId(self):
        return 1


class OptionalFieldTests(unittest.TestCase):
    def setUp(self):
        self.usage = dict((entry["key"], dict(entry, isType=False, isInstance=True))
                          for entry in derived_descriptors())
        self.db = types.ModuleType("Autodesk.Revit.DB")
        self.db.ElementType = ElementType
        self.db.FamilyInstance = FamilyInstance
        self.db.LocationPoint = LocationPoint
        self.base_calls = 0

        def base(doc):
            self.base_calls += 1
            return types.SimpleNamespace(Position=Point(3, 4, 5))
        self.db.BasePoint = types.SimpleNamespace(GetProjectBasePoint=base)
        self.doc = types.SimpleNamespace(
            ActiveProjectLocation=types.SimpleNamespace(
                GetProjectPosition=lambda p: types.SimpleNamespace(
                    EastWest=1000 - p.Y, NorthSouth=2000 + p.X, Elevation=p.Z + 100)),
            GetElement=lambda key: types.SimpleNamespace(FamilyName="Door family"))
        core_types = types.ModuleType("core.types")
        core_types.element_id_value = lambda value: value
        self.modules = {"Autodesk.Revit.DB": self.db, "core.types": core_types}

    def test_defaults_and_explicit_rollback(self):
        self.assertEqual(field_options(), {
            "coordinates": False, "usefulFields": False, "filterFalsePositives": True})
        raw = {
            "category": {"isType": True, "isInstance": True,
                         "usefulType": False, "usefulInstance": False},
            "family": {"isType": True, "isInstance": True, "usefulInstance": False},
            "comments": {"isInstance": True},
        }
        filtered = select_usage(raw, {})
        self.assertNotIn("category", filtered)
        self.assertTrue(filtered["family"]["isType"])
        self.assertFalse(filtered["family"]["isInstance"])
        self.assertIn("comments", filtered)
        self.assertEqual(select_usage(raw, {"filterFalsePositives": False}), raw)
        self.assertTrue(raw["family"]["isInstance"])

    def test_coordinate_and_useful_fields_are_independently_opt_in(self):
        self.assertEqual(select_usage(self.usage, {}), {})
        coordinates = select_usage(self.usage, {"coordinates": True})
        self.assertEqual(len(coordinates), 9)
        self.assertTrue(all(item["dataType"] == "Length" for item in coordinates.values()))
        useful = select_usage(self.usage, {"usefulFields": True})
        self.assertIn("derived:host", useful)
        self.assertNotIn("derived:internal_0", useful)

    def test_filtered_coverage_does_not_count_empty_scope_categories(self):
        raw = {"family": {
            "isType": True, "isInstance": True, "usefulType": True,
            "usefulInstance": False, "usefulTypeCategoryIds": [1],
            "usefulInstanceCategoryIds": [], "categoryIds": [1, 2],
            "categoryNames": ["Doors", "Windows"], "totalCategories": 2,
        }}
        entry = select_usage(raw, {})["family"]
        self.assertEqual(entry["categoryCount"], 1)
        self.assertEqual(entry["categoryNames"], ["Doors"])
        self.assertEqual(entry["typeCategoryIds"], [1])
        self.assertEqual(entry["instanceCategoryIds"], [])

    def test_nonzero_origins_rotated_shared_frame_and_units(self):
        reader = DerivedReader(self.doc)
        # Exercise conversion boundaries separately from Revit's unit service.
        reader._convert = lambda value, spec: (value * 304.8, "mm")
        with patch.dict(sys.modules, self.modules):
            records = reader.read(FamilyInstance(), set(self.usage), self.usage)
            reader.read(FamilyInstance(), {"derived:project_0"}, self.usage)
        self.assertAlmostEqual(records["derived:internal_0"]["value"], 20 * 304.8)
        self.assertAlmostEqual(records["derived:project_0"]["value"], 17 * 304.8)
        self.assertAlmostEqual(records["derived:project_2"]["value"], 35 * 304.8)
        self.assertAlmostEqual(records["derived:shared_0"]["value"], 970 * 304.8)
        self.assertAlmostEqual(records["derived:shared_1"]["value"], 2020 * 304.8)
        self.assertAlmostEqual(records["derived:shared_2"]["value"], 140 * 304.8)
        self.assertEqual(self.base_calls, 1)
        self.assertEqual(records["derived:host"]["value"], 123)
        self.assertTrue(all(record["isReadOnly"] for record in records.values()))

    def test_no_point_location_is_explicit_and_does_not_read_origins(self):
        element = FamilyInstance()
        element.Location = object()  # A curve or other unsupported Location.
        reader = DerivedReader(self.doc)
        reader._convert = lambda value, spec: (value * 304.8, "mm")
        with patch.dict(sys.modules, self.modules):
            record = reader.read(
                element, {"derived:project_0"}, self.usage)["derived:project_0"]
        self.assertIsNone(record["value"])
        self.assertIn("No point location", record["readOnlyReason"])
        self.assertEqual(self.base_calls, 0)

    def test_no_selected_derived_fields_does_not_read_location(self):
        self.assertEqual(DerivedReader(self.doc).read(object(), set(), {}), {})

    def test_builtin_filter_does_not_remove_custom_or_empty_editable_fields(self):
        from core.optional_fields import is_false_positive
        self.db.BuiltInParameter = types.SimpleNamespace(
            ELEM_CATEGORY_PARAM=-1, ELEM_CATEGORY_PARAM_MT=-2,
            SYMBOL_FAMILY_NAME_PARAM=-3, SYMBOL_NAME_PARAM=-4)
        self.db.StorageType = types.SimpleNamespace(String="String")
        with patch.dict(sys.modules, self.modules):
            def param(pid, readonly=True, value=None):
                return types.SimpleNamespace(
                    Id=pid, IsReadOnly=readonly, StorageType="String", AsString=lambda: value)
            self.assertTrue(is_false_positive(param(-1)))
            self.assertTrue(is_false_positive(param(-3)))
            self.assertFalse(is_false_positive(param(-3, value="Family")))
            self.assertFalse(is_false_positive(param(-3, readonly=False)))
            self.assertFalse(is_false_positive(param(100)))  # Custom Category/Family Name.

    def test_apply_rejects_derived_fields_before_any_transaction(self):
        with open(os.path.join(ROOT, "core", "apply_changes.py"), encoding="utf-8") as stream:
            node = next(item for item in ast.parse(stream.read()).body
                        if isinstance(item, ast.FunctionDef) and item.name == "_group_changes")
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "groups", "exec"), namespace)
        with self.assertRaisesRegex(ValueError, "read-only"):
            namespace["_group_changes"]([{"parameterIdentity": "derived:internal_0"}])


if __name__ == "__main__":
    unittest.main()
