import ast
import os
import sys
import types
import unittest
from unittest import mock

COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)
from filter_expression import evaluate_expression, parse_expression


class Storage(object):
    String = 'string'
    Double = 'double'
    Integer = 'integer'
    ElementId = 'reference'


class Parameter(object):
    StorageType = Storage.ElementId
    HasValue = True
    IsReadOnly = False

    def __init__(self, name, reference_id, display=None):
        self.Definition = types.SimpleNamespace(Name=name)
        self.reference_id = reference_id
        self.display = display

    def AsElementId(self):
        return self.reference_id

    def AsValueString(self):
        return self.display


class Element(object):
    def __init__(self, parameters=(), element_type=None):
        self.Parameters = parameters
        self.element_type = element_type

    def LookupParameter(self, name):
        return next((parameter for parameter in self.Parameters
                     if parameter.Definition.Name == name), None)


class ReferenceParameterTests(unittest.TestCase):
    def setUp(self):
        path = os.path.join(COMMAND_DIR, 'script.py')
        with open(path, encoding='utf-8') as source:
            tree = ast.parse(source.read())
        selected = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in (
                    '_elementid_param_to_text', 'collect_all_parameters',
                    '_safe_set_parameter_value'):
                selected.append(node)
            elif isinstance(node, ast.ClassDef) and node.name == 'ReValueDialog':
                selected.extend(method for method in node.body
                                if isinstance(method, ast.FunctionDef) and method.name in (
                                    'get_param_value', 'get_selected_param_values'))
        tree.body = selected
        self.document = mock.Mock()
        self.document.GetElement.side_effect = lambda key: {
            100: types.SimpleNamespace(Name='Ground Floor'),
            101: types.SimpleNamespace(Name='First Floor'),
            102: types.SimpleNamespace(Name=''),
            2 ** 40: types.SimpleNamespace(Name='Large ID Level'),
        }.get(key)
        self.namespace = dict(
            StorageType=Storage, doc=self.document, element_id_value=lambda value: value,
            _safe_element_name=lambda element: element.Name,
            _get_element_type=lambda element: element.element_type,
        )
        exec(compile(tree, path, 'exec'), self.namespace)
        self.dialog = types.SimpleNamespace(is_instance_mode=True)
        self.dialog.get_param_value = types.MethodType(
            self.namespace['get_param_value'], self.dialog)
        self.wall = Element([
            Parameter('Base Constraint', 100),
            Parameter('Top Constraint', 101),
        ], Element())

    def text(self, parameter):
        return self.namespace['_elementid_param_to_text'](parameter)

    def test_revit_display_text_and_special_values_are_preserved(self):
        self.assertEqual('Unconnected', self.text(
            Parameter('Top Constraint', -1, 'Unconnected')))
        self.assertEqual('Revit display', self.text(
            Parameter('Level', 100, 'Revit display')))
        self.document.GetElement.assert_not_called()

    def test_reference_resolves_to_name_not_numeric_id(self):
        self.assertEqual('Ground Floor', self.text(Parameter('Level', 100)))

    def test_missing_unnamed_and_large_ids(self):
        self.assertEqual('999', self.text(Parameter('Level', 999)))
        self.assertEqual('102', self.text(Parameter('Level', 102)))
        self.assertEqual('Large ID Level', self.text(Parameter('Level', 2 ** 40)))

    def test_unset_negative_and_null_references_are_blank(self):
        for reference_id in (-1, -2, None):
            self.assertEqual('', self.text(Parameter('Top Constraint', reference_id)))
        self.document.GetElement.assert_not_called()

    def test_wall_floor_roof_ceiling_and_localized_names_are_discovered(self):
        for names in (('Base Constraint', 'Top Constraint'), ('Level',),
                      ('Base Level',), ('Niveau',)):
            element = Element([Parameter(name, 100) for name in names], Element())
            available, examples = self.namespace['collect_all_parameters']([element], True)
            self.assertEqual(sorted(names), available)
            self.assertEqual(dict((name, 'Ground Floor') for name in names), examples)

    def test_type_mode_does_not_add_instance_constraints(self):
        available, _ = self.namespace['collect_all_parameters']([self.wall], False)
        self.assertEqual([], available)
        self.dialog.is_instance_mode = False
        self.assertEqual('', self.dialog.get_param_value(self.wall, 'Base Constraint'))

    def test_reference_on_type_available_in_both_modes(self):
        element = Element([], Element([Parameter('Reference', 101)]))
        for instance_mode in (False, True):
            self.dialog.is_instance_mode = instance_mode
            available, _ = self.namespace['collect_all_parameters']([element], instance_mode)
            self.assertIn('Reference', available)
            self.assertEqual('First Floor', self.dialog.get_param_value(element, 'Reference'))

    def test_tokens_and_filter_expressions_use_same_level_names(self):
        self.dialog.param_combos = [
            types.SimpleNamespace(SelectedItem='Base Constraint'),
            types.SimpleNamespace(SelectedItem='Top Constraint'),
            types.SimpleNamespace(SelectedItem=''),
        ]
        values = self.namespace['get_selected_param_values'](self.dialog, self.wall)
        self.assertEqual(['Ground Floor', 'First Floor', ''], values)
        expression = parse_expression(
            'AND([Base Constraint] = "Ground Floor", '
            '[Top Constraint] = "First Floor")')
        result = evaluate_expression(
            expression,
            lambda name: self.dialog.get_param_value(self.wall, name),
            lambda value, rule: value == rule['value'])
        self.assertTrue(result)

    def test_instance_reference_takes_precedence_over_type_reference(self):
        self.wall.element_type = Element([Parameter('Base Constraint', 101)])
        self.assertEqual('Ground Floor',
                         self.dialog.get_param_value(self.wall, 'Base Constraint'))

    def test_existing_scope_box_and_scalar_discovery_preserved(self):
        scope = Parameter('Scope Box', 100, 'Scope A')
        string = Parameter('Comments', None)
        string.StorageType = Storage.String
        string.AsString = lambda: 'Example'
        number = Parameter('Offset', None, '900 mm')
        number.StorageType = Storage.Double
        count = Parameter('Count', None, '3')
        count.StorageType = Storage.Integer
        element = Element([scope, string, number, count], Element())
        available, examples = self.namespace['collect_all_parameters']([element], True)
        self.assertEqual(['Comments', 'Count', 'Offset', 'Scope Box'], available)
        self.assertEqual('Scope A', examples['Scope Box'])
        self.assertEqual('Example', examples['Comments'])
        self.assertEqual('900 mm', examples['Offset'])

    def test_reference_cannot_be_written_by_revalue(self):
        parameter = mock.Mock(StorageType=Storage.ElementId, IsReadOnly=False)
        self.namespace['_find_parameter_for_write'] = lambda *args: parameter
        self.assertFalse(self.namespace['_safe_set_parameter_value'](
            self.wall, 'Base Constraint', 'First Floor', True))
        parameter.Set.assert_not_called()
        parameter.SetValueString.assert_not_called()


if __name__ == '__main__':
    unittest.main()
