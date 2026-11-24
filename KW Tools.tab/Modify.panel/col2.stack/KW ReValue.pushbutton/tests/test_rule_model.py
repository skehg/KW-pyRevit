import json
import os
import sys
import unittest


COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)

from rule_model import (
    CASES, default_composition, edit_operation, insert_operation,
    operation, original_composition, serialize_composition,
    deserialize_composition, validate_composition,
)


class RuleModelTests(unittest.TestCase):
    def test_default_and_original_compositions(self):
        default = default_composition()
        validate_composition(default)
        self.assertEqual('source', default['operations'][0]['kind'])
        self.assertEqual({'direction': 'start', 'index': 1},
                         default['operations'][0]['start'])
        validate_composition(original_composition())
        self.assertEqual('original',
                         original_composition()['operations'][0]['kind'])

    def test_supported_operations_and_literal_text(self):
        operations = [
            operation('source',
                      start={'direction': 'end', 'index': 2},
                      end={'direction': 'following', 'count': 2},
                      separator=' - '),
            operation('parameter', parameter='Comments', case='upper'),
            operation('original', case='sentence'),
            operation('counter', start='A', increment=1, case='lower'),
            operation('text', text='{literal} " \\\\ '),
        ]
        composition = {'version': 1, 'operations': operations}
        validate_composition(composition)
        self.assertEqual('{literal} " \\\\ ', operations[-1]['text'])

    def test_position_shapes_and_endpoints(self):
        for position in (
                {'direction': 'start', 'index': 1},
                {'direction': 'end', 'index': 3},
                {'direction': 'following', 'count': 0},
                {'direction': 'following', 'count': 4}):
            item = operation('source', start=position)
            validate_composition({'version': 1, 'operations': [item]})

    def test_case_and_progression_validation(self):
        for case in CASES:
            validate_composition({
                'version': 1,
                'operations': [operation('parameter', parameter='Mark', case=case)],
            })
        validate_composition({
            'version': 1,
            'operations': [operation(
                'source',
                progression={'kind': 'inc', 'step': -2})],
        })
        validate_composition({
            'version': 1,
            'operations': [operation(
                'parameter', parameter='Mark',
                progression={'kind': 'seq', 'step': 1})],
        })

    def test_validation_rejects_bad_operations(self):
        bad = [
            {'version': 1, 'operations': [{'kind': 'unknown'}]},
            {'version': 1, 'operations': [operation('parameter', parameter='')]},
            {'version': 1, 'operations': [operation(
                'source', start={'direction': 'start', 'index': 0})]},
            {'version': 1, 'operations': [operation(
                'source', start={'direction': 'sideways', 'index': 1})]},
            {'version': 1, 'operations': [operation(
                'source', start={'direction': 'start', 'index': 1},
                end={'direction': 'following', 'count': -1})]},
            {'version': 1, 'operations': [operation(
                'parameter', parameter='Mark', case='sideways')]},
            {'version': 1, 'operations': [operation(
                'original', progression={'kind': 'inc', 'step': 1})]},
            {'version': 1, 'operations': [operation(
                'text', text=3)]},
            {'version': 1, 'operations': []},
        ]
        for composition in bad:
            with self.subTest(composition=composition):
                with self.assertRaises(ValueError):
                    validate_composition(composition)
        with self.assertRaises(ValueError):
            validate_composition({'version': 2, 'operations': [operation('original')]})

    def test_edit_duplicate_insert_move_and_copy_independence(self):
        items = [operation('source'), operation('text', text='-')]
        composition = {'version': 1, 'operations': items}
        edited = edit_operation(items[0], case='upper')
        self.assertEqual('upper', edited['case'])
        self.assertEqual('Unchanged', items[0]['case'])

        duplicated, selected = insert_operation(items, items[0], 2)
        self.assertEqual(2, selected)
        duplicated[-1] = edit_operation(duplicated[-1], case='lower')
        self.assertEqual('Unchanged', items[0]['case'])

        moved, selected = insert_operation(items, None, 0, 1)
        self.assertEqual(0, selected)
        self.assertEqual('text', moved[0]['kind'])

    def test_json_round_trip_and_schema_rejection(self):
        composition = {'version': 1, 'operations': [
            operation('source',
                      start={'direction': 'start', 'index': 1},
                      end={'direction': 'end', 'index': 1},
                      separator=' '),
            operation('parameter', parameter='Mark', case='upper'),
        ]}
        raw = serialize_composition(composition)
        loaded = deserialize_composition(raw)
        self.assertEqual(composition, loaded)
        self.assertIsInstance(json.loads(raw), dict)
        with self.assertRaises(ValueError):
            deserialize_composition('{"version":3,"operations":[]}')


if __name__ == '__main__':
    unittest.main()
