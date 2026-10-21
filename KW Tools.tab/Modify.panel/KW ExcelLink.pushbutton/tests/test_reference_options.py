"""Reference choices and names without a Revit dependency."""
import ast
import os
import types
import unittest
from unittest.mock import Mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeType(object):
    def __init__(self, element_id, parameter_name, api_name, similar=()):
        self.Id = element_id
        self.Category = None
        self.FamilyName = "Callout Tag"
        self.parameter_name = parameter_name
        self.api_name = api_name
        self.similar = similar

    def get_Parameter(self, builtin):
        if self.parameter_name is None:
            return None
        return types.SimpleNamespace(AsString=lambda: self.parameter_name)

    def GetType(self):
        return types.SimpleNamespace(FullName="Autodesk.Revit.DB.ElementType")

    def GetSimilarTypes(self):
        return self.similar


class ReferenceOptionsTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "core", "element_refs.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        names = {
            "element_type_name", "element_display_name", "_normalize", "none_labels",
            "_category_id", "ReferenceCatalog",
        }
        nodes = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                 and node.name in names]
        self.collector = Mock()
        self.namespace = {
            "Element": types.SimpleNamespace(
                Name=types.SimpleNamespace(GetValue=lambda element: element.api_name)
            ),
            "ElementType": FakeType,
            "BuiltInParameter": types.SimpleNamespace(
                SYMBOL_NAME_PARAM=1, PHASE_CREATED=2,
            ),
            "element_id_value": lambda value: value,
            "make_element_id": int, "UnitConverter": Mock(),
            "FilteredElementCollector": self.collector,
            "locked_reason": lambda owner, parameter: None,
            "_TYPE_CHANGE_BUILTINS": (), "_UNCONNECTED_BUILTINS": (),
            "_LEVEL_REFERENCE_BUILTINS": (), "_PHASE_BUILTINS": (),
            "NONE_LABEL": "<None>",
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]),
                     "element_refs", "exec"), self.namespace)
        self.current = FakeType(10, "Head A", "Head A", [10, 11])
        self.other = FakeType(11, "Head B", "Head B")
        self.arrow = FakeType(23087, "", "Arrowhead")
        self.arrow.FamilyName = "Arrowhead"
        self.elements = {10: self.current, 11: self.other, 23087: self.arrow}
        self.doc = types.SimpleNamespace(GetElement=self.elements.get)
        self.catalog = self.namespace["ReferenceCatalog"](self.doc)
        self.kind = self.catalog._kind(
            None, types.SimpleNamespace(IsReadOnly=False), 0, self.current
        )

    def test_generic_reference_uses_similar_types_not_document_wide_collector(self):
        self.assertEqual(self.kind["key"], "similarTypes|10")
        self.assertEqual(self.catalog.candidates(self.kind), [self.current, self.other])
        self.collector.assert_not_called()

    def test_options_exclude_unrelated_arrowheads(self):
        self.assertEqual(self.catalog.options(self.kind), [
            "<None>", "Callout Tag: Head A", "Callout Tag: Head B",
        ])

    def test_existing_value_is_preserved_when_not_in_similar_types(self):
        self.current.similar = [11]
        self.assertEqual(self.catalog.candidates(self.kind), [self.current, self.other])

    def test_options_round_trip_through_fresh_catalog(self):
        fresh = self.namespace["ReferenceCatalog"](self.doc)
        for name, expected_id in [
            ("Callout Tag: Head A", 10), ("Callout Tag: Head B", 11),
            ("Head B", 11), ("11", 11),
        ]:
            with self.subTest(name=name):
                self.assertEqual(fresh.resolve(self.kind, name), expected_id)
        with self.assertRaisesRegex(ValueError, "not a valid choice"):
            fresh.resolve(self.kind, "23087")

    def test_empty_parameter_name_uses_real_api_name(self):
        self.assertEqual(self.namespace["element_type_name"](self.arrow), "Arrowhead")
        self.assertEqual(
            self.namespace["element_display_name"](self.arrow), "Arrowhead: Arrowhead"
        )

    def test_missing_parameter_name_uses_real_api_name(self):
        self.arrow.parameter_name = None
        self.assertEqual(self.namespace["element_type_name"](self.arrow), "Arrowhead")

    def test_existing_parameter_names_are_unchanged(self):
        self.current.api_name = "Different API name"
        self.assertEqual(self.namespace["element_type_name"](self.current), "Head A")

    def test_genuinely_unnamed_type_still_reports_error(self):
        self.arrow.api_name = ""
        with self.assertRaisesRegex(ValueError, "23087"):
            self.namespace["element_type_name"](self.arrow)

    def test_missing_reference_type_reports_error(self):
        del self.elements[10]
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            self.catalog.candidates(self.kind)

    def test_categorized_types_keep_existing_reference_kind(self):
        self.current.Category = types.SimpleNamespace(Id=50)
        kind = self.catalog._kind(
            None, types.SimpleNamespace(IsReadOnly=False), 0, self.current
        )
        self.assertEqual(kind["key"], "class|Autodesk.Revit.DB.ElementType|50")

    def test_unset_reference_accepts_serialized_similar_type_kind(self):
        with open(os.path.join(ROOT, "core", "apply_changes.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        method = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_client_reference_kind")
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     "apply_changes", "exec"), namespace)
        validate = namespace["_client_reference_kind"]
        self.assertEqual(validate(self.kind), self.kind)
        for key in ["similarTypes|", "similarTypes|-1", "similarTypes|abc",
                    "similarTypes|10|11"]:
            self.assertIsNone(validate({"key": key}))
        legacy = {"key": "class|Autodesk.Revit.DB.Level|42", "allowNone": True,
                  "changesType": False}
        self.assertEqual(validate(legacy), legacy)


if __name__ == "__main__":
    unittest.main()
