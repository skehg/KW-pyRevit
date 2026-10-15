import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from filter_expression import (
    count_rules, evaluate_expression, group, parse_expression, rule,
    serialize_expression, validate_expression,
)


class ExpressionTests(unittest.TestCase):
    def test_nested_round_trip(self):
        text = ('AND([Width] >= 900, OR(CONTAINS([Comments], "External"), '
                '[Comments] = "Fire Rated"), NOT(STARTSWITH([Mark], "TEMP")))')
        node = parse_expression(text)
        validate_expression(node, ['Width', 'Comments', 'Mark'])
        self.assertEqual(node, parse_expression(serialize_expression(node)))
        self.assertEqual(4, count_rules(node))

    def test_all_conditions_round_trip(self):
        expressions = [
            '[A] = "x"', '[A] <> "x"', '[A] = 900', '[A] <> -0.5',
            '[A] > 1', '[A] < 2', '[A] >= 3', '[A] <= 4',
            'CONTAINS([A], "x")', 'STARTSWITH([A], "x")',
            'ENDSWITH([A], "x")', 'ISBLANK([A])', 'NOT(ISBLANK([A]))',
        ]
        for text in expressions:
            node = parse_expression(text)
            validate_expression(node, ['A'])
            self.assertEqual(node, parse_expression(serialize_expression(node)))

    def test_escaped_parameter_and_text_are_literal(self):
        node = rule('Name] and [Code', 'Equals', 'a,"b"\\c\n\u00e9')
        self.assertEqual(node, parse_expression(serialize_expression(node)))

    def test_case_insensitive_functions_and_extra_grouping(self):
        node = parse_expression(' and ( ([A] = "X"), not ( isblank([B]) ) ) ')
        self.assertEqual('AND', node['operator'])
        self.assertEqual(2, count_rules(node))

    def test_empty_is_no_filter(self):
        self.assertIsNone(parse_expression(' \n '))
        self.assertEqual('', serialize_expression(None))
        self.assertEqual(0, count_rules(None))

    def test_malformed_input_reports_position(self):
        expressions = [
            'AND()', 'OR()', 'NOT()', 'NOT([A] = 1, [A] = 2)',
            'AND([A] = 1,)', 'AND([A] = 1', '[A = 1',
            '[A] > "1"', '[A] = abc', '[A] = "unterminated',
            'CONTAINS([A], 1)', 'UNKNOWN([A])', '[A] = 1 junk',
            '[A] = 1,200', '[A] = 1.2.3', '[] = "x"',
            '__import__("os")', '[A] = "x" OR [B] = "y"',
        ]
        for text in expressions:
            with self.assertRaises(ValueError) as error:
                parse_expression(text)
            self.assertIn('character', str(error.exception))

    def test_unknown_parameter_and_invalid_numeric_value_are_errors(self):
        with self.assertRaises(ValueError):
            validate_expression(parse_expression('[Missing] = 1'), ['Width'])
        with self.assertRaises(ValueError):
            validate_expression(rule('Width', 'Equals', 'NaN', True), ['Width'])
        with self.assertRaises(ValueError):
            validate_expression(group(), ['Width'])

    def test_limits(self):
        for text in (
                ' ' * 20001,
                'NOT(' * 22 + '[A] = 1' + ')' * 22,
                'AND(' + ','.join(['[A] = 1'] * 501) + ')'):
            with self.assertRaises(ValueError):
                parse_expression(text)

    def test_boolean_truth_tables_with_unknown_numeric_values(self):
        values = {'T': True, 'F': False, 'U': None}

        def compare(value, node):
            if value is None:
                raise ValueError('Not numeric')
            return value

        for operator in ('AND', 'OR'):
            for first in values:
                for second in values:
                    results = [values[first], values[second]]
                    if operator == 'AND':
                        expected = False if False in results else (
                            None if None in results else True)
                    else:
                        expected = True if True in results else (
                            None if None in results else False)
                    node = group(operator, [rule(first), rule(second)])
                    self.assertIs(expected, evaluate_expression(node, values.get, compare))
        for key in values:
            expected = None if values[key] is None else not values[key]
            self.assertIs(expected, evaluate_expression(
                group('NOT', [rule(key)]), values.get, compare))

    def test_editor_draft_copy_does_not_mutate_active_expression(self):
        active = parse_expression('AND([A] = "x", [B] >= 900)')
        original = serialize_expression(active)
        draft = copy.deepcopy(active)
        draft['children'][0]['value'] = 'edited'
        draft['children'].pop()
        self.assertEqual(original, serialize_expression(active))


if __name__ == '__main__':
    unittest.main()
