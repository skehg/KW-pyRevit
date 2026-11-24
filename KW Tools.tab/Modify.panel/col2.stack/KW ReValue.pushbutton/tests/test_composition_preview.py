import ast
import io
import os
import sys
import unittest


COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)

from rule_model import operation, validate_composition

with io.open(os.path.join(COMMAND_DIR, 'script.py'), encoding='utf-8') as source:
    SCRIPT_TREE = ast.parse(source.read())


def load_evaluator():
    names = {
        'evaluate_composition', '_resolve_source_window',
        '_resolve_progression_source', '_increment_value',
        '_alpha_to_int', '_int_to_alpha', 'apply_case_conversion',
        '_composition_uses_counter', '_sequence_source_refs',
        'build_counter_generator',
    }
    module = ast.Module(body=[
        node for node in SCRIPT_TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        're': __import__('re'),
        'basestring': str,
        'validate_composition': validate_composition,
        'NUMERIC_REGEX': __import__('re').compile(r'^\d+$'),
        'ALPHA_REGEX': __import__('re').compile(r'^[A-Za-z]+$'),
        'MIXED_SUFFIX_NUM_REGEX': __import__('re').compile(r'^(.*?)(\d+)$'),
        'SIGNED_NUMERIC_REGEX': __import__('re').compile(r'^-?\d+$'),
        'SIGNED_SUFFIX_NUM_REGEX': __import__('re').compile(r'^(.*?)(-?\d+)$'),
    }
    exec(compile(module, '<composition evaluator>', 'exec'), namespace)
    return namespace


class CompositionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.engine = load_evaluator()

    def evaluate(self, operations, source='a-b-c', params=None, seeds=None, row=0):
        composition = {'version': 1, 'operations': operations}
        warnings = []
        result = self.engine['evaluate_composition'](
            source, composition, params or {}, lambda value: value.split('-'),
            seeds or {}, row, warnings)
        return result, warnings

    def test_range_join_and_literal_braces(self):
        operations = [
            operation('text', text='{'),
            operation('source',
                      start={'direction': 'start', 'index': 1},
                      end={'direction': 'start', 'index': 3},
                      separator=' '),
            operation('text', text='}'),
        ]
        self.assertEqual(('{a b c}', []), self.evaluate(operations))

    def test_original_parameter_counter_and_text(self):
        operations = [
            operation('original'),
            operation('text', text='-'),
            operation('parameter', parameter='Mixed Parameter', case='upper'),
            operation('text', text='-'),
            operation('counter', start='AbC', increment=0, case='lower'),
        ]
        params = {
            'orig': 'source',
            'Mixed Parameter': 'mixed',
            'counter': 'AbC',
        }
        self.assertEqual(('source-MIXED-abc', []),
                         self.evaluate(operations, 'source', params))

    def test_end_and_following_positions(self):
        operations = [
            operation('source',
                      start={'direction': 'end', 'index': 2},
                      end={'direction': 'end', 'index': 1},
                      separator=' '),
        ]
        self.assertEqual(('b c', []), self.evaluate(operations))
        operations = [
            operation('source',
                      start={'direction': 'start', 'index': 2},
                      end={'direction': 'following', 'count': 1},
                      separator='/'),
        ]
        self.assertEqual(('b/c', []), self.evaluate(operations))

    def test_numeric_alpha_prefixed_and_negative_progression(self):
        operations = [
            operation('source',
                      start={'direction': 'start', 'index': 1},
                      progression={'kind': 'inc', 'step': 2}),
        ]
        for source, expected in [('009', '011'), ('A', 'C'), ('Z', 'AB'),
                                 ('RM09', 'RM11')]:
            with self.subTest(source=source):
                self.assertEqual((expected, []), self.evaluate(operations, source))

        operations[0]['progression'] = {'kind': 'inc', 'step': -2}
        self.assertEqual(('RM07', []), self.evaluate(operations, 'RM09'))

    def test_sequence_seed_and_blank_warning(self):
        operations = [
            operation('source',
                      start={'direction': 'start', 'index': 1},
                      progression={'kind': 'seq', 'step': 2}),
        ]
        result, warnings = self.evaluate(
            operations, 'A-b-c', seeds={'val1': 'A'}, row=2)
        self.assertEqual('E', result)
        self.assertEqual([], warnings)

        result, warnings = self.evaluate(
            operations, '???-b-c', seeds={'val1': ''}, row=2)
        self.assertEqual('???', result)
        self.assertEqual(1, len(warnings))

    def test_missing_source_position_is_blank(self):
        operations = [
            operation('source',
                      start={'direction': 'start', 'index': 5}),
        ]
        self.assertEqual(('', []), self.evaluate(operations, 'a-b-c'))

    def test_repeated_counters_use_one_supplied_row_value(self):
        operations = [
            operation('counter', start='RM03', increment=1),
            operation('text', text='/'),
            operation('counter', start='RM03', increment=1),
        ]
        params = {'counter': 'RM03'}
        self.assertEqual(('RM03/RM03', []),
                         self.evaluate(operations, 'a-b-c', params))


if __name__ == '__main__':
    unittest.main()
