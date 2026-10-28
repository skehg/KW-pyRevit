import os
import sys
import unittest

COMMAND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMMAND_DIR)
from token_pattern import (
    edited, expression, insert_item, label, parameter_slot, parse_pattern,
    serialize_pattern, token,
)
from test_preview import load_pattern_function


class TokenPatternTests(unittest.TestCase):
    def test_lossless_round_trip(self):
        patterns = [
            '', 'Door - Existing', '{val1}-{param1}-{count}',
            '{val1:4}', '{val2:end}', '{val1:end-1}', '{end-2:end}',
            '{end-3:end-1}', '{val3:+2}', '{end-3:+1}',
            '{val1:end|space~upper}', '{val1:4|-}', '{end-2:end|underscore}',
            '{val2:end|/}', '{val1~lower}', '{param1~title}', '{orig~sentence}',
            '{inc:val3:1}', '{inc:param1:-1}', '{seq:val3:-1}',
            '{inc:val1:0~upper}', '{param6}', '{COUNT~TITLE}',
            '  { orig ~ UPPER } / {seq:PARAM1:+02}  ',
        ]
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertEqual(pattern, serialize_pattern(parse_pattern(pattern)))

    def test_literals_are_explicit_and_preserve_whitespace(self):
        items = parse_pattern(' {val1} - {val2} (Existing) ')
        self.assertEqual(['text', 'source', 'text', 'source', 'text'],
                         [item['kind'] for item in items])
        self.assertEqual(' - ', items[2]['text'])
        self.assertEqual(' ', expression(token('text', text=' ')))

    def test_unsupported_patterns_are_not_simplified(self):
        for pattern in ('{unknown}', '{val0}', '{val1~random}', '{',
                        'x}', '{{val1}}', '{inc:end:2}', '{inc:val1:2.5}',
                        '{seq:param6:1}', '{val1:0}', '{val1| space }'):
            with self.subTest(pattern=pattern):
                with self.assertRaises(ValueError):
                    parse_pattern(pattern)

    def test_edit_only_canonicalizes_changed_chip(self):
        items = parse_pattern('{ val1 } - { PARAM1 ~ UPPER }')
        items[0] = edited(items[0], case='lower')
        self.assertEqual('{val1~lower} - { PARAM1 ~ UPPER }',
                         serialize_pattern(items))

    def test_all_supported_chip_kinds(self):
        items = [token('original'), token('source', start='val2'),
                 token('source', start='end-2', end='end', join='space', case='upper'),
                 token('parameter', slot=5), token('counter'), token('text', text=' / ')]
        pattern = '{orig}{val2}{end-2:end|space~upper}{param5}{count} / '
        self.assertEqual(pattern, serialize_pattern(items))

    def test_progression_and_negative_step(self):
        self.assertEqual('{inc:val1:2}', expression(token(
            'source', start='val1', operation='inc', step='2')))
        self.assertEqual('{seq:param2:-1~title}', expression(token(
            'parameter', slot=2, operation='seq', step='-1', case='title')))

    def test_progression_restrictions(self):
        invalid = [
            token('source', start='end', operation='inc', step='2'),
            token('source', start='val1', end='3', operation='inc', step='2'),
            token('source', start='val1', join='space', operation='seq', step='2'),
            token('source', start='val1', operation='inc', step='2.5'),
            token('original', operation='inc', step='2'),
            token('parameter', slot=6),
            token('text', text='{val1}'),
        ]
        for item in invalid:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    expression(item)

    def test_move_forward_backward_and_same_gap(self):
        items = parse_pattern('{val1}{val2}{val3}')
        result, selected = insert_item(items, None, 3, 0)
        self.assertEqual('{val2}{val3}{val1}', serialize_pattern(result))
        self.assertEqual(2, selected)
        result, selected = insert_item(items, None, 0, 2)
        self.assertEqual('{val3}{val1}{val2}', serialize_pattern(result))
        for gap in (1, 2):
            result, unused = insert_item(items, None, gap, 1)
            self.assertEqual(serialize_pattern(items), serialize_pattern(result))
        self.assertEqual('{val1}{val2}{val3}', serialize_pattern(items))

    def test_duplicate_is_independent(self):
        items = parse_pattern('{val1}')
        result, unused = insert_item(items, items[0], 1)
        result[1] = edited(result[1], case='upper')
        self.assertEqual('{val1}{val1~upper}', serialize_pattern(result))
        self.assertEqual('{val1}', serialize_pattern(items))

    def test_parameter_slot_reuse_and_limit(self):
        self.assertEqual(2, parameter_slot(['A', 'B', '', '', ''], 'B'))
        self.assertEqual(3, parameter_slot(['A', 'B', '', '', ''], 'C'))
        self.assertIsNone(parameter_slot(['A', 'B', 'C', 'D', 'E'], 'F'))

    def test_labels_are_position_based(self):
        item = token('source', start='val2')
        self.assertIn('Internal', label(item, ['Door', 'Internal']))
        self.assertIn('External', label(item, ['Door', 'External']))
        self.assertIn('missing', label(item, []))
        self.assertEqual('{val2}', expression(item))
        self.assertIn('Comments', label(token('parameter', slot=1), (), ['Comments']))
        self.assertIn('" "', label(token('text', text=' ')))

    def test_visual_increment_uses_existing_alphanumeric_engine(self):
        engine = load_pattern_function()
        pattern = expression(token('source', start='val1', operation='inc', step='2'))
        for original, expected in [('009', '011'), ('A', 'C'), ('Z', 'AB'), ('RM09', 'RM11')]:
            with self.subTest(original=original):
                result = engine['apply_pattern'](original, pattern, {},
                                                 tokenizer_func=lambda value: [value])
                self.assertEqual(expected, result)


if __name__ == '__main__':
    unittest.main()
