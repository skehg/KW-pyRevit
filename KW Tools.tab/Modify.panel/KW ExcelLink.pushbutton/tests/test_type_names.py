"""Type-name inventory and preflight checks without Revit."""
import ast
import importlib.util
import os
import sys
import types
import unittest
import uuid
from unittest.mock import Mock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TypeNameTests(unittest.TestCase):
    def setUp(self):
        db = types.ModuleType("Autodesk.Revit.DB")
        db.ElementType = type("ElementType", (), {})
        db.FamilySymbol = type("FamilySymbol", (), {})
        self.db = db
        self.collector = Mock()
        self.collector.OfClass.return_value = []
        db.FilteredElementCollector = Mock(return_value=self.collector)
        db.NamingUtils = types.SimpleNamespace(
            IsValidName=lambda value: not any(c in value for c in "|[]\\"),
            CompareNames=lambda a, b: (a > b) - (a < b),
        )
        refs = types.ModuleType("core.element_refs")
        refs.element_type_name = lambda element: element.name
        core_types = types.ModuleType("core.types")
        core_types.element_id_value = int
        spec = importlib.util.spec_from_file_location(
            "tested_type_names", os.path.join(ROOT, "core", "type_names.py")
        )
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "Autodesk.Revit.DB": db, "core.element_refs": refs, "core.types": core_types,
        }):
            spec.loader.exec_module(self.module)
        self.records = [
            {"id": 1, "scope": "a", "family": "Door A", "name": "Small"},
            {"id": 2, "scope": "a", "family": "Door A", "name": "Large"},
            {"id": 3, "scope": "b", "family": "Door B", "name": "Small"},
        ]

    def test_final_name_duplicates_and_external_collisions_are_rejected(self):
        for names in ({1: "New", 2: "New"}, {1: "Large"}):
            with self.subTest(names=names):
                with self.assertRaisesRegex(ValueError, "Type-name conflict"):
                    self.module.validate_type_renames(self.records, names)

    def test_swaps_chains_and_other_families_are_allowed(self):
        for names in ({1: "Large", 2: "Small"}, {1: "Large", 2: "New"}, {3: "Large"}):
            self.module.validate_type_renames(self.records, names)

    def test_invalid_names_and_deleted_types_are_rejected(self):
        for name in ("", " ", "bad|name"):
            with self.assertRaisesRegex(ValueError, "Invalid type name"):
                self.module.validate_type_renames(self.records, {1: name})
        with self.assertRaisesRegex(ValueError, "no longer exist"):
            self.module.validate_type_renames(self.records, {4: "New"})

    def test_inventory_uses_family_ids_and_system_family_scopes(self):
        symbol = self.db.FamilySymbol()
        symbol.Id, symbol.name, symbol.FamilyName = 1, "Small", "Door A"
        symbol.Family = types.SimpleNamespace(Id=10)
        wall = types.SimpleNamespace(
            Id=2, name="Wall", FamilyName="Basic Wall",
            GetType=lambda: types.SimpleNamespace(FullName="Autodesk.Revit.DB.WallType"),
        )
        self.collector.OfClass.return_value = [symbol, wall]
        records = self.module.collect_type_names("doc")
        self.assertEqual(records[0]["scope"], "family:10")
        self.assertEqual(records[1]["scope"], "Autodesk.Revit.DB.WallType|Basic Wall")

    def test_attachment_caches_inventory_and_includes_types_outside_rows(self):
        catalog = types.SimpleNamespace(type_names=self.records)
        rows = [{"TypeElementId": 1}]
        result = self.module.attach_type_names("doc", rows, catalog)
        self.assertEqual([record["id"] for record in result], [1, 2])
        self.db.FilteredElementCollector.assert_not_called()

    def test_name_normalization_preserves_unicode(self):
        self.assertEqual(self.module.type_name_value(u"  Caf\u00e9  "), u"Caf\u00e9")

    def apply_function(self, final_writer):
        with open(os.path.join(ROOT, "core", "apply_changes.py"), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "apply_changes")
        self.transaction = Mock()
        self.transaction.Start.return_value = "started"
        self.transaction.Commit.return_value = "committed"
        self.transaction.HasStarted.return_value = True
        self.transaction_factory = Mock(return_value=self.transaction)
        self.changes = {
            (1, "__TYPE_NAME__"): {"value": "Large"},
            (2, "__TYPE_NAME__"): {"value": "Small"},
        }
        namespace = {
            "_group_changes": lambda changes: (self.changes, {}),
            "type_name_value": self.module.type_name_value,
            "collect_type_names": lambda doc: self.records,
            "validate_type_renames": self.module.validate_type_renames,
            "ReferenceCatalog": lambda doc: types.SimpleNamespace(),
            "Transaction": self.transaction_factory,
            "TransactionStatus": types.SimpleNamespace(Started="started", Committed="committed"),
            "make_element_id": int, "uuid": uuid,
            "_apply_type_changes": final_writer, "_apply_instance_changes": Mock(),
            "_check_moved_inserts": Mock(),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     "apply_changes", "exec"), namespace)
        return namespace["apply_changes"]

    def test_apply_frees_old_names_before_assigning_final_names(self):
        elements = {
            1: types.SimpleNamespace(CanBeRenamed=True, Name="Small"),
            2: types.SimpleNamespace(CanBeRenamed=True, Name="Large"),
        }

        def write(doc, changes, catalog):
            self.assertTrue(all(e.Name.startswith("__ExcelLink_") for e in elements.values()))
            for (type_id, _), change in changes.items():
                doc.GetElement(type_id).Name = change["value"]

        apply = self.apply_function(write)
        result = apply(types.SimpleNamespace(GetElement=elements.get), ["rename"])
        self.assertEqual([elements[i].Name for i in (1, 2)], ["Large", "Small"])
        self.assertEqual(result["applied"], 2)
        self.transaction.Commit.assert_called_once()
        self.transaction.Dispose.assert_called_once()

    def test_apply_rejects_conflicts_before_starting_transaction(self):
        apply = self.apply_function(Mock())
        self.changes.pop((2, "__TYPE_NAME__"))
        with self.assertRaisesRegex(ValueError, "Type-name conflict"):
            apply("doc", ["rename"])
        self.transaction_factory.assert_not_called()

    def test_apply_rolls_back_if_renaming_fails(self):
        apply = self.apply_function(Mock(side_effect=ValueError("Revit rejected name")))
        doc = types.SimpleNamespace(
            GetElement=lambda type_id: types.SimpleNamespace(CanBeRenamed=True, Name="old")
        )
        with self.assertRaisesRegex(ValueError, "Revit rejected name"):
            apply(doc, ["rename"])
        self.transaction.RollBack.assert_called_once()
        self.transaction.Commit.assert_not_called()
        self.transaction.Dispose.assert_called_once()


if __name__ == "__main__":
    unittest.main()
