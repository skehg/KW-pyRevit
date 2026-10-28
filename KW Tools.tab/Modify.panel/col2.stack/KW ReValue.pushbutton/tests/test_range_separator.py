import unittest

from test_preview import load_pattern_function
from token_pattern import edited, expression, parse_pattern, serialize_pattern, token
from range_separator import decode_separator, encode_separator


class QuotedSeparatorTests(unittest.TestCase):
    def setUp(self):
        self.engine = load_pattern_function()

    def evaluate(self, pattern):
        return self.engine['apply_pattern'](
            'a_b_c', pattern, {}, tokenizer_func=lambda value: value.split('_'))

    def test_exact_custom_separators_roundtrip_and_evaluation(self):
        for separator in (' - ', '"', ' " ', '\\', "'", '~upper', '|',
                          '{}', 'space', '', '\t', u'\u2014'):
            with self.subTest(separator=separator):
                item = token('source', start='val1', end='3',
                             join=separator, join_quoted=True)
                pattern = expression(item)
                parsed = parse_pattern(pattern)
                self.assertEqual(separator, parsed[0]['join'])
                self.assertEqual(pattern, serialize_pattern(parsed))
                self.assertEqual(separator.join(('a', 'b', 'c')), self.evaluate(pattern))
                changed = expression(edited(parsed[0], case='upper'))
                self.assertEqual(separator.join(('a', 'b', 'c')).upper(), self.evaluate(changed))

    def test_spaces_and_quotes_are_encoded_automatically(self):
        self.assertEqual('{val1:3|" - "}', expression(token(
            'source', start='val1', end='3', join=' - ')))
        self.assertEqual(r'{val1:3|"\""}', expression(token(
            'source', start='val1', end='3', join='"')))
        self.assertEqual('a " b " c', self.evaluate(r'{val1:3|" \" "}'))
        self.assertEqual('a\\b\\c', self.evaluate(r'{val1:3|"\\"}'))

    def test_existing_unquoted_separators_are_unchanged(self):
        for separator, result in [('space', 'a b c'), ('hyphen', 'a-b-c'),
                                  ('underscore', 'a_b_c'), ('/', 'a/b/c')]:
            pattern = '{val1:3|' + separator + '}'
            self.assertEqual(result, self.evaluate(pattern))
            self.assertEqual(pattern, serialize_pattern(parse_pattern(pattern)))

    def test_invalid_quoted_syntax_is_explicit_error(self):
        for text in ('"unterminated', r'"\q"', '"a" trailing', '"a" "b"'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    decode_separator(text)
                with self.assertRaises(ValueError):
                    parse_pattern('{val1:3|' + text + '}')
                with self.assertRaises(ValueError):
                    self.evaluate('{val1:3|' + text + '}')

    def test_quoted_tilde_does_not_become_a_case_modifier(self):
        self.assertEqual('a~upperb~upperc', self.evaluate('{val1:3|"~upper"}'))
        self.assertEqual('A~UPPERB~UPPERC', self.evaluate('{val1:3|"~upper"~upper}'))

    def test_quoted_separator_is_not_double_escaped_on_edit(self):
        pattern = r'{val1:3|" \" "}'
        item = parse_pattern(pattern)[0]
        self.assertEqual(pattern, expression(edited(item)))

    def test_bad_separator_does_not_crash_sequence_seed_collection(self):
        refs = self.engine['_sequence_source_refs']
        self.assertEqual([], refs('{val1:3|"unterminated}'))
        self.assertEqual(['val1'], refs('{ seq : val1 : 2 }-{val1:3|" - "}'))


if __name__ == '__main__':
    unittest.main()
