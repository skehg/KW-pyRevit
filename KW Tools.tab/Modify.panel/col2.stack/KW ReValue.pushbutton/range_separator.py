"""Shared quoted separator syntax for the engine and visual editor."""
import json


NAMED_SEPARATORS = {'space': ' ', 'hyphen': '-', 'underscore': '_'}


def decode_separator(value):
    value = value.strip()
    if value.startswith('"'):
        try:
            result = json.loads(value)
        except ValueError as ex:
            raise ValueError('Invalid quoted range separator: {}'.format(ex))
        if not isinstance(result, type(u'')):
            raise ValueError('A quoted range separator must be a JSON string.')
        return result
    return NAMED_SEPARATORS.get(value, value) if value else None


def encode_separator(value, quoted=False):
    if quoted or value != value.strip() or any(char in value for char in '"\\~{}'):
        # Braces must not terminate the enclosing pattern placeholder.
        return json.dumps(value, ensure_ascii=True).replace('{', r'\u007b').replace('}', r'\u007d')
    return value


def split_case(expression):
    """Split only a case suffix outside a quoted separator."""
    pipe = expression.find('|')
    quote_start = -1
    if pipe >= 0:
        rest = expression[pipe + 1:]
        if rest.lstrip().startswith('"'):
            quote_start = pipe + 1 + len(rest) - len(rest.lstrip())
    inside = False
    escaped = False
    suffix = -1
    for index, char in enumerate(expression):
        if inside:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                inside = False
        elif index == quote_start:
            inside = True
        elif char == '~':
            suffix = index
    if inside:
        raise ValueError('Invalid quoted range separator: missing closing quote.')
    if suffix >= 0:
        return expression[:suffix].strip(), expression[suffix + 1:].strip().lower()
    return expression, None
