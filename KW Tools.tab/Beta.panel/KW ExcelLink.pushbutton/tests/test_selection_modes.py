"""Selection scope tests without a Revit runtime."""
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeElementType(object):
    pass


class FakeCollector(object):
    def __init__(self, document):
        self.document = document
        self.element_types = False

    def WhereElementIsNotElementType(self):
        self.element_types = False
        return self

    def WhereElementIsElementType(self):
        self.element_types = True
        return self

    def ToElements(self):
        return self.document.types if self.element_types else self.document.instances


class SelectionModeTests(unittest.TestCase):
    def setUp(self):
        db = types.ModuleType("Autodesk.Revit.DB")
        db.ElementType = FakeElementType
        db.FilteredElementCollector = FakeCollector
        refs = types.ModuleType("core.element_refs")
        refs.make_element_id = int
        core_types = types.ModuleType("core.types")
        core_types.element_id_value = int
        path = os.path.join(ROOT, "core", "selection.py")
        spec = importlib.util.spec_from_file_location("tested_selection", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "Autodesk.Revit.DB": db,
            "core.element_refs": refs,
            "core.types": core_types,
        }):
            spec.loader.exec_module(self.module)

        self.category_instance = types.SimpleNamespace(Id=10, Name="Ducts",
                                                       BuiltInCategory="OST_DuctCurves")
        self.category_unused_type = types.SimpleNamespace(Id=20, Name="Unused Tags",
                                                          BuiltInCategory="OST_Tags")
        self.used_type = FakeElementType()
        self.used_type.Id = 101
        self.used_type.Category = self.category_instance
        self.unused_type = FakeElementType()
        self.unused_type.Id = 201
        self.unused_type.Category = self.category_unused_type
        self.instance = types.SimpleNamespace(
            Id=1, Category=self.category_instance, GetTypeId=lambda: 101
        )
        self.document = types.SimpleNamespace(
            instances=[self.instance],
            types=[self.used_type, self.unused_type],
            GetElement=lambda element_id: {
                101: self.used_type,
                201: self.unused_type,
            }.get(element_id),
        )
        self.uidoc = types.SimpleNamespace(
            Document=self.document,
            Selection=types.SimpleNamespace(GetElementIds=lambda: []),
        )

    def test_entire_model_includes_instances_and_only_their_used_types(self):
        elements = self.module.resolve_source_elements(self.uidoc, "Entire Model")
        self.assertEqual(elements, [self.instance, self.used_type])
        self.assertEqual(
            [item["label"] for item in self.module.category_options(elements)],
            ["Ducts [10]"],
        )

    def test_entire_project_keeps_all_project_types(self):
        elements = self.module.resolve_source_elements(self.uidoc, "Entire Project File")
        self.assertEqual(elements, [
            self.instance, self.used_type, self.unused_type,
        ])
        self.assertEqual(
            [item["label"] for item in self.module.category_options(elements)],
            ["Ducts [10]", "Unused Tags [20]"],
        )


if __name__ == "__main__":
    unittest.main()
