"""Structured output-composition model for KW ReValue."""
import copy
import json
import re

try:
    integer_types = (int, long)
except NameError:
    integer_types = (int,)
try:
    string_types = (basestring,)
except NameError:
    string_types = (str,)


CASES = ('Unchanged', 'upper', 'lower', 'title', 'sentence')
CASE_LABELS = {
    'Unchanged': 'Unchanged',
    'upper': 'UPPER',
    'lower': 'lower',
    'title': 'Title Case',
    'sentence': 'Sentence case',
}
OPERATION_KINDS = ('source', 'parameter', 'original', 'counter', 'text')
DEFAULT_PARAMETER_DELIMITERS = r'-_/,\|'


def operation(kind, **values):
    item = {'kind': kind, 'case': 'Unchanged'}
    item.update(values)
    if kind == 'text':
        item.setdefault('text', '')
    if kind == 'source':
        item.setdefault('selections', [
            selection('single', position={'direction': 'start', 'index': 1}),
        ])
        item.setdefault('separator', '')
        item.setdefault('progression', None)
    elif kind == 'parameter':
        item.setdefault('parameter', '')
        item.setdefault('tokenize', False)
        item.setdefault('delimiters', DEFAULT_PARAMETER_DELIMITERS)
        item.setdefault('selections', [
            selection('single', position={'direction': 'start', 'index': 1}),
        ])
        item.setdefault('separator', '')
        item.setdefault('progression', None)
    elif kind == 'counter':
        item.setdefault('start', 'A')
        item.setdefault('increment', 1)
        item.setdefault('progression', None)
    elif kind == 'original':
        item.setdefault('progression', None)
    return item


def selection(kind, **values):
    if kind == 'range':
        return {
            'kind': 'range',
            'start': values.get('start', {'direction': 'start', 'index': 1}),
            'end': values.get('end', {'direction': 'end', 'index': 1}),
        }
    if kind == 'single':
        return {
            'kind': 'single',
            'position': values.get('position', {'direction': 'start', 'index': 1}),
        }
    raise ValueError('Selection kind must be range or single.')


def default_composition():
    return {
        'version': 1,
        'operations': [operation('source')],
    }


def original_composition():
    return {
        'version': 1,
        'operations': [operation('original')],
    }


def deep_copy_composition(composition):
    return copy.deepcopy(composition)


def serialize_composition(composition):
    validate_composition(composition)
    return json.dumps(composition, ensure_ascii=False)


def deserialize_composition(raw):
    if raw is None:
        return default_composition()
    if isinstance(raw, dict):
        composition = deep_copy_composition(raw)
    else:
        try:
            composition = json.loads(raw)
        except Exception as ex:
            raise ValueError('Invalid structured composition JSON: {}'.format(ex))
    validate_composition(composition)
    return deep_copy_composition(composition)


def _validate_position(position, label):
    if not isinstance(position, dict):
        raise ValueError('{} must be a position dictionary.'.format(label))
    direction = position.get('direction')
    if direction in ('start', 'end'):
        index = position.get('index')
        if not isinstance(index, integer_types) or isinstance(index, bool) or index < 1:
            raise ValueError('{} index must be a positive 1-based integer.'.format(label))
    elif direction == 'following':
        count = position.get('count')
        if not isinstance(count, integer_types) or isinstance(count, bool) or count < 0:
            raise ValueError('{} Following count must be zero or greater.'.format(label))
    else:
        raise ValueError('{} has an invalid direction.'.format(label))


def _validate_progression(progression, label):
    if progression is None:
        return
    if not isinstance(progression, dict):
        raise ValueError('{} progression must be a dictionary or null.'.format(label))
    kind = progression.get('kind')
    step = progression.get('step')
    if kind not in ('inc', 'seq'):
        raise ValueError('{} progression kind must be inc or seq.'.format(label))
    if not isinstance(step, integer_types) or isinstance(step, bool):
        raise ValueError('{} progression step must be an integer.'.format(label))


