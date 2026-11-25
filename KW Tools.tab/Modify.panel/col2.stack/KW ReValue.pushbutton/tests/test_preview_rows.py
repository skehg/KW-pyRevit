import ast
import io
import os
import unittest


COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with io.open(os.path.join(COMMAND_DIR, 'script.py'), encoding='utf-8') as source:
    SCRIPT_TREE = ast.parse(source.read())


class ElementId(object):
    def __init__(self, value):
        self.Value = value


class ElementType(object):
    def __init__(self, element_id, name, family_name=None):
        self.Id = ElementId(element_id)
        self.Name = name
        self.FamilyName = family_name


class Instance(object):
    def __init__(self, element_type):
        self.element_type = element_type

    def GetTypeId(self):
        return self.element_type.Id


def load_preview_helpers(type_by_id):
    names = {
        '_preview_elements_for_mode', '_element_identity_tooltip',
    }
    module = ast.Module(body=[
        node for node in SCRIPT_TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ], type_ignores=[])
    ast.fix_missing_locations(module)

    def get_element_type(element):
        if isinstance(element, ElementType):
            return element
        try:
            return type_by_id.get(element.GetTypeId().Value)
        except AttributeError:
            return None

    class Document(object):
        def GetElement(self, element_id):
            return type_by_id.get(element_id.Value)

    namespace = {
        'ElementType': ElementType,
        'doc': Document(),
        'element_id_value': lambda element_id: element_id.Value,
        '_get_element_type': get_element_type,
        '_safe_type_name': lambda element_type: element_type.Name,
    }
    exec(compile(module, '<preview helpers>', 'exec'), namespace)
    return namespace


class PreviewRowTests(unittest.TestCase):
    def setUp(self):
        self.type_a = ElementType(10, 'Same Name', 'Family A')
        self.type_b = ElementType(20, 'Same Name', 'Family B')
        self.helpers = load_preview_helpers({
            10: self.type_a,
            20: self.type_b,
        })

    def test_type_mode_deduplicates_by_type_id_and_preserves_selection_order(self):
        elements = [
            Instance(self.type_a),
            Instance(self.type_b),
            Instance(self.type_a),
            self.type_a,
        ]

        result = self.helpers['_preview_elements_for_mode'](elements, False)

        self.assertEqual([self.type_a, self.type_b], result)

    def test_instance_mode_keeps_all_selected_elements(self):
        elements = [Instance(self.type_a), Instance(self.type_a)]

        result = self.helpers['_preview_elements_for_mode'](elements, True)

        self.assertEqual(elements, result)

    def test_identity_tooltip_uses_family_and_type_for_types_and_instances(self):
        tooltip = self.helpers['_element_identity_tooltip']

        self.assertEqual('Family A : Same Name', tooltip(self.type_a, ''))
        self.assertEqual(
            'Family A : Same Name', tooltip(Instance(self.type_a), 'Instance'))
        self.assertEqual(
            'Family B : Same Name', tooltip(Instance(self.type_b), 'Instance'))

    def test_identity_tooltip_falls_back_when_element_has_no_type(self):
        class UntypedElement(object):
            pass

        self.assertEqual(
            'View Name',
            self.helpers['_element_identity_tooltip'](
                UntypedElement(), 'View Name'))


if __name__ == '__main__':
    unittest.main()
