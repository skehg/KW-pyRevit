"""Project-unit conversion and failure safety without a Revit dependency."""
import ast
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def forge_id(value):
    return types.SimpleNamespace(TypeId=value, Empty=lambda: not value)


class UnitConversionTests(unittest.TestCase):
    def setUp(self):
        self.spec = forge_id("length")
        self.unit = forge_id("millimeters")
        self.parameter = types.SimpleNamespace(
            Definition=types.SimpleNamespace(
                Name="Width", GetDataType=Mock(return_value=self.spec)
            ),
        )
        self.options = types.SimpleNamespace(
            GetUnitTypeId=Mock(return_value=self.unit),
            GetSymbolTypeId=Mock(return_value=forge_id("mm")),
            Accuracy=0.01,
        )
        self.units = types.SimpleNamespace(
            GetFormatOptions=Mock(return_value=self.options),
        )
        self.doc = types.SimpleNamespace(GetUnits=lambda: self.units)
        self.api = types.SimpleNamespace(
            IsMeasurableSpec=Mock(return_value=True),
            IsValidUnit=Mock(return_value=True),
            ConvertFromInternalUnits=Mock(side_effect=lambda value, unit: value * 304.8),
            ConvertToInternalUnits=Mock(side_effect=lambda value, unit: value / 304.8),
        )
        self.labels = types.SimpleNamespace(
            GetLabelForSymbol=Mock(return_value="mm"),
        )
        self.formats = types.SimpleNamespace(
            GetValidSymbols=Mock(return_value=[forge_id("mm")]),
        )
        self.logger = Mock()
        db = types.ModuleType("Autodesk.Revit.DB")
        db.UnitUtils, db.LabelUtils, db.FormatOptions = (
            self.api, self.labels, self.formats
        )
        pyrevit = types.ModuleType("pyrevit")
        pyrevit.script = types.SimpleNamespace(get_logger=lambda: self.logger)
        spec = importlib.util.spec_from_file_location(
            "tested_units", os.path.join(ROOT, "core", "units.py")
        )
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "Autodesk.Revit.DB": db, "pyrevit": pyrevit,
        }):
            spec.loader.exec_module(self.module)
        self.converter = self.module.UnitConverter(self.doc)

    def test_measurable_values_convert_round_and_cache(self):
        self.assertEqual(self.converter.to_display(self.parameter, 1.234567), 376.3)
        self.assertAlmostEqual(self.converter.to_internal(self.parameter, 304.8), 1.0)
        self.assertEqual(self.converter.symbol(self.parameter), "mm")
        self.units.GetFormatOptions.assert_called_once_with(self.spec)
        self.assertEqual(self.converter.to_display(self.parameter, -0.000001), 0.0)
        self.assertEqual(
            str(self.converter.to_display(self.parameter, -0.000001)), "0.0"
        )
        self.assertIsNone(self.converter.to_display(self.parameter, None))

    def test_unitless_values_are_unchanged(self):
        self.api.IsMeasurableSpec.return_value = False
        self.assertEqual(self.converter.to_display(self.parameter, 1.234567), 1.234567)
        self.assertEqual(self.converter.to_internal(self.parameter, 2.5), 2.5)
        self.assertEqual(self.converter.symbol(self.parameter), "")
        self.units.GetFormatOptions.assert_not_called()
        self.api.ConvertFromInternalUnits.assert_not_called()
        self.api.ConvertToInternalUnits.assert_not_called()

    def test_resolution_failures_never_return_raw_values_or_cache_failure(self):
        failures = [
            (self.parameter.Definition.GetDataType, "data type lookup failed"),
            (self.api.IsMeasurableSpec, "measurement detection failed"),
            (self.units.GetFormatOptions, "format lookup failed"),
            (self.options.GetUnitTypeId, "unit lookup failed"),
            (self.api.IsValidUnit, "unit validation failed"),
        ]
        for method, message in failures:
            with self.subTest(message=message):
                method.side_effect = RuntimeError(message)
                for convert in (self.converter.to_display, self.converter.to_internal):
                    with self.assertRaisesRegex(ValueError, "Width.*" + message):
                        convert(self.parameter, 1000.0)
                self.assertEqual(self.converter._cache, {})
                method.side_effect = None
        self.api.ConvertFromInternalUnits.assert_not_called()
        self.api.ConvertToInternalUnits.assert_not_called()
        self.assertEqual(self.converter.to_display(self.parameter, 1.0), 304.8)

    def test_empty_or_invalid_unit_information_is_an_error(self):
        cases = [
            (self.parameter.Definition.GetDataType, None),
            (self.parameter.Definition.GetDataType, forge_id("")),
            (self.options.GetUnitTypeId, None),
            (self.options.GetUnitTypeId, forge_id("")),
            (self.api.IsValidUnit, False),
        ]
        for method, value in cases:
            with self.subTest(value=value):
                original = method.return_value
                method.return_value = value
                with self.assertRaisesRegex(ValueError, "Cannot resolve project units"):
                    self.converter.to_internal(self.parameter, 1000.0)
                self.assertEqual(self.converter._cache, {})
                method.return_value = original
        self.api.ConvertToInternalUnits.assert_not_called()

    def test_invalid_accuracy_is_an_error_not_a_default_precision(self):
        for accuracy in (0, -1, float("nan"), float("inf"), None):
            with self.subTest(accuracy=accuracy):
                self.options.Accuracy = accuracy
                with self.assertRaisesRegex(ValueError, "Cannot resolve project units"):
                    self.converter.to_internal(self.parameter, 1000.0)
        self.api.ConvertToInternalUnits.assert_not_called()

    def test_symbol_failure_preserves_conversion_and_warns_once_per_spec(self):
        self.labels.GetLabelForSymbol.side_effect = RuntimeError("label lookup failed")
        self.assertEqual(self.converter.to_display(self.parameter, 1.0), 304.8)
        self.assertEqual(self.converter.symbol(self.parameter), "millimeters")
        self.assertAlmostEqual(self.converter.to_internal(self.parameter, 304.8), 1.0)
        self.logger.warning.assert_called_once()
        warning = self.logger.warning.call_args[0][0]
        self.assertIn("Width", warning)
        self.assertIn("millimeters", warning)
        self.assertIn("label lookup failed", warning)

    def test_hidden_symbol_uses_shortest_valid_symbol(self):
        self.options.GetSymbolTypeId.return_value = forge_id("")
        self.formats.GetValidSymbols.return_value = [
            forge_id(""), forge_id("long"), forge_id("short"),
        ]
        self.labels.GetLabelForSymbol.side_effect = lambda symbol: {
            "long": "millimetres", "short": "mm",
        }[symbol.TypeId]
        self.assertEqual(self.converter.symbol(self.parameter), "mm")
        self.logger.warning.assert_not_called()

    def test_units_without_symbols_remain_valid(self):
        self.options.GetSymbolTypeId.return_value = forge_id("")
        self.formats.GetValidSymbols.return_value = []
        self.assertEqual(self.converter.symbol(self.parameter), "")
        self.assertEqual(self.converter.to_display(self.parameter, 1.0), 304.8)
        self.logger.warning.assert_not_called()

    def test_conversion_errors_propagate(self):
        self.api.ConvertFromInternalUnits.side_effect = RuntimeError("read conversion failed")
        self.api.ConvertToInternalUnits.side_effect = RuntimeError("write conversion failed")
        with self.assertRaisesRegex(RuntimeError, "read conversion failed"):
            self.converter.to_display(self.parameter, 1.0)
        with self.assertRaisesRegex(RuntimeError, "write conversion failed"):
            self.converter.to_internal(self.parameter, 1000.0)

    def test_failed_resolution_prevents_parameter_set(self):
        with open(os.path.join(ROOT, "core", "apply_changes.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        nodes = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef)
                 and node.name == "_set_parameter_value"]
        storage = types.SimpleNamespace(String="String", Integer="Integer", Double="Double")
        namespace = {"StorageType": storage, "math": __import__("math")}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "apply_changes", "exec"),
             namespace)
        self.parameter.StorageType = storage.Double
        self.parameter.IsReadOnly = False
        self.parameter.Set = Mock(return_value=True)
        self.units.GetFormatOptions.side_effect = RuntimeError("format lookup failed")
        with self.assertRaisesRegex(ValueError, "format lookup failed"):
            namespace["_set_parameter_value"](self.parameter, 1000.0, self.converter)
        self.parameter.Set.assert_not_called()
        self.units.GetFormatOptions.side_effect = None
        namespace["_set_parameter_value"](self.parameter, 304.8, self.converter)
        self.parameter.Set.assert_called_once_with(1.0)


if __name__ == "__main__":
    unittest.main()
