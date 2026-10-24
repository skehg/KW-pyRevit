"""Identity, semantic type and per-target projection tests without Revit."""
import ast
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


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
        self.db.BuiltInParameter = types.SimpleNamespace(
            ELEM_CATEGORY_PARAM=-1140362, ELEM_CATEGORY_PARAM_MT=-1140363,
            SYMBOL_FAMILY_NAME_PARAM=-1002002, SYMBOL_NAME_PARAM=-1002001)
        self.db.StorageType = types.SimpleNamespace(String="String")
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
            "ElementType": ElementType,
            "parameter_descriptor": self.metadata.parameter_descriptor,
            "shadowed_parameter_ids": self.metadata.shadowed_parameter_ids,
            "element_id_value": lambda value: value,
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
            descriptor["isInstance"] = True
            usage[descriptor["key"]] = descriptor
        values = namespace["_parameter_values"](
            self.owner, set(usage), types.SimpleNamespace(doc=self.doc), usage)
        self.assertEqual(len(values), 2)
        self.assertEqual({record["value"] for record in values.values()}, {-1, -2})

    def test_compatible_definitions_across_families_collapse_but_keep_write_identities(self):
        category = types.SimpleNamespace(Id=10, Name="Doors")
        first = types.SimpleNamespace(
            Category=category, UniqueId="first", GetTypeId=lambda: -1,
            Parameters=[parameter("Validation Height", -101, "length", "Double")])
        second = types.SimpleNamespace(
            Category=category, UniqueId="second", GetTypeId=lambda: -1,
            Parameters=[parameter("Validation Height", -102, "length", "Double")])
        with patch.dict(sys.modules, {"core.parameter_metadata": self.metadata}):
            module = load("grouped_map", os.path.join("core", "parameter_map.py"))
        usage = module.build_parameter_usage_map(self.doc, [first, second])
        entries = [(key, entry) for key, entry in usage.items()
                   if entry["name"] == "Validation Height"]
        self.assertEqual(len(entries), 1)
        key, entry = entries[0]
        self.assertEqual(entry["displayName"], "Validation Height")
        self.assertEqual(len(entry["members"]), 2)
        with open(os.path.join(ROOT, "core", "extract.py"), encoding="utf-8") as stream:
            node = next(item for item in ast.parse(stream.read()).body
                        if isinstance(item, ast.FunctionDef) and item.name == "_parameter_values")
        namespace = {
            "ElementType": ElementType,
            "parameter_descriptor": self.metadata.parameter_descriptor,
            "shadowed_parameter_ids": self.metadata.shadowed_parameter_ids,
            "element_id_value": lambda value: value,
            "_READ_ONLY_REASON": "Read-only in Revit.",
            "_read_parameter": lambda p, owner, catalog: {
                "isReadOnly": False, "readOnlyReason": None, "value": p.Id},
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "group_values", "exec"), namespace)
        for owner, pid in ((first, -101), (second, -102)):
            record = namespace["_parameter_values"](
                owner, {key}, types.SimpleNamespace(doc=self.doc), usage)[key]
            self.assertEqual(record["value"], pid)
            self.assertNotEqual(record["identity"], entry["identity"])
            self.assertTrue(record["identity"].endswith(":" + str(pid)))
        first.Parameters.extend(second.Parameters)
        record = namespace["_parameter_values"](
            first, {key}, types.SimpleNamespace(doc=self.doc), usage)[key]
        self.assertTrue(record["isReadOnly"])
        self.assertIsNone(record["value"])
        self.assertIn("coexist", record["readOnlyReason"])

    def test_same_owner_conflicts_stay_separate(self):
        category = types.SimpleNamespace(Id=10, Name="Doors")
        owner = types.SimpleNamespace(
            Category=category, UniqueId="first", GetTypeId=lambda: -1,
            Parameters=[parameter("Height", -101, "length", "Double"),
                        parameter("Height", -102, "length", "Double")])
        with patch.dict(sys.modules, {"core.parameter_metadata": self.metadata}):
            module = load("conflicting_map", os.path.join("core", "parameter_map.py"))
        entries = [entry for entry in module.build_parameter_usage_map(
            self.doc, [owner]).values() if entry["name"] == "Height"]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all("members" not in entry for entry in entries))

    def test_spec_minor_patch_versions_group_but_different_quantities_do_not(self):
        old = {"name": "Height", "specTypeId": "autodesk.spec.aec:length-2.0.0",
               "storageType": "Double"}
        new = dict(old, specTypeId="autodesk.spec.aec:length-2.0.1")
        area = dict(old, specTypeId="autodesk.spec.aec:area-2.0.0")
        self.assertEqual(self.metadata.parameter_group_key(old),
                         self.metadata.parameter_group_key(new))
        self.assertNotEqual(self.metadata.parameter_group_key(old),
                            self.metadata.parameter_group_key(area))

    def test_same_builtin_spec_aliases_do_not_create_owner_conflicts(self):
        self.db.LabelUtils.GetLabelForSpec = lambda spec: "Length"
        category = types.SimpleNamespace(Id=10, Name="Doors")
        owner = types.SimpleNamespace(
            Category=category, UniqueId="first", GetTypeId=lambda: -1,
            Parameters=[
                parameter("Height", -1001300, "autodesk.spec.aec:length-2.0.0", "Double"),
                parameter("Height", -1001300, "autodesk.spec.aec:length-2.0.1", "Double")])
        with patch.dict(sys.modules, {"core.parameter_metadata": self.metadata}):
            module = load("builtin_alias_map", os.path.join("core", "parameter_map.py"))
        entries = [entry for entry in module.build_parameter_usage_map(
            self.doc, [owner]).values() if entry["name"] == "Height"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(entries[0]["members"]), 2)
        self.assertEqual(entries[0]["displayName"], "Height")

    def test_same_builtin_aliases_merge_even_when_other_height_definitions_conflict(self):
        self.db.LabelUtils.GetLabelForSpec = lambda spec: "Length"
        category = types.SimpleNamespace(Id=10, Name="Doors")
        owner = types.SimpleNamespace(
            Category=category, UniqueId="first", GetTypeId=lambda: -1,
            Parameters=[
                parameter("Height", -1001300, "autodesk.spec.aec:length-2.0.0", "Double"),
                parameter("Height", -1001300, "autodesk.spec.aec:length-2.0.1", "Double"),
                parameter("Height", -999, "autodesk.spec.aec:length-2.0.1", "Double")])
        with patch.dict(sys.modules, {"core.parameter_metadata": self.metadata}):
            module = load("builtin_conflict_alias_map", os.path.join("core", "parameter_map.py"))
        entries = [entry for entry in module.build_parameter_usage_map(
            self.doc, [owner]).values() if entry["name"] == "Height"]
        self.assertEqual(len(entries), 2)
        aliases = next(entry for entry in entries if entry["identity"] == "builtin:-1001300")
        self.assertEqual(len(aliases["members"]), 2)
        self.assertEqual(aliases["displayName"], "Height [Length; builtin:-1001300]")
        with open(os.path.join(ROOT, "core", "extract.py"), encoding="utf-8") as stream:
            node = next(item for item in ast.parse(stream.read()).body
                        if isinstance(item, ast.FunctionDef) and item.name == "_parameter_values")
        namespace = {
            "ElementType": ElementType,
            "parameter_descriptor": self.metadata.parameter_descriptor,
            "shadowed_parameter_ids": self.metadata.shadowed_parameter_ids,
            "element_id_value": lambda value: value,
            "_READ_ONLY_REASON": "Read-only in Revit.",
            "_read_parameter": lambda p, owner, catalog: {
                "isReadOnly": True, "readOnlyReason": "Read-only in Revit.", "value": 2100},
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "alias_values", "exec"), namespace)
        record = namespace["_parameter_values"](
            owner, {aliases["key"]}, types.SimpleNamespace(doc=self.doc),
            {aliases["key"]: aliases})[aliases["key"]]
        self.assertEqual(record["value"], 2100)
        self.assertNotIn("coexist", record["readOnlyReason"])
        self.assertEqual(record["identity"], "builtin:-1001300")

    def test_existing_preset_explicit_definition_keys_remain_valid(self):
        key = '["builtin:-1001300","length","Double"]'
        usage = {"group": {
            "members": [key], "name": "Height", "identity": "group",
            "specTypeId": "length", "storageType": "Double"}}
        self.metadata.restore_parameter_keys(usage, [key])
        self.assertEqual(usage[key]["identity"], "builtin:-1001300")
        self.assertEqual(usage[key]["builtin"], -1001300)
        self.assertNotIn("members", usage[key])

    def test_reopening_picker_coalesces_legacy_and_grouped_height_selections(self):
        old = '["builtin:-1001300","autodesk.spec.aec:length-2.0.0","Double"]'
        patch_key = '["builtin:-1001300","autodesk.spec.aec:length-2.0.1","Double"]'
        alias = '["builtin:-1001300","autodesk.spec.aec:length-2","Double"]'
        group = '["field","Height","autodesk.spec.aec:length-2","Double"]'
        usage = {group: {"members": [old, patch_key], "name": "Height"}}
        selected = self.metadata.canonical_parameter_keys(
            usage, [old, group, patch_key, alias])
        self.assertEqual(selected, [group])
        self.assertEqual(list(usage), [group])
        usage[group].update(
            isType=True, isInstance=True, dataType="Length",
            storageType="Double", specTypeId="autodesk.spec.aec:length-2.0.0")
        with patch.dict(sys.modules, {"core.types": self.types}):
            columns_module = load("restored_height_columns", os.path.join("core", "column_builder.py"))
        columns = columns_module.build_columns(selected, usage, "Instances Mode")
        height_columns = [column for column in columns if column.get("columnType") == "parameter"]
        self.assertEqual([column["target"] for column in height_columns], ["type", "instance"])
        projected = columns_module.project_rows([{"Parameters": {
            group: {"isTypeParam": False, "isInstanceParam": True,
                    "instanceValue": 2900, "storageType": "Double", "isReadOnly": True}
        }}], columns)
        displayed = [projected[0].get(column["field"]) for column in height_columns]
        self.assertEqual(displayed, [None, 2900])

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

    def _curtain_twin_elements(self):
        self.db.LabelUtils.GetLabelForSpec = lambda spec: "Length"
        length = "autodesk.spec.aec:length-2.0.0"

        def size_parameters(*ids):
            names = {-1001300: "Height", -1010300: "Height", -1001301: "Width", -1010301: "Width"}
            return [parameter(names[pid], pid, length, "Double") for pid in ids]

        doors = types.SimpleNamespace(Id=-2000023, Name="Doors")
        windows = types.SimpleNamespace(Id=-2000014, Name="Windows")
        panels = types.SimpleNamespace(Id=-2000170, Name="Curtain Panels")
        door_type = ElementType()
        door_type.Category = doors
        door_type.UniqueId = "door-type"
        door_type.Family = types.SimpleNamespace(UniqueId="door-family")
        door_type.Parameters = size_parameters(-1001300, -1001301)
        window_type = ElementType()
        window_type.Category = windows
        window_type.UniqueId = "window-type"
        window_type.Family = types.SimpleNamespace(UniqueId="window-family")
        window_type.Parameters = size_parameters(-1001300, -1001301)
        types_by_id = {1: door_type, 2: window_type}
        self.doc.GetElement = lambda key: types_by_id.get(key)
        twins = (-1010300, -1001300, -1010301, -1001301)
        return {
            "door": types.SimpleNamespace(Category=doors, UniqueId="door", GetTypeId=lambda: 1,
                                          Parameters=[]),
            "window": types.SimpleNamespace(Category=windows, UniqueId="window",
                                            GetTypeId=lambda: 2, Parameters=[]),
            "curtain_door": types.SimpleNamespace(Category=doors, UniqueId="cp-door",
                                                  GetTypeId=lambda: -1,
                                                  Parameters=size_parameters(*twins)),
            "curtain_window": types.SimpleNamespace(Category=windows, UniqueId="cp-window",
                                                    GetTypeId=lambda: -1,
                                                    Parameters=size_parameters(*twins)),
            "panel": types.SimpleNamespace(Category=panels, UniqueId="panel", GetTypeId=lambda: -1,
                                           Parameters=size_parameters(*twins)),
        }

    def _size_usage(self, elements):
        with patch.dict(sys.modules, {"core.parameter_metadata": self.metadata}):
            module = load("curtain_twin_map", os.path.join("core", "parameter_map.py"))
        module.element_id_value = lambda value: value
        usage = module.build_parameter_usage_map(self.doc, elements)
        return dict((name, [entry for entry in usage.values() if entry["name"] == name])
                    for name in ("Height", "Width"))

    def test_shadowed_ids_depend_on_each_elements_category(self):
        elements = self._curtain_twin_elements()
        shadowed = self.metadata.shadowed_parameter_ids
        self.assertEqual(shadowed(elements["curtain_door"]), {-1010300, -1010301})
        self.assertEqual(shadowed(elements["curtain_window"]), {-1010300, -1010301})
        self.assertEqual(shadowed(elements["panel"]), {-1001300, -1001301})
        self.assertEqual(shadowed(elements["door"]), set())
        other = types.SimpleNamespace(Category=types.SimpleNamespace(Id=-2000011),
                                      Parameters=elements["panel"].Parameters)
        self.assertEqual(shadowed(other), set())

    def test_door_and_window_selections_show_one_height_and_width(self):
        elements = self._curtain_twin_elements()
        for selection in (["door", "curtain_door"], ["window", "curtain_window"],
                          ["door", "curtain_door", "window", "curtain_window"]):
            sizes = self._size_usage([elements[name] for name in selection])
            for name in ("Height", "Width"):
                self.assertEqual(len(sizes[name]), 1, (selection, name))
                entry = sizes[name][0]
                self.assertEqual(entry["displayName"], name)
                self.assertTrue(entry["isType"] and entry["isInstance"])
                self.assertTrue(all("builtin:-10103" not in member for member in entry["members"]))

    def test_curtain_panel_selection_keeps_curtain_panel_height_and_width(self):
        elements = self._curtain_twin_elements()
        sizes = self._size_usage([elements["panel"]])
        self.assertEqual(len(sizes["Height"]), 1)
        self.assertEqual(sizes["Height"][0]["members"],
                         ['["builtin:-1010300","autodesk.spec.aec:length-2.0.0","Double"]'])
        self.assertEqual(sizes["Width"][0]["members"],
                         ['["builtin:-1010301","autodesk.spec.aec:length-2.0.0","Double"]'])
        self.assertEqual(sizes["Height"][0]["displayName"], "Height")

    def test_mixed_categories_share_columns_but_read_each_categorys_parameter(self):
        elements = self._curtain_twin_elements()
        selection = [elements[name] for name in ("door", "curtain_door", "panel")]
        sizes = self._size_usage(selection)
        self.assertEqual(len(sizes["Height"]), 1)
        height = sizes["Height"][0]
        self.assertEqual(height["displayName"], "Height")
        self.assertEqual(height["categoryNames"], ["Curtain Panels", "Doors"])
        self.assertEqual(sorted(height["members"]), [
            '["builtin:-1001300","autodesk.spec.aec:length-2.0.0","Double"]',
            '["builtin:-1010300","autodesk.spec.aec:length-2.0.0","Double"]'])
        with open(os.path.join(ROOT, "core", "extract.py"), encoding="utf-8") as stream:
            node = next(item for item in ast.parse(stream.read()).body
                        if isinstance(item, ast.FunctionDef) and item.name == "_parameter_values")
        namespace = {
            "ElementType": ElementType,
            "parameter_descriptor": self.metadata.parameter_descriptor,
            "shadowed_parameter_ids": self.metadata.shadowed_parameter_ids,
            "element_id_value": lambda value: value,
            "_READ_ONLY_REASON": "Read-only in Revit.",
            "_read_parameter": lambda p, owner, catalog: {
                "isReadOnly": True, "readOnlyReason": "Read-only in Revit.", "value": p.Id},
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "twin_values", "exec"), namespace)
        usage = {height["key"]: height}
        catalog = types.SimpleNamespace(doc=self.doc)
        read = namespace["_parameter_values"]
        self.assertEqual(read(elements["curtain_door"], {height["key"]}, catalog, usage)
                         [height["key"]]["value"], -1001300)
        self.assertEqual(read(elements["panel"], {height["key"]}, catalog, usage)
                         [height["key"]]["value"], -1010300)
        self.assertNotIn("coexist", read(elements["panel"], {height["key"]}, catalog, usage)
                         [height["key"]]["readOnlyReason"])


if __name__ == "__main__":
    unittest.main()
