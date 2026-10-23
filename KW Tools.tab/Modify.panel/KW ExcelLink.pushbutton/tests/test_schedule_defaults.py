"""Schedule translation tests without a Revit runtime."""
import importlib.util
import os
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch


def field(name, key, hidden=False, kind="Instance", param_id=None):
    result = types.SimpleNamespace(
        GetName=lambda: name, FieldId=key, IsHidden=hidden,
        HasSchedulableField=kind in ("Instance", "ElementType"), FieldType=kind,
        GetSpecTypeId=lambda: "length",
    )
    if param_id is not None:
        result.ParameterId = param_id
    return result


def rule(key, kind="Equal", value="D", storage="String"):
    return types.SimpleNamespace(
        FieldId=key, FilterType=kind,
        IsStringValue=storage == "String", IsIntegerValue=storage == "Integer",
        IsDoubleValue=storage == "Double", IsElementIdValue=storage == "ElementId",
        GetStringValue=lambda: value, GetIntegerValue=lambda: value,
        GetDoubleValue=lambda: value, GetElementIdValue=lambda: value,
    )


class ScheduleDefaultsTests(unittest.TestCase):
    def setUp(self):
        db = types.ModuleType("Autodesk.Revit.DB")
        db.ViewSchedule = type("ViewSchedule", (), {})
        db.UnitUtils = types.SimpleNamespace(
            IsMeasurableSpec=lambda spec: True,
            ConvertFromInternalUnits=lambda value, unit: value * 304.8,
        )
        refs = types.ModuleType("core.element_refs")
        refs.element_display_name = lambda element: element.Name if element else "<None>"
        units = types.ModuleType("core.units")
        units._decimals = lambda accuracy: 2
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "core", "schedule_defaults.py")
        spec = importlib.util.spec_from_file_location("tested_schedule_defaults", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "Autodesk.Revit.DB": db, "core.element_refs": refs, "core.units": units,
        }):
            spec.loader.exec_module(self.module)
        self.view = db.ViewSchedule()
        self.fields = [
            field("Mark", 1), field("Unused", 2, hidden=True),
            field("Width", 3, kind="ElementType"), field("Level", 4, hidden=True),
            field("Count", 5, kind="Count"),
        ]
        by_id = {item.FieldId: item for item in self.fields}
        self.filters = [rule(4, "Equal", 10, "ElementId"), rule(1, "BeginsWith", "D")]
        self.view.Definition = types.SimpleNamespace(
            GetFieldOrder=lambda: [item.FieldId for item in self.fields],
            GetField=lambda key: by_id[key], GetFilters=lambda: self.filters,
            IsFilteredBySheet=False, IncludeLinkedFiles=False,
            HasEmbeddedSchedule=False, IsMaterialTakeoff=False,
            GetSortGroupFields=lambda: [
                types.SimpleNamespace(FieldId=3, SortOrder="Descending")
            ],
        )
        self.uidoc = types.SimpleNamespace(ActiveView=self.view)
        self.doc = Mock()
        self.doc.GetElement.return_value = types.SimpleNamespace(Name="Level 01")
        self.doc.GetUnits.return_value.GetFormatOptions.return_value = types.SimpleNamespace(
            GetUnitTypeId=lambda: "mm", Accuracy=0.01
        )
        self.sheet = {"columns": [
            {"parameterName": "Mark", "target": "instance", "title": "Mark (Instance)"},
            {"parameterName": "Width", "target": "type", "title": "Width (Type)"},
            {"parameterName": "Level", "target": "instance", "title": "Level (Instance)"},
        ]}

    def defaults(self):
        return self.module.read_schedule_defaults(self.uidoc, "Current View")

    def test_only_current_schedule_seeds_defaults(self):
        self.assertIsNone(self.module.read_schedule_defaults(None, "Entire Model"))
        self.uidoc.ActiveView = object()
        self.assertIsNone(self.module.read_schedule_defaults(self.uidoc, "Current View"))

    def test_display_order_then_hidden_filter_fields_without_unrelated_hidden_fields(self):
        defaults = self.defaults()
        self.assertEqual(self.module.schedule_parameters(
            defaults, dict.fromkeys(["Mark", "Width", "Level", "Unused", "Count"], {})
        ), ["Mark", "Width", "Level"])

    def test_filters_and_sort_use_real_column_titles_and_reference_names(self):
        layout, issues = self.module.build_schedule_layout(
            self.doc, self.defaults(), self.sheet
        )
        self.assertEqual(layout["filters"]["advanced"], {"join": "and", "rules": [
            {"title": "Level (Instance)", "op": "equals", "value": "Level 01", "value2": ""},
            {"title": "Mark (Instance)", "op": "startsWith", "value": "D", "value2": ""},
        ]})
        self.assertEqual(layout["sort"], [{"title": "Width (Type)", "dir": "desc"}])
        self.assertTrue(any("Count" in issue for issue in issues))

    def test_numeric_filter_uses_project_units_not_schedule_overrides(self):
        self.filters[:] = [rule(3, "GreaterThanOrEqual", 3.0, "Double")]
        layout, _ = self.module.build_schedule_layout(self.doc, self.defaults(), self.sheet)
        self.assertEqual(layout["filters"]["advanced"]["rules"][0], {
            "title": "Width (Type)", "op": "gte", "value": "914.4", "value2": "",
        })

    def test_all_supported_operators_and_negated_substrings(self):
        for native, op in self.module._OPERATORS.items():
            self.filters[:] = [rule(1, native, "D")]
            layout, _ = self.module.build_schedule_layout(self.doc, self.defaults(), self.sheet)
            self.assertEqual(layout["filters"]["advanced"]["rules"][0]["op"], op)
        for native, excluded, included in [
            ("NotBeginsWith", "D.01", "XD.01"),
            ("NotEndsWith", "01D.", "D.01"),
        ]:
            self.filters[:] = [rule(1, native, "D.")]
            layout, _ = self.module.build_schedule_layout(self.doc, self.defaults(), self.sheet)
            expression = layout["filters"]["advanced"]["rules"][0]["value"]
            self.assertIsNone(re.search(expression, excluded))
            self.assertIsNotNone(re.search(expression, included))

    def test_missing_fields_and_unsupported_filters_are_reported(self):
        self.filters[:] = [rule(1, "HasParameter"), rule(4)]
        self.sheet["columns"] = self.sheet["columns"][:2]
        layout, issues = self.module.build_schedule_layout(self.doc, self.defaults(), self.sheet)
        self.assertEqual(layout["filters"]["advanced"]["rules"], [])
        self.assertTrue(any("HasParameter" in issue for issue in issues))
        self.assertTrue(any("Level: Equal" in issue for issue in issues))

    def test_nonportable_schedule_scope_settings_are_reported(self):
        self.view.Definition.IsFilteredBySheet = True
        self.view.Definition.IncludeLinkedFiles = True
        _, issues = self.module.build_schedule_layout(self.doc, self.defaults(), self.sheet)
        self.assertTrue(any("filtering by sheet" in issue for issue in issues))
        self.assertTrue(any("Linked-file" in issue for issue in issues))

    def test_mixed_use_filter_targets_the_schedule_scope(self):
        self.sheet["columns"].append({
            "parameterName": "Mark", "target": "type", "title": "Mark (Type)"
        })
        layout, _ = self.module.build_schedule_layout(self.doc, self.defaults(), self.sheet)
        self.assertEqual(layout["filters"]["advanced"]["rules"][1]["title"], "Mark (Instance)")

    def test_types_mode_does_not_redirect_instance_filter_to_type_parameter(self):
        self.filters[:] = [rule(1, "BeginsWith", "D")]
        self.sheet["columns"][0]["target"] = "type"
        self.sheet["columns"][0]["title"] = "Mark (Type)"
        self.sheet["parameterUsage"] = {"Mark": {"isType": True, "isInstance": True}}
        layout, issues = self.module.build_schedule_layout(self.doc, self.defaults(), self.sheet)
        self.assertEqual(layout["filters"]["advanced"]["rules"], [])
        self.assertTrue(any("Mark: BeginsWith" in issue for issue in issues))

    def test_opaque_parameter_keys_use_identity_to_disambiguate_schedule_names(self):
        defaults = {"fields": [field("Mark", 1, param_id=-42)], "issues": []}
        usage = {
            "parameter-key-a": {
                "name": "Mark", "identity": "builtin:-42",
            },
            "parameter-key-b": {
                "name": "Mark", "identity": "shared:other",
            },
        }
        self.assertEqual(self.module.schedule_parameters(defaults, usage), [
            "parameter-key-a",
        ])

    def test_ambiguous_schedule_name_is_reported_instead_of_guessed(self):
        defaults = {"fields": [field("Mark", 1)], "issues": []}
        usage = {
            "parameter-key-a": {"name": "Mark", "identity": "builtin:-42"},
            "parameter-key-b": {"name": "Mark", "identity": "shared:other"},
        }
        self.assertEqual(self.module.schedule_parameters(defaults, usage), [])
        self.assertTrue(any("multiple parameters" in issue for issue in defaults["issues"]))


if __name__ == "__main__":
    unittest.main()
