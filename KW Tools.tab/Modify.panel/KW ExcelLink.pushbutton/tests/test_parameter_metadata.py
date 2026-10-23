"""Identity, semantic type and per-target projection tests without Revit."""
import ast
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ElementType:
    pass


class ParameterElement:
    UniqueId = "project-parameter"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relative))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parameter(name, parameter_id, spec="text", storage="String", guid=None):
    return types.SimpleNamespace(
        Id=parameter_id, IsShared=guid is not None, GUID=guid,
        Definition=types.SimpleNamespace(
            Name=name, GetDataType=lambda: types.SimpleNamespace(TypeId=spec)),
        StorageType=storage,
    )


class ParameterMetadataTests(unittest.TestCase):
    def setUp(self):
        self.db = types.ModuleType("Autodesk.Revit.DB")
        self.db.ElementType = ElementType
        self.db.ParameterElement = ParameterElement
        self.db.LabelUtils = types.SimpleNamespace(GetLabelForSpec=lambda spec: {
            "text": "Text", "length": "Length", "yesno": "Yes/No",
        }[spec.TypeId])
        self.db.Category = types.SimpleNamespace(IsBuiltInCategory=lambda spec: False)
        self.types = load("metadata_types", os.path.join("core", "types.py"))
        self.types.element_id_value = lambda value: value
        self.patch = patch.dict(sys.modules, {
            "Autodesk.Revit.DB": self.db, "core.types": self.types,
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.metadata = load("tested_metadata", os.path.join("core", "parameter_metadata.py"))
        self.owner = types.SimpleNamespace(UniqueId="element-1", GetTypeId=lambda: 100)
        self.family_type = ElementType()
        self.family_type.Family = types.SimpleNamespace(UniqueId="family-1")
        self.doc = types.SimpleNamespace(GetElement=lambda key: self.family_type if key == 100 else None)

    def test_semantic_types_distinguish_boolean_from_integer_storage(self):
        descriptor = self.metadata.parameter_descriptor(
            self.doc, self.owner, parameter("Enabled", -1, "yesno", "Integer"))
        self.assertEqual(descriptor["dataType"], "Yes/No")
        self.assertEqual(descriptor["storageType"], "Integer")

    def test_identity_and_spec_not_display_name_define_compatible_columns(self):
        first = self.metadata.parameter_descriptor(self.doc, self.owner, parameter("Size", -1))
        renamed = self.metadata.parameter_descriptor(self.doc, self.owner, parameter("Translated", -1))
        other_id = self.metadata.parameter_descriptor(self.doc, self.owner, parameter("Size", -2))
        other_spec = self.metadata.parameter_descriptor(
            self.doc, self.owner, parameter("Size", -1, "length", "Double"))
        self.assertEqual(first["key"], renamed["key"])
        self.assertNotEqual(first["key"], other_id["key"])
        self.assertNotEqual(first["key"], other_spec["key"])

    def test_shared_project_and_local_family_parameters_have_distinct_scopes(self):
        self.assertEqual(self.metadata.parameter_identity(
            self.doc, self.owner, parameter("Code", 1, guid="guid-1")), "shared:guid-1")
        self.assertEqual(self.metadata.parameter_identity(
            self.doc, self.owner, parameter("Code", 1)), "local:family-1:1")
        self.family_type.Family.UniqueId = "family-2"
        self.assertEqual(self.metadata.parameter_identity(
            self.doc, self.owner, parameter("Code", 1)), "local:family-2:1")
        self.doc.GetElement = lambda key: ParameterElement()
        self.assertEqual(self.metadata.parameter_identity(
            self.doc, self.owner, parameter("Code", 1)), "project:project-parameter")

    def test_discovery_tracks_category_coverage_and_disambiguates_same_names(self):
        category_a = types.SimpleNamespace(Id=10, Name="Doors")
        category_b = types.SimpleNamespace(Id=20, Name="Windows")
        first = types.SimpleNamespace(
            Category=category_a, GetTypeId=lambda: -1,
            Parameters=[parameter("Comments", -1), parameter("Size", -2)])
        second = types.SimpleNamespace(
            Category=category_b, GetTypeId=lambda: -1,
            Parameters=[parameter("Comments", -1), parameter("Size", -3, "length", "Double")])
        with patch.dict(sys.modules, {"core.parameter_metadata": self.metadata}):
            module = load("tested_map", os.path.join("core", "parameter_map.py"))
        usage = module.build_parameter_usage_map(self.doc, [first, second])
        comments = next(entry for entry in usage.values() if entry["name"] == "Comments")
        self.assertEqual(comments["categoryCount"], 2)
        self.assertEqual(comments["totalCategories"], 2)
        sizes = [entry for entry in usage.values() if entry["name"] == "Size"]
        self.assertEqual(len(sizes), 2)
        self.assertNotEqual(sizes[0]["displayName"], sizes[1]["displayName"])

    def test_projection_preserves_type_lock_and_reference_choices_per_cell(self):
        with patch.dict(sys.modules, {"core.types": self.types}):
            module = load("tested_columns", os.path.join("core", "column_builder.py"))
        usage = {"key": {
            "name": "Reference", "dataType": "Reference", "identity": "builtin:-1",
            "specTypeId": "reference", "storageType": "ElementId",
            "isType": True, "isInstance": True,
        }}
        columns = module.build_columns(["key"], usage, "Instances Mode")
        type_record = {
            "storageType": "ElementId", "isReadOnly": False, "referenceKind": {"key": "type"},
            "identity": "builtin:-1", "builtin": -1,
        }
        instance_record = dict(type_record, isReadOnly=True, referenceKind={"key": "instance"})
        record = {
            "isTypeParam": True, "isInstanceParam": True,
            "typeValue": "Type choice", "instanceValue": "Instance choice",
            "typeRecord": type_record, "instanceRecord": instance_record,
            "typeKind": type_record["referenceKind"], "instanceKind": instance_record["referenceKind"],
        }
        rows = [
            {"Parameters": {"key": record}},
            {"Parameters": {"key": dict(record, typeRecord=dict(
                type_record, referenceKind={"key": "other"}))}},
            {"Parameters": {}},
        ]
        catalog = types.SimpleNamespace(options=lambda kind: [kind["key"] + " choice"])
        projected = module.project_rows(rows, columns, catalog)
        self.assertFalse(projected[0]["p0_type__disabled"])
        self.assertTrue(projected[0]["p0_instance__disabled"])
        self.assertEqual(projected[0]["p0_type__metadata"]["options"], ["type choice"])
        self.assertEqual(projected[1]["p0_type__metadata"]["options"], ["other choice"])
        self.assertTrue(projected[2]["p0_type__disabled"])
        self.assertIn("not available", projected[2]["p0_type__note"])

    def test_apply_grouping_keeps_same_name_distinct_identities_separate(self):
        with open(os.path.join(ROOT, "core", "apply_changes.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_group_changes")
        namespace = {"TARGET_TYPE": "type", "TARGET_INSTANCE": "instance", "TARGET_TYPE_NAME": "typeName"}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "apply_groups", "exec"), namespace)
        changes = [
            {"target": "instance", "elementId": 1, "parameterName": "Size", "parameterKey": key, "value": value}
            for key, value in [("key-a", "one"), ("key-b", "two")]
        ]
        self.assertEqual(len(namespace["_group_changes"](changes)[1]), 2)

    def test_extraction_keeps_duplicate_names_under_distinct_parameter_keys(self):
        with open(os.path.join(ROOT, "core", "extract.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_parameter_values")
        namespace = {
            "parameter_descriptor": self.metadata.parameter_descriptor,
            "_READ_ONLY_REASON": "Read-only in Revit.",
            "_read_parameter": lambda p, owner, catalog: {
                "isReadOnly": False, "readOnlyReason": None, "value": p.Id},
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "extract_values", "exec"), namespace)
        params = [parameter("Size", -1), parameter("Size", -2, "length", "Double")]
        self.owner.Parameters = params
        usage = {}
        for param in params:
            descriptor = self.metadata.parameter_descriptor(self.doc, self.owner, param)
            usage[descriptor["key"]] = descriptor
        values = namespace["_parameter_values"](
            self.owner, set(usage), types.SimpleNamespace(doc=self.doc), usage)
        self.assertEqual(len(values), 2)
        self.assertEqual({record["value"] for record in values.values()}, {-1, -2})

    def test_apply_requires_identity_spec_and_storage_match(self):
        with open(os.path.join(ROOT, "core", "apply_changes.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_find_parameter")
        namespace = {
            "parameter_identity": self.metadata.parameter_identity,
            "_is_writable": lambda owner, parameter: True,
            "element_id_value": lambda value: value,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "find_parameter", "exec"), namespace)
        wrong = parameter("Size", -1)
        correct = parameter("Size", -2, "length", "Double")
        self.owner.Parameters = [wrong, correct]
        self.owner.Document = self.doc
        change = {
            "parameterName": "Size", "parameterIdentity": "builtin:-2",
            "specTypeId": "length", "storageType": "Double",
        }
        find = namespace["_find_parameter"]
        self.assertIs(find(self.owner, change), correct)
        self.assertIsNone(find(self.owner, dict(change, specTypeId="text")))
        self.assertIsNone(find(self.owner, dict(change, storageType="String")))


if __name__ == "__main__":
    unittest.main()
