"""Host-independent tests for parameter value editing (run with CPython)."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SCRIPT = Path(__file__).resolve().parents[1] / "script.py"
TREE = ast.parse(SCRIPT.read_text(encoding="utf-8-sig"))


def load_functions(names, namespace):
    nodes = []
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "ParameterEditorWindow":
            nodes.extend(
                method for method in node.body
                if isinstance(method, ast.FunctionDef) and method.name in names
            )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


class ElementId:
    InvalidElementId = -1

    def __init__(self, value):
        self.value = value


class ValueEditingTests(unittest.TestCase):
    def setUp(self):
        self.storage = SimpleNamespace(String=1, Double=2, Integer=3, ElementId=4)
        self.namespace = {"StorageType": self.storage, "ElementId": ElementId}
        self.functions = load_functions(
            ["_can_edit_value", "_value_editor_value", "_save_parameter_value",
             "_is_family_type_parameter", "_family_type_value_options"],
            self.namespace,
        )

    def test_read_only_formula_and_missing_type_are_locked(self):
        parameter = SimpleNamespace(
            IsReadOnly=False, IsDeterminedByFormula=False, StorageType=1)
        item = SimpleNamespace(Param=parameter)
        window = SimpleNamespace(fm=SimpleNamespace(CurrentType=object()))
        self.assertTrue(self.functions._can_edit_value(window, item))
        parameter.IsReadOnly = True
        self.assertFalse(self.functions._can_edit_value(window, item))
        parameter.IsReadOnly = False
        parameter.IsDeterminedByFormula = True
        self.assertFalse(self.functions._can_edit_value(window, item))
        parameter.IsDeterminedByFormula = False
        window.fm.CurrentType = None
        self.assertFalse(self.functions._can_edit_value(window, item))

    def test_editors_return_typed_ids_boolean_text_and_text(self):
        read = self.functions._value_editor_value
        identifier = ElementId(123)
        self.assertIs(read(None, SimpleNamespace(
            Tag="reference", SelectedItem=SimpleNamespace(Value=identifier))), identifier)
        for checked, expected in [(True, "Yes"), (False, "No")]:
            self.assertEqual(read(None, SimpleNamespace(
                Tag="yesno", IsChecked=checked)), expected)
        self.assertEqual(read(None, SimpleNamespace(Tag=None, Text="25 mm")), "25 mm")
        with self.assertRaises(ValueError):
            read(None, SimpleNamespace(Tag="reference", SelectedItem=None))

    def test_family_type_detection_legacy_and_forge(self):
        detect = self.functions._is_family_type_parameter
        self.namespace.update(
            _PT_AVAILABLE=True,
            ParameterType=SimpleNamespace(FamilyType="family"),
        )
        parameter = SimpleNamespace(
            StorageType=4, Definition=SimpleNamespace(ParameterType="family"))
        self.assertTrue(detect(parameter))
        parameter.Definition.ParameterType = "material"
        self.assertFalse(detect(parameter))
        self.namespace.update(
            _PT_AVAILABLE=False,
            Category=SimpleNamespace(IsBuiltInCategory=lambda value: value == "category"),
        )
        parameter.Definition.GetDataType = lambda: "category"
        self.assertTrue(detect(parameter))
        parameter.StorageType = 1
        self.assertFalse(detect(parameter))

    def test_choices_are_revit_allowed_ids_plus_current_reference(self):
        get_ids = Mock(return_value={2, 3})
        self.namespace.update(
            doc=SimpleNamespace(
                OwnerFamily=SimpleNamespace(GetFamilyTypeParameterValues=get_ids),
                GetElement=lambda identifier: {
                    2: "Family B : Type", 3: "Family A : Type", 9: "Current : Type",
                }[identifier]),
            OptionItem=lambda label, value: SimpleNamespace(Label=label, Value=value),
            _element_display_name=lambda element: element,
        )
        manager = SimpleNamespace(CurrentType=SimpleNamespace(AsElementId=lambda fp: 9))
        options = self.functions._family_type_value_options(manager, SimpleNamespace(Id=17))
        get_ids.assert_called_once_with(17)
        self.assertEqual([option.Value for option in options], [9, 3, 2])
        self.assertEqual(options[1].Label, "Family A : Type")

    def test_unset_family_type_has_a_selected_none_option(self):
        self.namespace.update(
            doc=SimpleNamespace(OwnerFamily=SimpleNamespace(
                GetFamilyTypeParameterValues=lambda identifier: [])),
            OptionItem=lambda label, value: SimpleNamespace(Label=label, Value=value),
        )
        manager = SimpleNamespace(CurrentType=SimpleNamespace(AsElementId=lambda fp: None))
        options = self.functions._family_type_value_options(manager, SimpleNamespace(Id=17))
        self.assertEqual(len(options), 1)
        self.assertEqual((options[0].Label, options[0].Value), ("<None>", -1))

    def test_reference_saves_use_id_overload_and_text_uses_existing_parser(self):
        transaction = Mock()
        transaction.return_value.__enter__ = Mock()
        transaction.return_value.__exit__ = Mock(return_value=False)
        parse = Mock(return_value=(True, ""))
        self.namespace.update(
            revit=SimpleNamespace(Transaction=transaction), _apply_initial_value=parse)
        window = SimpleNamespace(
            fm=SimpleNamespace(Set=Mock()), _can_edit_value=lambda item: True,
            _set_status=Mock())
        item = SimpleNamespace(Param=object(), Name="Nested")
        identifier = ElementId(5)
        self.assertTrue(self.functions._save_parameter_value(window, item, identifier))
        window.fm.Set.assert_called_once_with(item.Param, identifier)
        parse.assert_not_called()
        self.assertTrue(self.functions._save_parameter_value(window, item, "10 mm"))
        parse.assert_called_once_with(window.fm, item.Param, "10 mm")
        parse.return_value = (False, "Invalid value")
        self.assertFalse(self.functions._save_parameter_value(window, item, "bad"))
        self.assertIn("Invalid value", window._set_status.call_args[0][0])

    def test_locked_value_does_not_start_transaction(self):
        transaction = Mock()
        self.namespace["revit"] = SimpleNamespace(Transaction=transaction)
        window = SimpleNamespace(_can_edit_value=lambda item: False, _set_status=Mock())
        self.assertFalse(self.functions._save_parameter_value(window, object(), "42"))
        transaction.assert_not_called()

    def test_cancelled_and_unchanged_grid_edits_do_not_save(self):
        functions = load_functions(["on_value_cell_edit_ending"], self.namespace)
        self.namespace["DataGridEditAction"] = SimpleNamespace(Commit="commit")
        window = SimpleNamespace(_save_parameter_value=Mock())
        functions.on_value_cell_edit_ending(
            window, None, SimpleNamespace(EditAction="cancel"))
        self.namespace["_find_value_editor_host"] = lambda element: SimpleNamespace(
            Content=object(), Tag="unchanged")
        window._value_editor_value = lambda editor: "unchanged"
        functions.on_value_cell_edit_ending(
            window, None, SimpleNamespace(EditAction="commit", EditingElement=object()))
        window._save_parameter_value.assert_not_called()

    def test_failed_grid_edit_remains_in_edit_mode(self):
        functions = load_functions(["on_value_cell_edit_ending"], self.namespace)
        self.namespace.update(
            DataGridEditAction=SimpleNamespace(Commit="commit"),
            _find_value_editor_host=lambda element: SimpleNamespace(Content=object(), Tag="old"))
        window = SimpleNamespace(
            _value_editor_value=lambda editor: "invalid",
            _save_parameter_value=Mock(return_value=False))
        args = SimpleNamespace(
            EditAction="commit", EditingElement=object(), Row=SimpleNamespace(Item=object()),
            Cancel=False)
        functions.on_value_cell_edit_ending(window, None, args)
        self.assertTrue(args.Cancel)
        window._save_parameter_value.assert_called_once()


if __name__ == "__main__":
    unittest.main()