def _validate_selections(selections, label):
    if not isinstance(selections, list) or not selections:
        raise ValueError('{} must be a non-empty list.'.format(label))
    for selection_index, selection in enumerate(selections):
        selection_label = '{} selection {}'.format(label, selection_index + 1)
        if not isinstance(selection, dict):
            raise ValueError('{} must be a dictionary.'.format(selection_label))
        selection_kind = selection.get('kind')
        if selection_kind == 'range':
            _validate_position(selection.get('start'), selection_label + ' start')
            _validate_position(selection.get('end'), selection_label + ' end')
        elif selection_kind == 'single':
            _validate_position(selection.get('position'), selection_label + ' position')
        else:
            raise ValueError('{} has an invalid kind.'.format(selection_label))


def validate_composition(composition):
    if not isinstance(composition, dict):
        raise ValueError('Composition must be a dictionary.')
    if composition.get('version') != 1:
        raise ValueError('Unsupported composition schema version.')
    operations = composition.get('operations')
    if not isinstance(operations, list):
        raise ValueError('Composition operations must be a list.')
    if not operations:
        raise ValueError('Composition must contain at least one operation.')
    for index, item in enumerate(operations):
        label = 'Operation {}'.format(index + 1)
        if not isinstance(item, dict):
            raise ValueError('{} must be a dictionary.'.format(label))
        kind = item.get('kind')
        if kind not in OPERATION_KINDS:
            raise ValueError('{} has invalid operation kind.'.format(label))
        case = item.get('case', 'Unchanged')
        if case not in CASES:
            raise ValueError('{} has invalid case setting.'.format(label))
        if kind == 'text':
            if not isinstance(item.get('text'), string_types):
                raise ValueError('{} text must be a string.'.format(label))
            if item.get('case', 'Unchanged') != 'Unchanged':
                raise ValueError('{} Text operations do not support case conversion.'.format(label))
            if item.get('progression') is not None:
                raise ValueError('{} Text operations do not support progression.'.format(label))
        elif kind == 'source':
            if 'start' in item or 'end' in item:
                raise ValueError('{} uses the unsupported legacy source shape.'.format(label))
            separator = item.get('separator', '')
            if not isinstance(separator, string_types):
                raise ValueError('{} separator must be a string.'.format(label))
            progression = item.get('progression')
            _validate_progression(progression, label)
            selections = item.get('selections')
            _validate_selections(selections, label + ' selections')
            if progression is not None:
                if len(selections) != 1 or selections[0].get('kind') != 'single':
                    raise ValueError('{} progression requires a single source position.'.format(label))
                start = selections[0].get('position')
                if start.get('direction') != 'start':
                    raise ValueError('{} progression requires an absolute Start position.'.format(label))
        elif kind == 'parameter':
            parameter = item.get('parameter')
            if not isinstance(parameter, string_types) or not parameter.strip():
                raise ValueError('{} parameter name is required.'.format(label))
            tokenize = item.get('tokenize', False)
            if not isinstance(tokenize, bool):
                raise ValueError('{} tokenize setting must be true or false.'.format(label))
            progression = item.get('progression')
            _validate_progression(progression, label)
            if tokenize:
                delimiters = item.get('delimiters')
                separator = item.get('separator', '')
                if not isinstance(delimiters, string_types) or not delimiters:
                    raise ValueError('{} token delimiters are required.'.format(label))
                if not isinstance(separator, string_types):
                    raise ValueError('{} separator must be a string.'.format(label))
                selections = item.get('selections')
                _validate_selections(selections, label + ' selections')
                if progression is not None:
                    if len(selections) != 1 or selections[0].get('kind') != 'single':
                        raise ValueError(
                            '{} progression requires a single parameter token.'.format(label))
                    position = selections[0].get('position')
                    if position.get('direction') != 'start':
                        raise ValueError(
                            '{} progression requires an absolute Start position.'.format(label))
        elif kind == 'original':
            _validate_progression(item.get('progression'), label)
        elif kind == 'counter':
            if item.get('progression') is not None:
                raise ValueError('{} does not support progression.'.format(label))
        if kind == 'counter':
            start = item.get('start')
            increment = item.get('increment')
            if not isinstance(start, string_types) or not start.strip():
                raise ValueError('{} Counter start is required.'.format(label))
            start = start.strip()
            if not (re.match(r'^\d+$', start)
                    or re.match(r'^[A-Za-z]+$', start)
                    or re.match(r'^.+\d+$', start)):
                raise ValueError('{} Counter start must be numeric, alphabetic, or prefix-plus-numeric.'.format(label))
            if not isinstance(increment, integer_types) or isinstance(increment, bool) or increment < 0:
                raise ValueError('{} Counter increment must be zero or greater.'.format(label))
    return True


