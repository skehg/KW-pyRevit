"""Bounded, non-executable parameter filter expressions (IronPython 2.7)."""
import json
import re
from decimal import Decimal, InvalidOperation


COMPARISONS = {
    '=': 'Equals', '<>': 'Does not equal', '>': 'Greater than',
    '<': 'Less than', '>=': 'Greater than or equal to',
    '<=': 'Less than or equal to',
}
FUNCTIONS = {
    'CONTAINS': 'Contains', 'STARTSWITH': 'Starts with',
    'ENDSWITH': 'Ends with', 'ISBLANK': 'Is blank',
}
NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')


def rule(parameter='', condition='Equals', value='', numeric=False):
    return dict(kind='rule', parameter=parameter, condition=condition,
                value=value, numeric=numeric)


def group(operator='AND', children=None):
    return dict(kind='group', operator=operator,
                children=[] if children is None else children)


class ExpressionParser(object):
    def __init__(self, text):
        self.text = text
        self.position = 0
        self.nodes = 0

    def error(self, message):
        raise ValueError('{} at character {}.'.format(message, self.position + 1))

    def space(self):
        while self.position < len(self.text) and self.text[self.position].isspace():
            self.position += 1

    def take(self, token):
        self.space()
        if self.text.startswith(token, self.position):
            self.position += len(token)
            return True
        return False

    def require(self, token):
        if not self.take(token):
            self.error("Expected '{}'".format(token))

    def parameter(self):
        self.require('[')
        parts = []
        while self.position < len(self.text):
            char = self.text[self.position]
            self.position += 1
            if char == ']':
                if self.position < len(self.text) and self.text[self.position] == ']':
                    self.position += 1
                    parts.append(']')
                else:
                    name = ''.join(parts)
                    if not name.strip():
                        self.error('Parameter name cannot be blank')
                    return name
            else:
                parts.append(char)
        self.error("Missing closing ']'")

    def value(self):
        self.space()
        if self.position < len(self.text) and self.text[self.position] == '"':
            try:
                value, length = json.JSONDecoder().raw_decode(self.text[self.position:])
            except ValueError:
                self.error('Invalid quoted text (use JSON escapes for quotes and backslashes)')
            self.position += length
            return value, False
        match = NUMBER.match(self.text, self.position)
        if not match:
            self.error('Expected quoted text or a decimal number')
        self.position = match.end()
        return match.group(), True

    def expression(self, depth=0):
        self.space()
        self.nodes += 1
        if depth > 20 or self.nodes > 500:
            self.error('Filter exceeds 20 nesting levels or 500 conditions/groups')
        if self.take('('):
            node = self.expression(depth + 1)
            self.require(')')
            return node
        if self.position < len(self.text) and self.text[self.position] == '[':
            parameter = self.parameter()
            for symbol in ('>=', '<=', '<>', '=', '>', '<'):
                if self.take(symbol):
                    value, numeric = self.value()
                    if symbol in ('>', '<', '>=', '<=') and not numeric:
                        self.error('Ordering comparisons require an unquoted number')
                    return rule(parameter, COMPARISONS[symbol], value, numeric)
            self.error('Expected =, <>, >, <, >= or <=')
        name_match = re.match(r'[A-Za-z]+', self.text[self.position:])
        if not name_match:
            self.error('Expected a condition or AND, OR, NOT')
        name = name_match.group().upper()
        self.position += len(name_match.group())
        self.require('(')
        if name in ('AND', 'OR', 'NOT'):
            children = [self.expression(depth + 1)]
            while self.take(','):
                children.append(self.expression(depth + 1))
            self.require(')')
            if name == 'NOT' and len(children) != 1:
                self.error('NOT requires exactly one condition or group')
            return group(name, children)
        if name not in FUNCTIONS:
            self.error('Unknown function {}'.format(name))
        parameter = self.parameter()
        value = ''
        if name != 'ISBLANK':
            self.require(',')
            value, numeric = self.value()
            if numeric:
                self.error('Text functions require a quoted value')
        self.require(')')
        return rule(parameter, FUNCTIONS[name], value)


def parse_expression(text):
    if len(text) > 20000:
        raise ValueError('Filter expression exceeds 20,000 characters.')
    if not text.strip():
        return None
    parser = ExpressionParser(text)
    node = parser.expression()
    parser.space()
    if parser.position != len(text):
        parser.error('Unexpected text')
    return node


def serialize_expression(node):
    if node is None:
        return ''
    if node['kind'] == 'group':
        return '{}({})'.format(node['operator'], ', '.join(
            serialize_expression(child) for child in node['children']))
    parameter = '[{}]'.format(node['parameter'].replace(']', ']]'))
    condition = node['condition']
    if condition == 'Is not blank':
        return 'NOT(ISBLANK({}))'.format(parameter)
    if condition == 'Is blank':
        return 'ISBLANK({})'.format(parameter)
    value = node['value'] if node['numeric'] else json.dumps(node['value'], ensure_ascii=True)
    for symbol, label in COMPARISONS.items():
        if label == condition:
            return '{} {} {}'.format(parameter, symbol, value)
    for function, label in FUNCTIONS.items():
        if label == condition:
            return '{}({}, {})'.format(function, parameter, value)
    raise ValueError('Unknown condition: {}'.format(condition))


def validate_expression(node, parameters):
    if node is None:
        return
    if node['kind'] == 'group':
        if not node['children']:
            raise ValueError('Add a condition to each group, or remove the empty group.')
        for child in node['children']:
            validate_expression(child, parameters)
        return
    if node['parameter'] not in parameters:
        raise ValueError("Parameter '{}' is unavailable in this mode.".format(node['parameter']))
    if node['numeric']:
        if not NUMBER.match(node['value']) or NUMBER.match(node['value']).end() != len(node['value']):
            raise ValueError('Numeric conditions require a decimal number (e.g. 1200.5).')
        try:
            if not Decimal(node['value']).is_finite():
                raise ValueError('Numeric values must be finite.')
        except InvalidOperation:
            raise ValueError('Invalid numeric value.')


def count_rules(node):
    if node is None:
        return 0
    if node['kind'] == 'rule':
        return 1
    return sum(count_rules(child) for child in node['children'])


def evaluate_expression(node, get_value, compare):
    """Unknown numeric values stay unknown under NOT, not accidentally included."""
    if node is None:
        return True
    if node['kind'] == 'rule':
        try:
            return compare(get_value(node['parameter']), node)
        except ValueError:
            return None
    results = [evaluate_expression(child, get_value, compare) for child in node['children']]
    if node['operator'] == 'NOT':
        return None if results[0] is None else not results[0]
    if node['operator'] == 'AND':
        if False in results:
            return False
        return None if None in results else True
    if True in results:
        return True
    return None if None in results else False
