"""Lossless visual representation of the existing ReValue pattern language."""
import copy
import re


CASES = ('Unchanged', 'upper', 'lower', 'title', 'sentence')
POSITIONS = r'(?:val[1-9]\d*|end(?:-[1-9]\d*)?)'
ENDS = r'(?:[1-9]\d*|end(?:-[1-9]\d*)?|\+\d+)'
SOURCE = re.compile(r'^(' + POSITIONS + r')(?::(' + ENDS + r'))?(?:\|([^{}~]+))?$')
PROGRESSION = re.compile(r'^(inc|seq):(val[1-9]\d*|param[1-5]):([+-]?\d+)$',
                         re.IGNORECASE)


def token(kind, **values):
    item = {'kind': kind, 'case': 'Unchanged'}
    item.update(values)
    return item


def expression(item):
    kind = item['kind']
    if kind == 'text':
        text = item.get('text', '')
        if '{' in text or '}' in text:
            raise ValueError('Braces are reserved for expressions. Use Advanced Pattern for brace text.')
        return text
    case = item.get('case', 'Unchanged')
    if case not in CASES:
        raise ValueError('Choose a supported text case.')
    if kind == 'source':
        source = item.get('start', '')
        end = item.get('end', '')
        join = item.get('join', '')
        core = source + (':' + end if end else '') + ('|' + join if join else '')
        if not SOURCE.match(core) or any(c in join for c in '{}~'):
            raise ValueError('Use val1, end or end-1 for Start; 3, end, end-1 or +2 for End.')
        if join != join.strip():
            raise ValueError('Use "space" for a space separator; leading/trailing spaces are not supported.')
    elif kind == 'parameter':
        slot = item.get('slot', 0)
        if slot not in range(1, 6):
            raise ValueError('Choose parameter slot 1 through 5.')
        source = 'param{}'.format(slot)
        core = source
    elif kind == 'original':
        source = core = 'orig'
    elif kind == 'counter':
        source = core = item.get('alias', 'count')
        if core not in ('count', 'param6'):
            raise ValueError('Unsupported counter token.')
    else:
        raise ValueError('Unsupported token kind: {}'.format(kind))
    operation = item.get('operation', '')
    if operation:
        if operation not in ('inc', 'seq'):
            raise ValueError('Choose Increment or Sequence.')
        step = item.get('step', '1')
        core = '{}:{}:{}'.format(operation, source, step)
        if not PROGRESSION.match(core) or (kind == 'source' and item.get('end')):
            raise ValueError('Progression requires a single valN or parameter slot and a signed integer step.')
        if kind == 'source' and item.get('join'):
            raise ValueError('Progression cannot include a join separator.')
    if case != 'Unchanged':
        core += '~' + case
    return '{' + core + '}'


def parse_placeholder(raw):
    inner = raw[1:-1].strip()
    parts = inner.rsplit('~', 1)
    case = 'Unchanged'
    if len(parts) == 2:
        inner, case = parts[0].strip(), parts[1].strip().lower()
        if case not in CASES[1:]:
            raise ValueError('Unsupported text case in {}.'.format(raw))
    progression = PROGRESSION.match(inner)
    operation, step = '', '1'
    if progression:
        operation, inner, step = progression.groups()
        operation, inner = operation.lower(), inner.lower()
    if inner.lower() == 'orig':
        item = token('original')
    elif inner.lower() in ('count', 'param6'):
        item = token('counter', alias=inner.lower())
    elif re.match(r'^param[1-5]$', inner, re.IGNORECASE):
        item = token('parameter', slot=int(inner[-1]))
    else:
        match = SOURCE.match(inner)
        if not match:
            raise ValueError('Cannot represent {} as a chip. Keep editing in Advanced Pattern.'.format(raw))
        start, end, join = match.groups()
        item = token('source', start=start, end=end or '', join=join or '')
    item.update(case=case, operation=operation, step=step)
    expression(item)
    item['raw'] = raw
    return item


def parse_pattern(pattern):
    items = []
    position = 0
    for match in re.finditer(r'\{[^{}]*\}', pattern):
        literal = pattern[position:match.start()]
        if literal:
            expression(token('text', text=literal))
            items.append(token('text', text=literal))
        items.append(parse_placeholder(match.group(0)))
        position = match.end()
    if position < len(pattern):
        literal = pattern[position:]
        expression(token('text', text=literal))
        items.append(token('text', text=literal))
    return items


def serialize_pattern(items):
    # Keep untouched expressions byte-for-byte, including aliases and spacing.
    return ''.join(item['raw'] if 'raw' in item else expression(item) for item in items)


def edited(item, **values):
    result = copy.deepcopy(item)
    result.pop('raw', None)
    result.update(values)
    expression(result)
    return result


def insert_item(items, item, destination, source_index=None):
    """Return a new list; destination is the insertion gap before removal."""
    if not 0 <= destination <= len(items):
        raise ValueError('Invalid insertion position.')
    result = copy.deepcopy(items)
    if source_index is not None:
        if not 0 <= source_index < len(items):
            raise ValueError('Invalid source position.')
        item = result.pop(source_index)
        if destination > source_index:
            destination -= 1
    else:
        item = copy.deepcopy(item)
    result.insert(destination, item)
    return result, destination


def parameter_slot(mappings, name):
    if name and name in mappings:
        return mappings.index(name) + 1
    if '' in mappings:
        return mappings.index('') + 1
    return None


def label(item, samples=(), mappings=()):
    kind = item['kind']
    if kind == 'text':
        value = item.get('text', '').replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')
        text = 'Text: "{}"'.format(value)
    elif kind == 'original':
        text = 'Original'
    elif kind == 'counter':
        text = 'Counter'
    elif kind == 'parameter':
        slot = item['slot']
        name = mappings[slot - 1] if len(mappings) >= slot else ''
        text = 'P{}: {}'.format(slot, name or '(unmapped)')
    else:
        start = item['start']
        end = item.get('end', '')
        if end:
            text = '{}:{}'.format(start, end)
        else:
            index = int(start[3:]) - 1 if start.startswith('val') else (
                len(samples) - 1 - (int(start[4:]) if start.startswith('end-') else 0))
            sample = samples[index] if 0 <= index < len(samples) else '(missing in sample)'
            text = '{}: {}'.format(start, sample)
        if item.get('join'):
            text += ' | ' + item['join']
    if item.get('operation'):
        text += ' [{} {}]'.format(item['operation'], item['step'])
    if item.get('case', 'Unchanged') != 'Unchanged':
        text += ' [' + item['case'] + ']'
    return text if len(text) <= 68 else text[:65] + '...'