def operation_copy(item):
    return copy.deepcopy(item)


def edit_operation(item, **values):
    result = copy.deepcopy(item)
    result.update(values)
    validate_composition({'version': 1, 'operations': [result]})
    return result


def insert_operation(operations, item, destination, source_index=None):
    if not 0 <= destination <= len(operations):
        raise ValueError('Invalid insertion position.')
    result = copy.deepcopy(operations)
    if source_index is not None:
        if not 0 <= source_index < len(operations):
            raise ValueError('Invalid source position.')
        moved = result.pop(source_index)
        if destination > source_index:
            destination -= 1
    else:
        moved = copy.deepcopy(item)
    result.insert(destination, moved)
    validate_composition({'version': 1, 'operations': result})
    return result, destination


def position_controls(position):
    direction = position.get('direction', 'start')
    if direction == 'following':
        return 'Following', str(position.get('count', 0))
    if direction == 'end':
        return 'End', str(position.get('index', 1))
    return 'Start', str(position.get('index', 1))


def position_value(direction, number, is_end=False):
    number = str(number).strip()
    if not number.isdigit():
        raise ValueError('Enter a whole number for the token position.')
    value = int(number)
    if direction == 'Following':
        if not is_end:
            raise ValueError('Following is only available for an end position.')
        return {'direction': 'following', 'count': value}
    if value < 1:
        raise ValueError('Token positions start at 1; End 1 means the last token.')
    if direction == 'End':
        return {'direction': 'end', 'index': value}
    if direction != 'Start':
        raise ValueError('Choose Start or End for the token direction.')
    return {'direction': 'start', 'index': value}


def describe_operation(item, samples=()):
    kind = item['kind']
    if kind == 'text':
        value = item.get('text', '').replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')
        text = 'Text: "{}"'.format(value)
    elif kind == 'original':
        text = 'Original'
    elif kind == 'counter':
        text = 'Counter'
    elif kind == 'parameter':
        name = item.get('parameter', '')
        text = 'Parameter: {}'.format(name or '(unselected)')
        if item.get('tokenize'):
            parts = []
            for selection in item.get('selections', []):
                if selection['kind'] == 'range':
                    start_direction, start_number = position_controls(selection['start'])
                    end_direction, end_number = position_controls(selection['end'])
                    if end_direction == 'Following':
                        parts.append('{} {} + {} following'.format(
                            start_direction, start_number, end_number))
                    else:
                        parts.append('{} {} to {} {}'.format(
                            start_direction, start_number,
                            end_direction, end_number))
                else:
                    direction, number = position_controls(selection['position'])
                    parts.append('{} {}'.format(direction, number))
            if parts:
                text += ' [' + ' + '.join(parts) + ']'
    elif kind == 'source':
        parts = []
        for selection in item['selections']:
            if selection['kind'] == 'range':
                start_direction, start_number = position_controls(selection['start'])
                end_direction, end_number = position_controls(selection['end'])
                if end_direction == 'Following':
                    part = '{} {} + {} following'.format(
                        start_direction, start_number, end_number)
                else:
                    part = '{} {} to {} {}'.format(
                        start_direction, start_number,
                        end_direction, end_number)
            else:
                position_direction, position_number = position_controls(selection['position'])
                part = '{} {}'.format(position_direction, position_number)
            parts.append(part)
        text = 'Selections: ' + ' + '.join(parts)
        if len(item['selections']) > 1:
            text += ' | ' + repr(item.get('separator', ''))
    else:
        text = 'Unknown'
    progression = item.get('progression')
    if progression:
        text += ' [{} {}]'.format(progression['kind'], progression['step'])
    case = item.get('case', 'Unchanged')
    if case != 'Unchanged':
        text += ' [' + case + ']'
    return text if len(text) <= 68 else text[:65] + '...'
