# -*- coding: utf-8 -*-
""""KW ReValue"
Re-value types/instances using structured token composition rules.
Decompose names into tokens, apply parameter re-valuation, reconstruct with flexible syntax.
"""

__title__ = 'KW\nReValue'
__author__ = 'Kent Watson'

import clr
import os
import re
import sys
from decimal import Decimal, InvalidOperation

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xaml')

from System import Enum, Predicate
from System.Windows import Window, GridLength, GridUnitType, Visibility as WpfVisibility
from System.Windows.Controls import ComboBoxItem, DataGridColumn, DataGridEditingUnit, TextBox
from System.Windows.Data import CollectionViewSource
from System.Windows.Input import Mouse
from ui_styles import load_window
from System.Windows.Media import VisualTreeHelper
from System.Collections.ObjectModel import ObservableCollection
from System.Globalization import CultureInfo
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script as _pyscript
from pyrevit.compat import get_elementid_value_func
from filter_expression import (
    count_rules, evaluate_expression, serialize_expression, validate_expression,
)
from rule_model import (
    CASES, CASE_LABELS, default_composition, deserialize_composition,
    deep_copy_composition, original_composition, serialize_composition,
    validate_composition,
)


class ListSortDirection(object):
    """ListSortDirection lives in different assemblies on .NET Framework (Revit 2024-)
    and .NET 8 (Revit 2025+), so resolve it from DataGridColumn.SortDirection."""
    _enum_type = clr.GetClrType(DataGridColumn).GetProperty(
        'SortDirection').PropertyType.GetGenericArguments()[0]
    Ascending = Enum.Parse(_enum_type, 'Ascending')
    Descending = Enum.Parse(_enum_type, 'Descending')


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
element_id_value = get_elementid_value_func()

_ENV_PREFIX = 'KWReValue'
_SESSION_SETTING_DEFAULTS = {
    'mode': 'type',
    'delimiters': r'-_/,\|',
    'orig_param': '',
    'composition': serialize_composition(default_composition()),
    'final_case': 'None',
    'find_text': '',
    'replace_text': '',
    'match_whole_word': 'False',
    'match_case': 'True',
    'sort_mode': 'none',
    'sort_param': '',
    'sort_descending': 'False',
}

SORT_NONE = 'none'
SORT_CURRENT = 'current'
SORT_PARAM = 'param'
NEW_VALUE_FILTER_WARNING = 'Clear New Value filter to apply'


def natural_sort_key(text):
    """Case-insensitive key that orders embedded numbers numerically (A2 before A10)."""
    parts = re.split(r'(\d+)', text or '')
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower())
                 for part in parts if part)


def order_preview_rows(rows, sort_entries, descending):
    """Return rows sorted by (is_blank, key) entries; blanks last, ties in selection order."""
    by_selection = sorted(rows, key=lambda row: row.SelectionIndex)
    if sort_entries is None:
        return by_selection
    filled = [row for row in by_selection if not sort_entries[row][0]]
    blanks = [row for row in by_selection if sort_entries[row][0]]
    filled = sorted(filled, key=lambda row: sort_entries[row][1], reverse=descending)
    return filled + blanks


def _session_key(name):
    return '{}_{}'.format(_ENV_PREFIX, name)


def load_session_settings():
    """Load tool settings that persist only for the current Revit session."""
    settings = dict(_SESSION_SETTING_DEFAULTS)
    for name in _SESSION_SETTING_DEFAULTS:
        try:
            saved = _pyscript.get_envvar(_session_key(name))
            if saved is not None:
                settings[name] = str(saved)
        except Exception:
            pass
    if 'composition' in settings:
        try:
            settings['composition'] = serialize_composition(
                deserialize_composition(settings['composition']))
        except Exception as ex:
            settings['composition'] = serialize_composition(default_composition())
            settings['composition_error'] = 'Malformed structured composition reset to default: {}'.format(ex)
    return settings


def save_session_setting(name, value):
    """Save a single setting for the current Revit session."""
    try:
        _pyscript.set_envvar(_session_key(name), '' if value is None else str(value))
    except Exception:
        pass

# ============================================================================
# DEFAULT TOKENIZATION CONFIG
# ============================================================================

DEFAULT_DELIMITERS = r'-_/,\|'
CANONICAL_DELIM = '|'

# Named delimiters for user-friendly syntax
NAMED_DELIMS = {
    'space': ' ',
    'hyphen': '-',
    'underscore': '_',
}


def build_tokenizer(delimiters):
    """Build a tokenizer function with the given delimiters."""
    try:
        # Escape delimiters for regex
        escaped = ''.join(['\\' + c if c in r'-[]{}()*+?.^\\|' else c for c in delimiters])
        delim_regex = re.compile(r'[%s]+' % escaped)
    except:
        # Fallback to default if regex fails
        delim_regex = re.compile(r'[%s]+' % DEFAULT_DELIMITERS)
    
    def tokenize(input_text):
        """Normalize and split input_text into tokens."""
        if not input_text:
            return []
        
        normalized = delim_regex.sub(CANONICAL_DELIM, input_text)
        raw_tokens = normalized.split(CANONICAL_DELIM)
        tokens = [t.strip() for t in raw_tokens if t.strip()]
        return tokens
    
    return tokenize


# Default tokenizer
tokenize = build_tokenizer(DEFAULT_DELIMITERS)

NUMERIC_REGEX = re.compile(r'^\d+$')
ALPHA_REGEX = re.compile(r'^[A-Za-z]+$')
MIXED_SUFFIX_NUM_REGEX = re.compile(r'^(.*?)(\d+)$')


def _alpha_to_int(text):
    """Convert alpha sequence (A..Z, AA..) to 1-based integer."""
    total = 0
    for ch in text.upper():
        total = (total * 26) + (ord(ch) - ord('A') + 1)
    return total


def _int_to_alpha(num):
    """Convert 1-based integer to alpha sequence (A..Z, AA..)."""
    if num < 1:
        return ''

    chars = []
    while num > 0:
        num, rem = divmod(num - 1, 26)
        chars.append(chr(ord('A') + rem))
    chars.reverse()
    return ''.join(chars)


SIGNED_NUMERIC_REGEX = re.compile(r'^-?\d+$')
SIGNED_SUFFIX_NUM_REGEX = re.compile(r'^(.*?)(-?\d+)$')
PROGRESSION_SOURCE_REGEX = re.compile(r'^(val[1-9]\d*|param[1-5])$', re.IGNORECASE)


def _increment_value(value, increment):
    """Advance a numeric, alphabetic, or prefix-plus-number value."""
    original = '' if value is None else str(value)
    text = original.strip()
    if not text:
        return original, 'source value is blank'

    if SIGNED_NUMERIC_REGEX.match(text):
        number = int(text) + increment
        sign = '-' if number < 0 else ''
        return '{}{}'.format(sign, str(abs(number)).zfill(len(text.lstrip('-')))), None

    if ALPHA_REGEX.match(text):
        number = _alpha_to_int(text) + increment
        if number < 1:
            return original, 'alphabetic value would move below A'
        alpha = _int_to_alpha(number)
        if text.islower():
            alpha = alpha.lower()
        return alpha, None

    match = SIGNED_SUFFIX_NUM_REGEX.match(text)
    if match and match.group(1):
        prefix = match.group(1)
        suffix = match.group(2)
        number = int(suffix) + increment
        sign = '-' if number < 0 else ''
        return '{}{}{}'.format(
            prefix, sign, str(abs(number)).zfill(len(suffix.lstrip('-')))), None

    return original, 'source value is not numeric, alphabetic, or prefix-plus-number'


def apply_case_conversion(value, case_name):
    """Convert text to the requested case, leaving it unchanged for None."""
    if value is None:
        text = ''
    elif isinstance(value, basestring):
        text = value
    else:
        text = str(value)
    if not case_name or case_name == 'None':
        return text
    case_key = str(case_name).strip().lower()
    if case_key == 'upper':
        return text.upper()
    if case_key == 'lower':
        return text.lower()
    if case_key == 'title':
        return text.title()
    if case_key == 'sentence':
        return text[:1].upper() + text[1:].lower()
    return text


def _resolve_progression_source(source_ref, tokens, param_dict, composition=None):
    """Get one token or selected parameter value for an inc/seq operation."""
    if source_ref.startswith('val'):
        try:
            token_index = int(source_ref[3:]) - 1
            if token_index >= 0 and token_index < len(tokens):
                return tokens[token_index]
        except Exception:
            pass
        return ''

    if source_ref.startswith('ptoken') and composition is not None:
        try:
            operation_index = int(source_ref[6:])
            item = composition['operations'][operation_index]
            if item.get('kind') == 'parameter' and item.get('tokenize'):
                return _resolve_tokenized_parameter(
                    item, param_dict.get(item.get('parameter'), ''))
        except Exception:
            pass
        return ''

    return param_dict.get(source_ref, '')


def _operation_progression_ref(operation_index, item):
    if item['kind'] == 'source':
        selections = item['selections']
        if len(selections) == 1 and selections[0].get('kind') == 'single':
            position = selections[0].get('position', {})
            if position.get('direction') == 'start':
                return 'val{}'.format(position['index'])
    elif item['kind'] == 'parameter':
        if item.get('tokenize'):
            return 'ptoken{}'.format(operation_index)
        return item['parameter']
    elif item['kind'] == 'original':
        return 'orig'
    return ''


def _sequence_source_refs(composition):
    """Return source references used by sequence operations."""
    source_refs = []
    validate_composition(composition)
    for operation_index, item in enumerate(composition['operations']):
        progression = item.get('progression')
        if not progression or progression['kind'] != 'seq':
            continue
        ref = _operation_progression_ref(operation_index, item)
        if not ref:
            continue
        if ref not in source_refs:
            source_refs.append(ref)
    return source_refs


def _composition_uses_counter(composition):
    if isinstance(composition, dict) and composition.get('operations') == []:
        return False
    validate_composition(composition)
    return any(item['kind'] == 'counter' for item in composition['operations'])


def build_counter_generator(start_text, increment_text):
    """Build counter generator supporting numeric, alpha, and prefix+numeric."""
    start_text = '' if start_text is None else str(start_text).strip()
    increment_text = '' if increment_text is None else str(increment_text).strip()

    if not start_text:
        return None, 'Counter Start value is required when the composition uses Counter.'

    if not increment_text:
        increment_text = '1'

    try:
        increment = int(increment_text)
    except Exception:
        return None, 'Increment value must be an integer.'

    if increment < 0:
        return None, 'Increment value must be 0 or greater.'

    if NUMERIC_REGEX.match(start_text):
        width = len(start_text)
        base = int(start_text)

        def _numeric_counter(index):
            value = base + (index * increment)
            return str(value).zfill(width)

        return _numeric_counter, None

    if ALPHA_REGEX.match(start_text):
        base = _alpha_to_int(start_text)
        is_lower = start_text.islower()

        def _alpha_counter(index):
            value = base + (index * increment)
            alpha = _int_to_alpha(value)
            if is_lower:
                return alpha.lower()
            return alpha

        return _alpha_counter, None

    match = MIXED_SUFFIX_NUM_REGEX.match(start_text)
    if match and match.group(1):
        prefix = match.group(1)
        suffix = match.group(2)
        width = len(suffix)
        base = int(suffix)

        def _mixed_counter(index):
            value = base + (index * increment)
            return '{}{}'.format(prefix, str(value).zfill(width))

        return _mixed_counter, None

    return None, 'Unsupported start format. Use numeric, alphabetic, or prefix+numeric (e.g. RM01).'


def _resolve_source_window(tokens, start, end=None):
    """Resolve a structured Start/End/Following source range."""
    if not tokens:
        return []
    direction = start.get('direction')
    if direction == 'start':
        start_pos = start['index'] - 1
        if start_pos < 0 or start_pos >= len(tokens):
            return []
    elif direction == 'end':
        start_pos = len(tokens) - start['index']
        if start_pos < 0:
            start_pos = 0
    else:
        raise ValueError('Invalid source start direction.')

    if end is None:
        end_pos = start_pos
    else:
        end_direction = end.get('direction')
        if end_direction == 'start':
            end_pos = end['index'] - 1
        elif end_direction == 'end':
            end_pos = len(tokens) - end['index']
        elif end_direction == 'following':
            end_pos = start_pos + end['count']
        else:
            raise ValueError('Invalid source end direction.')

    if end_pos < start_pos:
        return []
    end_pos = min(end_pos, len(tokens) - 1)
    return tokens[start_pos:end_pos + 1]


def _resolve_source_selection(tokens, selection):
    if selection.get('kind') == 'range':
        return _resolve_source_window(
            tokens, selection['start'], selection['end'])
    if selection.get('kind') == 'single':
        position = selection['position']
        return _resolve_source_window(tokens, position, None)
    raise ValueError('Invalid source selection kind.')


def _resolve_selected_tokens(tokens, selections, separator):
    resolved_parts = []
    for selection in selections:
        window = _resolve_source_selection(tokens, selection)
        resolved_parts.append(separator.join(window))
    return separator.join(part for part in resolved_parts if part)


def _resolve_tokenized_parameter(item, value):
    tokenizer = build_tokenizer(item['delimiters'])
    tokens = tokenizer('' if value is None else str(value))
    return _resolve_selected_tokens(
        tokens, item['selections'], item.get('separator', ''))


def evaluate_composition(input_text, composition, parameter_values,
                         tokenizer_func=None, sequence_seeds=None,
                         row_index=0, warnings=None):
    """Evaluate an ordered structured composition into one output string."""
    validate_composition(composition)
    if tokenizer_func is None:
        tokenizer_func = tokenize
    tokens = tokenizer_func(input_text)
    sequence_seeds = sequence_seeds or {}
    if warnings is None:
        warnings = []

    param_dict = {}
    if isinstance(parameter_values, dict):
        param_dict.update(parameter_values)

    param_dict['orig'] = '' if input_text is None else str(input_text)
    parts = []
    for operation_index, item in enumerate(composition['operations']):
        kind = item['kind']
        case = item.get('case', 'Unchanged')
        if kind == 'text':
            result = item.get('text', '')
        elif kind == 'source':
            selections = item['selections']
            result = _resolve_selected_tokens(
                tokens, selections, item.get('separator', ''))
            progression = item.get('progression')
            if progression:
                start = selections[0]['position']
                ref = 'val{}'.format(start['index'])
                source_value = _resolve_progression_source(ref, tokens, param_dict)
                if progression['kind'] == 'inc':
                    result, error = _increment_value(source_value, progression['step'])
                else:
                    seed_value = sequence_seeds.get(ref, '')
                    if not seed_value:
                        error = 'sequence seed is blank'
                        result = source_value
                    else:
                        result, error = _increment_value(
                            seed_value, row_index * progression['step'])
                        if error:
                            result = source_value
                if error:
                    warnings.append('{}: {}'.format(ref, error))
        elif kind == 'parameter':
            ref = item['parameter']
            result = param_dict.get(ref, '')
            if item.get('tokenize'):
                result = _resolve_tokenized_parameter(item, result)
            progression = item.get('progression')
            if progression:
                ref = _operation_progression_ref(operation_index, item)
                source_value = _resolve_progression_source(
                    ref, tokens, param_dict, composition)
                if progression['kind'] == 'inc':
                    result, error = _increment_value(source_value, progression['step'])
                else:
                    seed_value = sequence_seeds.get(ref, '')
                    if not seed_value:
                        error = 'sequence seed is blank'
                        result = source_value
                    else:
                        result, error = _increment_value(
                            seed_value, row_index * progression['step'])
                        if error:
                            result = source_value
                if error:
                    warnings.append('{}: {}'.format(ref, error))
        elif kind == 'original':
            result = param_dict['orig']
            progression = item.get('progression')
            if progression:
                ref = 'orig'
                source_value = _resolve_progression_source(ref, tokens, param_dict)
                if progression['kind'] == 'inc':
                    result, error = _increment_value(source_value, progression['step'])
                else:
                    seed_value = sequence_seeds.get(ref, '')
                    if not seed_value:
                        error = 'sequence seed is blank'
                        result = source_value
                    else:
                        result, error = _increment_value(
                            seed_value, row_index * progression['step'])
                        if error:
                            result = source_value
                if error:
                    warnings.append('{}: {}'.format(ref, error))
        elif kind == 'counter':
            start = item.get('start', 'A')
            increment = item.get('increment', 1)
            generator, error = build_counter_generator(
                start, str(increment))
            if error:
                warnings.append('Counter: {}'.format(error))
                result = param_dict.get('counter', '')
            else:
                result = generator(row_index)
        else:
            raise ValueError('Unknown operation kind: {}'.format(kind))
        parts.append(apply_case_conversion(result, case))
    return ''.join(parts)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_default_source_label(elements, is_instance_mode):
    """Describe the system name source without treating it as a parameter."""
    if not is_instance_mode:
        return '<Default: Type Name>'

    source_names = set()
    for element in elements:
        if isinstance(element, ViewSheet):
            source_names.add('Sheet Name')
        elif isinstance(element, View):
            source_names.add('View Name')
        elif isinstance(element, ElementType):
            source_names.add('Type Name')
        else:
            element_type = _get_element_type(element)
            type_name = _safe_type_name(element_type) if element_type is not None else ''
            if type_name and _safe_element_name(element) == type_name:
                source_names.add('Type Name')
            else:
                source_names.add('Name')
    if len(source_names) == 1:
        return '<Default: {}>'.format(next(iter(source_names)))
    if source_names:
        return '<Default: Name (varies by element)>'
    return '<Default: Name>'


def _safe_type_name(elem_type):
    """Best-effort type name getter across Revit API edge cases."""
    if elem_type is None:
        return ""

    try:
        name = revit.query.get_name(elem_type)
        if name:
            return str(name)
    except Exception:
        pass

    for bip in [BuiltInParameter.SYMBOL_NAME_PARAM,
                BuiltInParameter.ALL_MODEL_TYPE_NAME]:
        try:
            p = elem_type.get_Parameter(bip)
            if p and p.HasValue:
                val = p.AsString()
                if val:
                    return str(val)
        except Exception:
            pass

    return ""


def _safe_set_type_name(elem_type, new_name):
    """Best-effort type name setter across Revit API edge cases."""
    try:
        revit.update.set_name(elem_type, new_name)
        return True
    except Exception:
        pass

    for bip in [BuiltInParameter.SYMBOL_NAME_PARAM,
                BuiltInParameter.ALL_MODEL_TYPE_NAME]:
        try:
            p = elem_type.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(new_name)
                return True
        except Exception:
            pass

    return False


def _safe_element_name(element):
    """Get name of element (instance), fallback to type."""
    if element is None:
        return ""
    
    try:
        name = revit.query.get_name(element)
        if name:
            return str(name)
    except Exception:
        pass
    
    return ""


def _safe_set_element_name(element, new_name):
    """Set name of element (instance)."""
    if element is None:
        return False
    
    try:
        element.Name = new_name
        return True
    except Exception:
        pass

    try:
        revit.update.set_name(element, new_name)
        return True
    except Exception:
        pass
    
    return False


def _transactional_set_instance_name(element, new_name):
    """Set an instance name using a transaction-friendly path.

    Views and other instance-like elements are first tried through the direct
    element Name property. This avoids plan-view parameter writes that can
    trigger Revit's corresponding-level rename behavior.
    """
    if element is None:
        return False

    try:
        if isinstance(element, View):
            element.Name = new_name
            return True
        if isinstance(element, Level):
            element.Name = new_name
            return True
    except Exception:
        pass

    candidate_bips = [
        getattr(BuiltInParameter, 'VIEW_NAME', None),
        getattr(BuiltInParameter, 'ALL_MODEL_TYPE_NAME', None),
        getattr(BuiltInParameter, 'ALL_MODEL_INSTANCE_COMMENTS', None),
    ]

    for bip in candidate_bips:
        if bip is None:
            continue

        try:
            param = element.get_Parameter(bip)
            if param and not param.IsReadOnly:
                storage = param.StorageType
                text_value = '' if new_name is None else str(new_name)

                if storage == StorageType.String:
                    param.Set(text_value)
                    return True

                try:
                    param.SetValueString(text_value)
                    return True
                except Exception:
                    pass
        except Exception:
            pass

    return _safe_set_element_name(element, new_name)


def _find_parameter_for_write(element, param_name, is_instance_mode):
    """Find writable parameter by mode. Returns parameter or None."""
    if element is None or not param_name:
        return None

    param_name = str(param_name).strip()
    if not param_name:
        return None

    if is_instance_mode:
        # In instance mode, prefer instance parameter first.
        try:
            p = element.LookupParameter(param_name)
            if p:
                return p
        except Exception:
            pass

        elem_type = _get_element_type(element)
        if elem_type:
            try:
                p = elem_type.LookupParameter(param_name)
                if p:
                    return p
            except Exception:
                pass
    else:
        # Type mode writes only to type parameter.
        elem_type = _get_element_type(element)
        if elem_type:
            try:
                p = elem_type.LookupParameter(param_name)
                if p:
                    return p
            except Exception:
                pass

    return None


def _safe_set_parameter_value(element, param_name, new_value, is_instance_mode):
    """Set parameter value with basic storage-type handling."""
    p = _find_parameter_for_write(element, param_name, is_instance_mode)
    if not p or p.IsReadOnly:
        return False

    try:
        storage = p.StorageType
        text_value = '' if new_value is None else str(new_value)

        if storage == StorageType.String:
            p.Set(text_value)
            return True

        if storage in [StorageType.Double, StorageType.Integer]:
            # Try formatted string first (units-aware for doubles), then numeric parse.
            try:
                if p.SetValueString(text_value):
                    return True
            except Exception:
                pass

            try:
                if storage == StorageType.Integer:
                    p.Set(int(float(text_value)))
                else:
                    p.Set(float(text_value))
                return True
            except Exception:
                return False

    except Exception:
        return False

    return False


def _get_element_type(element):
    """Get ElementType for an element, or return the element if already a type."""
    if element is None:
        return None

    if isinstance(element, ElementType):
        return element

    try:
        type_id = element.GetTypeId()
        if type_id and type_id.Value != -1:
            return doc.GetElement(type_id)
    except:
        pass

    return None


def _elementid_param_to_text(param):
    """Convert an ElementId parameter value into readable text."""
    try:
        val = param.AsValueString()
        if val:
            return str(val)
    except Exception as ex:
        print("Error reading reference parameter display value: {}".format(ex))

    elem_id = param.AsElementId()
    if elem_id is not None:
        id_value = element_id_value(elem_id)
        if id_value >= 0:
            referenced_element = doc.GetElement(elem_id)
            if referenced_element is not None:
                name = _safe_element_name(referenced_element)
                if name:
                    return name
            return str(id_value)

    return ''


def collect_all_parameters(elements, is_instance_mode):
    """Collect all unique string/numeric/ElementId parameters from elements."""
    param_set = set()
    param_values_map = {}
    
    for elem in elements:
        try:
            targets = []

            if is_instance_mode:
                # Instance mode can use both instance and type parameters.
                targets.append(elem)
                elem_type = _get_element_type(elem)
                if elem_type:
                    targets.append(elem_type)
            else:
                # Type mode must only use type parameters.
                elem_type = _get_element_type(elem)
                if elem_type:
                    targets.append(elem_type)

            for target in targets:
                if target is None:
                    continue

                for param in target.Parameters:
                    try:
                        param_name = param.Definition.Name
                        param_storage = param.StorageType
                        
                        include_param = (
                            param_storage in [StorageType.String, StorageType.Double,
                                              StorageType.Integer, StorageType.ElementId]
                        )

                        if include_param:
                            param_set.add(param_name)
                            
                            if param.HasValue:
                                try:
                                    if param_storage == StorageType.String:
                                        val = param.AsString()
                                    elif param_storage == StorageType.ElementId:
                                        val = _elementid_param_to_text(param)
                                    else:
                                        val = param.AsValueString()
                                    if val and param_name not in param_values_map:
                                        param_values_map[param_name] = str(val)
                                except:
                                    pass
                    except:
                        pass
        except:
            pass
    
    available_params = sorted(list(param_set))
    return available_params, param_values_map


# ============================================================================
# Load XAML from File
# ============================================================================
def load_xaml_window():
    """Load XAML window from ReValueUI.xaml file"""
    script_dir = os.path.dirname(__file__)
    xaml_file = os.path.join(script_dir, 'ReValueUI.xaml')
    
    if not os.path.exists(xaml_file):
        raise IOError("XAML file not found: {}".format(xaml_file))
    
    return load_window(xaml_file)


# ============================================================================
# Preview Item Class
# ============================================================================
FILTER_CONDITIONS = (
    'Equals', 'Does not equal', 'Contains', 'Does not contain',
    'Starts with', 'Does not begin with', 'Ends with', 'Does not end with',
    'Is blank', 'Is not blank', 'Greater than', 'Less than',
    'Greater than or equal to', 'Less than or equal to',
)
NUMERIC_FILTER_CONDITIONS = (
    'Greater than', 'Less than', 'Greater than or equal to', 'Less than or equal to',
)


def parse_filter_number(text, decimal_separator='.', group_separator=',',
                        allow_unit=False):
    """Parse a single displayed number, never concatenate compound measurements."""
    text = text.strip()
    separators = re.escape(decimal_separator + group_separator)
    match = re.match(r'^([+-]?(?:\d[\d' + separators +
                     r']*|[' + re.escape(decimal_separator) +
                     r']\d+)(?:[eE][+-]?\d+)?)\s*(.*?)$', text, re.UNICODE)
    if not match:
        raise ValueError('Enter a numeric value in the parameter display units.')
    number, suffix = match.groups()
    number = number.strip()
    if suffix and (not allow_unit or re.search(r'[\d/\'"+-]', suffix)):
        raise ValueError('Use a single decimal number, not compound or fractional units.')
    if group_separator and group_separator != decimal_separator:
        mantissa = re.split('[eE]', number)[0]
        whole = mantissa.split(decimal_separator)[0].lstrip('+-')
        if group_separator in whole:
            groups = whole.split(group_separator)
            if not (1 <= len(groups[0]) <= 3 and
                    all(len(group) == 3 and group.isdigit() for group in groups[1:])):
                raise ValueError('Use the current regional decimal and thousands separators.')
        if decimal_separator in mantissa and group_separator in mantissa.split(decimal_separator, 1)[1]:
            raise ValueError('Use the current regional decimal and thousands separators.')
        number = number.replace(group_separator, '')
    number = number.replace(decimal_separator, '.')
    try:
        value = Decimal(number)
    except InvalidOperation:
        raise ValueError('Enter a valid numeric value.')
    if not value.is_finite():
        raise ValueError('Enter a finite numeric value.')
    return value


def matches_parameter_filter(value, condition, expected, decimal_separator='.',
                             group_separator=','):
    if condition in NUMERIC_FILTER_CONDITIONS:
        actual = parse_filter_number(value, decimal_separator, group_separator, True)
        target = parse_filter_number(expected, decimal_separator, group_separator)
        if condition == 'Greater than':
            return actual > target
        if condition == 'Less than':
            return actual < target
        if condition == 'Greater than or equal to':
            return actual >= target
        return actual <= target
    actual, target = value.lower(), expected.lower()
    if condition == 'Is blank':
        return not value.strip()
    if condition == 'Is not blank':
        return bool(value.strip())
    if condition == 'Equals':
        return actual == target
    if condition == 'Does not equal':
        return actual != target
    if condition == 'Contains':
        return target in actual
    if condition == 'Does not contain':
        return target not in actual
    if condition == 'Starts with':
        return actual.startswith(target)
    if condition == 'Does not begin with':
        return not actual.startswith(target)
    if condition == 'Ends with':
        return actual.endswith(target)
    if condition == 'Does not end with':
        return not actual.endswith(target)
    raise ValueError('Unknown parameter filter condition: {}'.format(condition))


def compare_filter_rule(value, node, decimal_separator='.', group_separator=','):
    if not node['numeric']:
        return matches_parameter_filter(value, node['condition'], node['value'])
    actual = parse_filter_number(value, decimal_separator, group_separator, True)
    expected = Decimal(node['value'])
    condition = node['condition']
    if condition == 'Equals':
        return actual == expected
    if condition == 'Does not equal':
        return actual != expected
    if condition == 'Greater than':
        return actual > expected
    if condition == 'Less than':
        return actual < expected
    if condition == 'Greater than or equal to':
        return actual >= expected
    if condition == 'Less than or equal to':
        return actual <= expected
    raise ValueError('Unknown numeric condition: {}'.format(condition))


def replace_final_value(value, find_text, replace_text, match_whole_word=False,
                        match_case=True):
    """Replace literal text, optionally restricted by word boundaries and case."""
    if not find_text:
        return value
    if match_case and not match_whole_word:
        return value.replace(find_text, replace_text)

    expression = re.escape(find_text)
    if match_whole_word:
        expression = r'(?<!\w)' + expression + r'(?!\w)'
    flags = re.UNICODE
    if not match_case:
        flags |= re.IGNORECASE
    return re.sub(expression, lambda match: replace_text, value, flags=flags)


class PreviewItem(object):
    """Represents a single element re-value preview"""
    def __init__(self, element, current_name):
        self.Element = element
        self.CurrentName = current_name
        self.NewName = current_name
        self.final = False
        self.tooltip = ''
        self.FilterMatch = True
        self.SortValue = ''
        self.SelectionIndex = 0

    @property
    def HasChanges(self):
        return self.NewName != self.CurrentName
    
    def format_value(self, composition, param_values, tokenizer_func, counter_value='', original_value='', find_text='', replace_text='', sequence_seeds=None, row_index=0, match_whole_word=False, match_case=True, final_case='None'):
        """Format new name using a structured token composition."""
        if self.final:
            return
        
        self.tooltip = ''
        try:
            if not composition:
                self.NewName = ''
                self.tooltip = 'Composition Required'
                return
            validate_composition(composition)
            param_dict = {}
            if isinstance(param_values, dict):
                param_dict.update(param_values)
            param_dict['orig'] = '' if original_value is None else str(original_value)
            param_dict['counter'] = '' if counter_value is None else str(counter_value)
            warnings = []
            new_name = evaluate_composition(
                self.CurrentName, composition, param_dict, tokenizer_func,
                sequence_seeds, row_index, warnings)

            if find_text:
                new_name = replace_final_value(
                    new_name, find_text, replace_text, match_whole_word, match_case)

            new_name = apply_case_conversion(new_name, final_case)
            self.NewName = new_name
            if warnings:
                self.tooltip = 'Warning: {}'.format('; '.join(warnings))
            else:
                self.tooltip = 'OK'
            
        except Exception as ex:
            self.NewName = ''
            self.tooltip = 'Error: {}'.format(str(ex))


# ============================================================================
# Re-Value Dialog Class
# ============================================================================
class ReValueDialog(object):
    def __init__(self, elements, is_instance_mode=False, launch_context=None,
                 rename_writer=None, initial_names=None, draft_only=False):
        """Initialize dialog with list of elements"""
        if launch_context not in (None, 'filter_names'):
            raise ValueError("Unsupported ReValue launch context.")
        self.is_filter_name_context = launch_context == 'filter_names'
        if self.is_filter_name_context and not callable(rename_writer):
            raise TypeError("Filter-name mode requires a rename_writer callback.")
        self.rename_writer = rename_writer
        self.initial_names = dict(initial_names or {})
        self.draft_only = bool(draft_only)
        if self.draft_only and not self.is_filter_name_context:
            raise ValueError("Draft return is only available in filter-name mode.")
        self.applied = False

        # Load XAML window
        self.window = load_xaml_window()
        
        # Store data
        self.elements = elements
        self.is_instance_mode = is_instance_mode
        self.preview_items = ObservableCollection[object]()
        self.available_params = []
        self.param_values_map = {}
        self._suspend_events = False
        self._composition_before_original = None
        self.composition = default_composition()
        self.composition_error = ''
        self.sort_mode = SORT_NONE
        self.sort_param = ''
        self.sort_descending = False
        
        # Get controls - mode toggle
        self.btn_mode = self.window.FindName('btn_mode')
        
        # Get controls - original parameter dropdown
        self.combo_orig_param = self.window.FindName('combo_orig_param')
        self.txt_delimiters = self.window.FindName('txt_delimiters')

        # Get controls - row sorting
        self.combo_sort_by = self.window.FindName('combo_sort_by')
        self.btn_sort_direction = self.window.FindName('btn_sort_direction')
        self.btn_clear_sort = self.window.FindName('btn_clear_sort')
        self.col_sort_value = self.window.FindName('col_sort_value')
        self.col_current = self.window.FindName('col_current')
        self.current_sort_hint = self.window.FindName('current_sort_hint')
        self.current_header_sort_hint = self.window.FindName('current_header_sort_hint')
        
        
        # Get controls - composition
        self.btn_use_orig = self.window.FindName('btn_use_orig')
        self.combo_final_case = self.window.FindName('combo_final_case')

        # Get controls - final value find/replace
        self.txt_find = self.window.FindName('txt_find')
        self.txt_replace = self.window.FindName('txt_replace')
        self.chk_match_whole_word = self.window.FindName('chk_match_whole_word')
        self.chk_match_case = self.window.FindName('chk_match_case')
        
        # Get controls - grid and buttons
        self.preview_grid = self.window.FindName('preview_grid')
        self.txt_filter_current = self.window.FindName('txt_filter_current')
        self.txt_filter_new = self.window.FindName('txt_filter_new')
        self.btn_help = self.window.FindName('btn_help')
        self.btn_apply = self.window.FindName('btn_apply')
        self.btn_close = self.window.FindName('btn_close')
        self.btn_edit_filters = self.window.FindName('btn_edit_filters')
        self.btn_clear_filters = self.window.FindName('btn_clear_filters')
        self.txt_filter_summary = self.window.FindName('txt_filter_summary')
        self.txt_filter_status = self.window.FindName('txt_filter_status')
        self.parameter_filter = None
        self._parameter_filter_error = ''
        self._invalid_filter_values = 0
        number_format = CultureInfo.CurrentCulture.NumberFormat
        self._decimal_separator = number_format.NumberDecimalSeparator
        self._group_separator = number_format.NumberGroupSeparator
        
        # Wire up events
        self.btn_mode.Click += self.OnModeChanged
        if self.combo_orig_param:
            self.combo_orig_param.SelectionChanged += self.OnSettingsChanged
        if self.txt_delimiters:
            self.txt_delimiters.TextChanged += self.OnSettingsChanged
        if self.combo_final_case:
            self.combo_final_case.SelectionChanged += self.OnSettingsChanged
        
        if self.txt_find:
            self.txt_find.TextChanged += self.OnSettingsChanged
        if self.txt_replace:
            self.txt_replace.TextChanged += self.OnSettingsChanged
        for checkbox in (self.chk_match_whole_word, self.chk_match_case):
            checkbox.Checked += self.OnSettingsChanged
            checkbox.Unchecked += self.OnSettingsChanged
        
        self.btn_use_orig.Click += self.OnUseOriginal
        self.preview_grid.SelectedCellsChanged += self.OnGridSelectionChanged
        self.preview_grid.Sorting += self.OnGridSorting
        self.combo_sort_by.SelectionChanged += self.OnSortByChanged
        self.btn_sort_direction.Click += self.OnSortDirectionClicked
        self.btn_clear_sort.Click += self.OnClearSort
        self.txt_filter_current.TextChanged += self.OnPreviewFilterChanged
        self.txt_filter_new.TextChanged += self.OnPreviewFilterChanged
        self.btn_edit_filters.Click += self.OnEditFilters
        self.btn_clear_filters.Click += self.OnClearFilters

        if self.btn_help:
            self.btn_help.Click += self.OnHelp
        
        self.btn_apply.Click += self.OnApply
        self.btn_close.Click += self.OnClose

        if self.is_filter_name_context:
            self.window.Title = ('KW ReValue - Filter Name Proposals' if self.draft_only
                                 else 'KW ReValue - Rename Filters')
            self.btn_apply.Content = 'Use Proposals' if self.draft_only else 'Rename Filters'
            self.btn_mode.IsEnabled = False
            self.btn_mode.Parent.Visibility = WpfVisibility.Collapsed
            self.combo_orig_param.IsEnabled = False
            self.btn_edit_filters.IsEnabled = False
            self.btn_clear_filters.IsEnabled = False
        
        # Initialize data
        self.initialize_data()
        from token_editor import TokenEditor
        self.token_editor = TokenEditor(self, build_counter_generator)
        
    def initialize_data(self):
        """Initialize parameter list and preview items"""
        self._suspend_events = True
        if self.is_filter_name_context:
            session_settings = dict(_SESSION_SETTING_DEFAULTS)
            session_settings['composition'] = serialize_composition(original_composition())
        else:
            session_settings = load_session_settings()
        self.composition_error = session_settings.get('composition_error', '')
        try:
            self.composition = deserialize_composition(session_settings.get(
                'composition', serialize_composition(default_composition())))
        except ValueError as ex:
            self.composition = default_composition()
            self.composition_error = str(ex)

        # Set mode
        self.is_instance_mode = (self.is_filter_name_context or
                                str(session_settings.get('mode', 'type')).lower() == 'instance')
        self.btn_mode.IsChecked = self.is_instance_mode

        if self.txt_delimiters:
            saved_delims = session_settings.get('delimiters', DEFAULT_DELIMITERS)
            self.txt_delimiters.Text = saved_delims if saved_delims else DEFAULT_DELIMITERS
        # Set counter inputs
        if self.combo_final_case:
            final_case = session_settings.get('final_case', 'None')
            case_options = ['None', 'upper', 'lower', 'title', 'sentence']
            try:
                self.combo_final_case.SelectedIndex = case_options.index(final_case)
            except ValueError:
                self.combo_final_case.SelectedIndex = 0

        if self.txt_find:
            self.txt_find.Text = session_settings.get('find_text', '') or ''
        if self.txt_replace:
            self.txt_replace.Text = session_settings.get('replace_text', '') or ''
        self.chk_match_whole_word.IsChecked = session_settings['match_whole_word'].lower() == 'true'
        self.chk_match_case.IsChecked = session_settings['match_case'].lower() == 'true'
        
        # Collect all parameters
        if self.is_filter_name_context:
            self.available_params, self.param_values_map = [], {}
        else:
            self.available_params, self.param_values_map = collect_all_parameters(
                self.elements, self.is_instance_mode)
        
        self.populate_source_parameters(session_settings.get('orig_param', ''))
        self.populate_sort_options(session_settings)
        
        # Create preview items
        for elem in self.elements:
            if self.is_filter_name_context:
                current_name = self.get_original_source_text(elem)
            elif self.is_instance_mode:
                current_name = _safe_element_name(elem)
                if not current_name:
                    try:
                        current_name = "<Instance {}>".format(elem.Id.IntegerValue)
                    except:
                        current_name = "<Unnamed Instance>"
            else:
                # Type mode - get the type
                elem_type = None
                if isinstance(elem, ElementType):
                    elem_type = elem
                else:
                    try:
                        type_id = elem.GetTypeId()
                        if type_id.Value != -1:
                            elem_type = doc.GetElement(type_id)
                    except:
                        pass
                
                if elem_type:
                    current_name = _safe_type_name(elem_type)
                    if not current_name:
                        current_name = "<Unnamed Type {}>".format(elem_type.Id.IntegerValue)
                    elem = elem_type
                else:
                    continue
            
            preview_item = PreviewItem(elem, current_name)
            preview_item.SelectionIndex = len(self.preview_items)
            self.preview_items.Add(preview_item)
        
        # Set grid data source
        self.preview_grid.ItemsSource = self.preview_items
        self.preview_view = CollectionViewSource.GetDefaultView(self.preview_items)
        self.preview_view.Filter = Predicate[object](self.matches_preview_filters)
        
        self._suspend_events = False

        # Store normalized values into current-session settings.
        self.persist_settings()

        # Build initial preview.
        self.update_preview()

        # Update tokenization display for first item

    def populate_source_parameters(self, previous_selection):
        """Keep the system default distinct from real, possibly bracketed names."""
        if not self.combo_orig_param:
            return
        self.combo_orig_param.Items.Clear()
        self.default_source_item = ComboBoxItem()
        self.default_source_item.Content = (
            '<Filter Name>' if getattr(self, 'is_filter_name_context', False)
            else get_default_source_label(self.elements, self.is_instance_mode))
        self.default_source_item.ToolTip = (
            'System default: use each element/type name, not a selected parameter.')
        self.combo_orig_param.Items.Add(self.default_source_item)
        for param_name in self.available_params:
            self.combo_orig_param.Items.Add(param_name)
        if previous_selection and previous_selection in self.available_params:
            self.combo_orig_param.SelectedItem = previous_selection
        else:
            self.combo_orig_param.SelectedIndex = 0

    def populate_sort_options(self, session_settings):
        """Fill Sort by, restoring the session sort only if its parameter still exists."""
        self.sort_descending = str(
            session_settings.get('sort_descending', 'False')).lower() == 'true'
        self.sort_mode = session_settings.get('sort_mode', SORT_NONE)
        self.sort_param = session_settings.get('sort_param', '') or ''
        if self.sort_mode == SORT_PARAM and self.sort_param not in self.available_params:
            self.sort_mode = SORT_NONE
        if self.sort_mode not in (SORT_CURRENT, SORT_PARAM):
            self.sort_mode = SORT_NONE
        if self.sort_mode != SORT_PARAM:
            self.sort_param = ''

        self.combo_sort_by.Items.Clear()
        self.sort_none_item = ComboBoxItem()
        self.sort_none_item.Content = '<Selection order>'
        self.sort_none_item.ToolTip = 'Keep rows in the order the elements were selected.'
        self.sort_current_item = ComboBoxItem()
        self.sort_current_item.Content = '<Current Value>'
        self.sort_current_item.ToolTip = 'Sort by the Current Value column.'
        self.combo_sort_by.Items.Add(self.sort_none_item)
        self.combo_sort_by.Items.Add(self.sort_current_item)
        for param_name in self.available_params:
            self.combo_sort_by.Items.Add(param_name)
        self._select_sort_item()

    def _select_sort_item(self):
        """Show the active sort in the dropdown without triggering its change handler."""
        suspended = self._suspend_events
        self._suspend_events = True
        try:
            if self.sort_mode == SORT_PARAM:
                self.combo_sort_by.SelectedItem = self.sort_param
            elif self.sort_mode == SORT_CURRENT:
                self.combo_sort_by.SelectedItem = self.sort_current_item
            else:
                self.combo_sort_by.SelectedItem = self.sort_none_item
        finally:
            self._suspend_events = suspended

    def OnSortByChanged(self, sender, args):
        if self._suspend_events:
            return
        selected = self.combo_sort_by.SelectedItem
        if selected is None:
            return
        if selected == self.sort_none_item:
            self.sort_mode, self.sort_param = SORT_NONE, ''
        elif selected == self.sort_current_item:
            self.sort_mode, self.sort_param = SORT_CURRENT, ''
        else:
            self.sort_mode, self.sort_param = SORT_PARAM, str(selected)
        self._on_sort_changed()

    def OnSortDirectionClicked(self, sender, args):
        if self.sort_mode == SORT_NONE:
            return
        self.sort_descending = not self.sort_descending
        self._on_sort_changed()

    def OnClearSort(self, sender, args):
        if not self.commit_preview_edits():
            return
        self.sort_mode, self.sort_param = SORT_NONE, ''
        self.sort_descending = False
        self._select_sort_item()
        self.persist_settings()
        self.update_preview()

    def OnGridSorting(self, sender, args):
        """Replace WPF's view sort so numbering always follows the displayed order."""
        args.Handled = True
        if self._is_mouse_over_text_box():
            return
        column = args.Column
        if column == self.col_current:
            if self.sort_mode == SORT_CURRENT:
                self.sort_descending = not self.sort_descending
            else:
                self.sort_mode, self.sort_param = SORT_CURRENT, ''
                self.sort_descending = False
        elif column == self.col_sort_value and self.sort_mode == SORT_PARAM:
            self.sort_descending = not self.sort_descending
        else:
            return
        self._select_sort_item()
        self._on_sort_changed()

    def _is_mouse_over_text_box(self):
        """Header filter boxes sit inside sortable headers; clicks in them must not sort."""
        element = Mouse.DirectlyOver
        while element is not None:
            if isinstance(element, TextBox):
                return True
            try:
                element = VisualTreeHelper.GetParent(element)
            except Exception:
                return False
        return False

    def _on_sort_changed(self):
        if not self.commit_preview_edits():
            return
        self.persist_settings()
        self.update_preview()

    def _update_sort_indicators(self):
        direction = (ListSortDirection.Descending if self.sort_descending
                     else ListSortDirection.Ascending)
        current_is_sorted = self.sort_mode == SORT_CURRENT
        self.col_current.SortDirection = direction if current_is_sorted else None
        self.current_sort_hint.Visibility = (
            WpfVisibility.Collapsed if current_is_sorted else WpfVisibility.Visible)
        if current_is_sorted:
            order = 'descending' if self.sort_descending else 'ascending'
            next_order = 'ascending' if self.sort_descending else 'descending'
            self.current_header_sort_hint.ToolTip = (
                'Sorted {}. Click to sort {}.'.format(order, next_order))
        else:
            self.current_header_sort_hint.ToolTip = 'Click to sort ascending.'
        if self.sort_mode == SORT_PARAM:
            self.col_sort_value.Header = 'Sort: {}'.format(self.sort_param)
            self.col_sort_value.SortDirection = direction
            self.col_sort_value.Visibility = WpfVisibility.Visible
        else:
            self.col_sort_value.SortDirection = None
            self.col_sort_value.Visibility = WpfVisibility.Collapsed
        self.btn_sort_direction.IsChecked = self.sort_descending
        self.btn_sort_direction.IsEnabled = self.sort_mode != SORT_NONE
        self.btn_clear_sort.IsEnabled = self.sort_mode != SORT_NONE

    def get_param_sort_key(self, element, param_name):
        """Return (is_blank, key): numbers by value, Levels by elevation, text naturally."""
        param = self._lookup_parameter(element, param_name)
        if param is None or not param.HasValue:
            return True, None
        storage = param.StorageType
        try:
            if storage == StorageType.Double:
                return False, (0, param.AsDouble())
            if storage == StorageType.Integer:
                return False, (0, param.AsInteger())
            if storage == StorageType.ElementId:
                referenced = doc.GetElement(param.AsElementId())
                if isinstance(referenced, Level):
                    return False, (0, referenced.Elevation)
                text = _elementid_param_to_text(param)
            else:
                text = param.AsString()
        except Exception:
            text = self.get_param_value(element, param_name)
        if not text or not text.strip():
            return True, None
        return False, (1, natural_sort_key(text))

    def sort_preview_items(self):
        """Reorder the rows in place; keys never depend on New Value, so this cannot loop."""
        entries = None
        for item in self.preview_items:
            item.SortValue = ''
        if self.sort_mode == SORT_CURRENT:
            entries = {}
            for item in self.preview_items:
                text = item.CurrentName or ''
                entries[item] = (not text.strip(), natural_sort_key(text))
        elif self.sort_mode == SORT_PARAM:
            entries = {}
            for item in self.preview_items:
                entries[item] = self.get_param_sort_key(item.Element, self.sort_param)
                item.SortValue = self.get_param_value(item.Element, self.sort_param)
        ordered = order_preview_rows(list(self.preview_items), entries, self.sort_descending)
        if hasattr(self.preview_items, 'Move'):
            for target_index, item in enumerate(ordered):
                current_index = self.preview_items.IndexOf(item)
                if current_index != target_index:
                    self.preview_items.Move(current_index, target_index)
        else:
            self.preview_items[:] = ordered
        self._update_sort_indicators()

    def _selected_combo_text(self, combo):
        """Get selected ComboBox item text safely."""
        if not combo or not combo.SelectedItem:
            return ''
        return str(combo.SelectedItem).strip()

    def _composition_uses_counter(self):
        return _composition_uses_counter(self.composition)

    def persist_settings(self):
        """Persist current UI settings for this Revit session only."""
        if getattr(self, 'is_filter_name_context', False):
            return
        try:
            validate_composition(self.composition)
            serialized_composition = serialize_composition(self.composition)
            self.composition_error = ''
        except ValueError as ex:
            self.composition_error = str(ex)
            return
        mode = 'instance' if self.is_instance_mode else 'type'
        save_session_setting('mode', mode)
        save_session_setting('delimiters', self.get_delimiters())
        save_session_setting('orig_param', self.get_selected_original_param_name())

        save_session_setting(
            'composition',
            serialized_composition)
        save_session_setting('final_case', self._selected_final_case())

        find_text = self.txt_find.Text if self.txt_find else ''
        replace_text = self.txt_replace.Text if self.txt_replace else ''
        save_session_setting('find_text', find_text)
        save_session_setting('replace_text', replace_text)
        save_session_setting('match_whole_word', bool(self.chk_match_whole_word.IsChecked))
        save_session_setting('match_case', bool(self.chk_match_case.IsChecked))
        save_session_setting('sort_mode', self.sort_mode)
        save_session_setting('sort_param', self.sort_param)
        save_session_setting('sort_descending', self.sort_descending)
    
    def get_tokenizer_func(self):
        """Get the source-tokenizer function for the current delimiter field."""
        delimiters = self.txt_delimiters.Text if getattr(self, 'txt_delimiters', None) else ''
        return build_tokenizer(delimiters if delimiters else DEFAULT_DELIMITERS)

    def get_delimiters(self):
        delimiters = self.txt_delimiters.Text if getattr(self, 'txt_delimiters', None) else ''
        return delimiters if delimiters else DEFAULT_DELIMITERS

    def _selected_final_case(self):
        """Return the selected final-case option."""
        if not self.combo_final_case or not self.combo_final_case.SelectedItem:
            return 'None'
        selected = self.combo_final_case.SelectedItem
        if hasattr(selected, 'Tag') and selected.Tag is not None:
            return str(selected.Tag)
        if hasattr(selected, 'Content'):
            selected = selected.Content
        return str(selected)
    
    def _lookup_parameter(self, element, param_name):
        """Find a parameter using the mode rules: type mode reads the type;
        instance mode tries the instance first, then its type."""
        if getattr(self, 'is_filter_name_context', False):
            return None
        param_name = str(param_name or '').strip()
        if not param_name:
            return None

        # In type mode, resolve selected element to type before lookup.
        target = element
        if not self.is_instance_mode:
            resolved_type = _get_element_type(element)
            if resolved_type:
                target = resolved_type

        param = None
        try:
            param = target.LookupParameter(param_name)
        except:
            param = None

        if not param and self.is_instance_mode:
            resolved_type = _get_element_type(element)
            if resolved_type:
                try:
                    param = resolved_type.LookupParameter(param_name)
                except:
                    param = None
        return param

    def get_param_value(self, element, param_name):
        """Get parameter value as string from element"""
        try:
            param = self._lookup_parameter(element, param_name)
            if param:
                if param.HasValue:
                    param_storage = param.StorageType
                    
                    if param_storage == StorageType.String:
                        value = param.AsString()
                        return str(value) if value else ""
                    elif param_storage == StorageType.Double:
                        value = param.AsValueString()
                        return str(value) if value else ""
                    elif param_storage == StorageType.Integer:
                        value = param.AsInteger()
                        return str(value) if value is not None else ""
                    elif param_storage == StorageType.ElementId:
                        value = _elementid_param_to_text(param)
                        return str(value) if value else ""
                    else:
                        try:
                            value = param.AsString()
                            return str(value) if value else ""
                        except:
                            pass
        except Exception as e:
            print("Error getting param '{}': {}".format(param_name, str(e)))
        
        return ""
    
    def get_selected_param_values(self, element):
        """Get values for parameter names referenced by the composition."""
        if getattr(self, 'is_filter_name_context', False):
            return {}
        values = {}
        for item in self.composition['operations']:
            if item['kind'] == 'parameter':
                name = item.get('parameter', '').strip()
                if name and name not in values:
                    values[name] = self.get_param_value(element, name)
        return values
    
    def get_original_source_text(self, element):
        """Get the text to use as source for tokenization"""
        if getattr(self, 'is_filter_name_context', False):
            initial = getattr(self, 'initial_names', {})
            return initial.get(element.UniqueId, element.Name or '') if initial else (element.Name or '')
        param_name = self.get_selected_original_param_name()
        if param_name:
            return self.get_param_value(element, param_name)
        
        # Fall back to element/type name
        if self.is_instance_mode:
            return _safe_element_name(element)
        else:
            return _safe_type_name(element)

    def get_selected_original_param_name(self):
        """Get selected original/source parameter name, or empty string for Name mode."""
        if getattr(self, 'is_filter_name_context', False):
            return ''
        if not self.combo_orig_param:
            return ''

        selected = self.combo_orig_param.SelectedItem
        if selected is self.default_source_item or not selected:
            return ''

        return str(selected).strip()
    
    def get_token_sample_item(self):
        """Use displayed order, not the order in which cells were selected."""
        grid = self.preview_grid
        if not grid.Items.Count:
            return None
        selected = set(cell.Item for cell in grid.SelectedCells if cell.IsValid)
        if len(selected) == 1:
            return next(iter(selected))
        if selected:
            for item in grid.Items:
                if item in selected:
                    return item
        return grid.Items[0]

    def update_tokenization_display(self):
        """Refresh the visible source-token preview without recalculating preview values."""
        if getattr(self, '_suspend_events', False):
            return
        editor = getattr(self, 'token_editor', None)
        if editor is not None:
            editor.refresh()
        field = self.window.FindName('tokenized_sample')
        if not field:
            return
        item = self.get_token_sample_item()
        if item is None:
            field.Text = 'Tokens: (no visible rows)'
            return
        source = item.CurrentName if item.CurrentName is not None else ''
        tokens = self.get_tokenizer_func()(source)
        field.Text = 'Tokens: ' + (' '.join(
            '[{0}] {1}'.format(index + 1, token)
            for index, token in enumerate(tokens)) if tokens else '(none)')

    def get_counter_generator(self):
        """Compatibility hook; Counter values are generated per chip."""
        if not self._composition_uses_counter():
            return None, None
        counter_item = next(
            item for item in self.composition['operations']
            if item['kind'] == 'counter')
        return build_counter_generator(
            counter_item.get('start', 'A'),
            str(counter_item.get('increment', 1)))
    
    def update_preview(self):
        """Sort, then number only rows passing the Current Value and parameter filters,
        in display order. The New Value filter is excluded so it can never renumber."""
        composition = self.composition
        tokenizer_func = self.get_tokenizer_func()

        if getattr(self, 'composition_error', ''):
            for item in self.preview_items:
                item.NewName = ''
                item.tooltip = 'Composition Error: {}'.format(self.composition_error)
            self.refresh_preview_filters(recompute_matches=False)
            self.update_tokenization_display()
            return

        counter_gen, counter_error = self.get_counter_generator()
        for item in self.preview_items:
            # CurrentName column always reflects the selected tokenization source.
            item.CurrentName = self.get_original_source_text(item.Element)
        self.sort_preview_items()
        self.update_parameter_matches()

        if counter_error:
            for item in self.preview_items:
                item.NewName = ''
                item.tooltip = 'Counter Error: {}'.format(counter_error)

            self.refresh_preview_filters(recompute_matches=False)
            return

        numbered_rows = [item for item in self.preview_items
                         if self.matches_numbering_filters(item)]
        row_contexts = [(item.CurrentName, self.get_selected_param_values(item.Element))
                        for item in numbered_rows]

        sequence_seeds = {}
        if row_contexts:
            first_source, first_values = row_contexts[0]
            first_param_dict = dict(first_values)
            first_tokens = tokenizer_func(first_source)
            for source_ref in _sequence_source_refs(composition):
                sequence_seeds[source_ref] = _resolve_progression_source(
                    source_ref, first_tokens, first_param_dict, composition)

        find_text = self.txt_find.Text if self.txt_find else ''
        replace_text = self.txt_replace.Text if self.txt_replace else ''
        for idx, item in enumerate(numbered_rows):
            original_source, param_values = row_contexts[idx]
            counter_value = counter_gen(idx) if counter_gen else ''
            item.format_value(
                composition,
                param_values,
                tokenizer_func,
                counter_value,
                original_source,
                find_text,
                replace_text,
                sequence_seeds,
                idx,
                match_whole_word=bool(self.chk_match_whole_word.IsChecked),
                match_case=bool(self.chk_match_case.IsChecked),
                final_case=self._selected_final_case(),
            )
        
        self.refresh_preview_filters(recompute_matches=False)
    
    def OnModeChanged(self, sender, args):
        """Called when instance/type mode changes"""
        if self._suspend_events or getattr(self, 'is_filter_name_context', False):
            return

        # Re-initialize with new mode
        self.is_instance_mode = bool(self.btn_mode.IsChecked)

        self._suspend_events = True
        
        # Recollect parameters and reinitialize
        self.available_params, self.param_values_map = collect_all_parameters(
            self.elements, self.is_instance_mode)

        session_settings = load_session_settings()

        self.populate_source_parameters(session_settings.get('orig_param', ''))
        self.populate_sort_options(session_settings)
        
        # Rebuild preview items
        self.preview_items.Clear()
        for elem in self.elements:
            if self.is_instance_mode:
                current_name = _safe_element_name(elem)
                if not current_name:
                    try:
                        current_name = "<Instance {}>".format(elem.Id.IntegerValue)
                    except:
                        current_name = "<Unnamed Instance>"
            else:
                elem_type = None
                if isinstance(elem, ElementType):
                    elem_type = elem
                else:
                    try:
                        type_id = elem.GetTypeId()
                        if type_id.Value != -1:
                            elem_type = doc.GetElement(type_id)
                    except:
                        pass
                
                if elem_type:
                    current_name = _safe_type_name(elem_type)
                    if not current_name:
                        current_name = "<Unnamed Type {}>".format(elem_type.Id.IntegerValue)
                    elem = elem_type
                else:
                    continue
            
            preview_item = PreviewItem(elem, current_name)
            preview_item.SelectionIndex = len(self.preview_items)
            self.preview_items.Add(preview_item)

        self._suspend_events = False
        self.persist_settings()
        self.update_preview()
    
    def OnSettingsChanged(self, sender, args):
        """Called when composition-affecting settings change."""
        if self._suspend_events:
            return
        if self.btn_use_orig.IsChecked and (
                self.composition != original_composition()):
            self.btn_use_orig.IsChecked = False
            self._composition_before_original = None
        self.persist_settings()
        self.update_preview()
        self.update_tokenization_display()
    
    def OnGridSelectionChanged(self, sender, args):
        """Called when grid selection changes"""
        self.update_tokenization_display()

    def matches_numbering_filters(self, item):
        """Filters that decide which rows are numbered; they never depend on New Value."""
        current_filter = self.txt_filter_current.Text.lower()
        return item.FilterMatch and current_filter in item.CurrentName.lower()

    def matches_preview_filters(self, item):
        """Display filter: numbering filters plus the find-only New Value filter."""
        new_filter = self.txt_filter_new.Text.lower()
        return (self.matches_numbering_filters(item)
                and new_filter in item.NewName.lower())

    def new_value_filter_active(self):
        return bool(self.txt_filter_new.Text)

    def update_parameter_matches(self):
        """Cache read-only parameter filter matches for every row."""
        self._parameter_filter_error = ''
        if getattr(self, 'is_filter_name_context', False):
            self.parameter_filter = None
            self._invalid_filter_values = 0
            for item in self.preview_items:
                item.FilterMatch = True
            return
        try:
            validate_expression(self.parameter_filter, self.available_params)
        except ValueError as ex:
            self._parameter_filter_error = str(ex)
        invalid_values = 0
        for item in self.preview_items:
            item.FilterMatch = False
            if not self._parameter_filter_error:
                values = {}

                def get_value(parameter):
                    if parameter not in values:
                        values[parameter] = self.get_param_value(item.Element, parameter)
                    return values[parameter]

                matched = evaluate_expression(
                    self.parameter_filter, get_value,
                    lambda value, node: compare_filter_rule(
                        value, node, self._decimal_separator, self._group_separator))
                item.FilterMatch = matched is True
                if matched is None:
                    invalid_values += 1
        self._invalid_filter_values = invalid_values

    def refresh_preview_filters(self, recompute_matches=True):
        """Refresh the WPF view, status line and Apply availability."""
        if recompute_matches:
            self.update_parameter_matches()
        invalid_values = self._invalid_filter_values
        self.preview_view.Refresh()
        rules = count_rules(self.parameter_filter)
        self.txt_filter_summary.Text = (
            '{} rule(s) - Custom grouping'.format(rules) if rules else 'No parameter filters')
        if getattr(self, 'is_filter_name_context', False):
            self.txt_filter_summary.Text = 'Filter names only (no parameter filters)'
        self.txt_filter_summary.ToolTip = serialize_expression(self.parameter_filter)
        self.btn_clear_filters.IsEnabled = self.parameter_filter is not None
        self.btn_apply.IsEnabled = not (
            self._parameter_filter_error
            or self.new_value_filter_active()
            or bool(getattr(self, 'composition_error', '')))
        self.btn_apply.ToolTip = (
            getattr(self, 'composition_error', '')
            if getattr(self, 'composition_error', '')
            else (self.btn_apply.FindResource('NewValueFilterToolTip')
                  if self.new_value_filter_active() else None))
        status = '{} of {} rows displayed.'.format(
            self.preview_grid.Items.Count, len(self.preview_items))
        if self._parameter_filter_error:
            status += ' ' + self._parameter_filter_error
        elif invalid_values:
            status += (' {} row(s) excluded: blank/non-numeric or unsupported display '
                       'format (use decimal project units).').format(invalid_values)
        self.txt_filter_status.Text = status

    def commit_preview_edits(self):
        if not self.preview_grid.CommitEdit(DataGridEditingUnit.Cell, True):
            forms.alert("Finish editing the preview cell before continuing.")
            return False
        if not self.preview_grid.CommitEdit(DataGridEditingUnit.Row, True):
            forms.alert("Finish editing the preview row before continuing.")
            return False
        return True

    def OnEditFilters(self, sender, args):
        if getattr(self, 'is_filter_name_context', False):
            return
        if not self.commit_preview_edits():
            return
        from filter_editor import FilterEditor
        editor = FilterEditor(self.window, self.available_params, self.parameter_filter)
        accepted, node = editor.show()
        if accepted:
            self.parameter_filter = node
            self.update_preview()

    def OnClearFilters(self, sender, args):
        if not self.commit_preview_edits():
            return
        self.parameter_filter = None
        self.update_preview()

    def OnPreviewFilterChanged(self, sender, args):
        if self._suspend_events:
            return
        if not self.commit_preview_edits():
            return
        if sender == self.txt_filter_new:
            # Find-only: hide/show rows without renumbering (renumbering would be circular).
            self.refresh_preview_filters(recompute_matches=False)
        else:
            self.update_preview()

    def OnHelp(self, sender, args):
        """Lazy-load help viewer only when Help is clicked."""
        try:
            from help_viewer import show_help
            show_help(SCRIPT_DIR, "KW ReValue")
        except Exception as ex:
            forms.alert("Could not open Help window: {}".format(str(ex)))
    
    def OnApply(self, sender, args):
        """Apply changes and reload the preview without closing the dialog."""
        try:
            if not self.commit_preview_edits():
                return
            if self._parameter_filter_error:
                forms.alert(self._parameter_filter_error)
                return
            if self.new_value_filter_active():
                forms.alert(NEW_VALUE_FILTER_WARNING)
                return
            if getattr(self, 'draft_only', False):
                proposals = dict((item.Element, item.NewName) for item in self.preview_grid.Items)
                try:
                    accepted = self.rename_writer(proposals)
                except Exception as ex:
                    forms.alert("Could not return filter-name proposals: {}".format(str(ex)))
                    return
                if accepted is False:
                    return
                self.applied = True
                self.window.Close()
                return
            revalue_map = self.get_revalue_map()
            if not revalue_map:
                forms.alert("No changes to apply.")
                return
            if getattr(self, 'is_filter_name_context', False):
                try:
                    result = self.rename_writer(revalue_map)
                    if result is False:
                        forms.alert("Filter rename was not completed.")
                        return
                except Exception as ex:
                    forms.alert("Could not rename filters: {}".format(str(ex)))
                    return
                self.applied = True
                forms.alert("Renamed {} filter(s) successfully.".format(len(revalue_map)))
            else:
                target_param_name = _resolve_target_param_name(
                    self.get_selected_original_param_name())
                if not revalue_elements(revalue_map, self.is_instance_mode, target_param_name):
                    return

            self._suspend_events = True
            try:
                self.txt_find.Text = ''
                self.txt_replace.Text = ''
                for item in self.preview_items:
                    item.final = False
            finally:
                self._suspend_events = False
            self.persist_settings()
            self.update_preview()
        finally:
            # Revit-owned result alerts can leave the unowned WPF window behind Revit.
            if self.window.IsVisible:
                self.window.Activate()
                self.window.Focus()

    def OnUseOriginal(self, sender, args):
        """Temporarily use an Original operation, or restore the saved composition."""
        if self.btn_use_orig.IsChecked:
            self._composition_before_original = deep_copy_composition(self.composition)
            self.composition = original_composition()
        elif self._composition_before_original is not None:
            self.composition = deep_copy_composition(self._composition_before_original)
            self._composition_before_original = None
        self.persist_settings()
        self.update_preview()

    def OnClose(self, sender, args):
        """Close without applying pending changes."""
        self.window.Close()
    
    def show_dialog(self):
        """Show the dialog for repeated re-value actions."""
        self.window.ShowDialog()
    
    def get_revalue_map(self):
        """Get changes only for rows included in the filtered preview."""
        revalue_map = {}
        for item in self.preview_grid.Items:
            if (item.NewName != item.CurrentName and
                    (item.NewName or getattr(self, 'is_filter_name_context', False))):
                revalue_map[item.Element] = item.NewName
        return revalue_map


def show_filter_names(elements, rename_writer):
    """Show a name-only modal preview; return whether any Apply succeeded.

    rename_writer receives {native FilterElement: approved_name}. It must validate
    names, IDs and ownership, write atomically, and raise on failure. ReValue never
    starts a transaction or falls back to parameter/type writes in this context.
    """
    if not callable(rename_writer):
        raise TypeError("rename_writer must be callable.")
    elements = list(elements)
    if any(not isinstance(element, FilterElement) for element in elements):
        raise TypeError("Expected native Revit FilterElement objects.")
    if not elements:
        return False
    dialog = ReValueDialog(elements, launch_context='filter_names',
                          rename_writer=rename_writer)
    dialog.show_dialog()
    return dialog.applied


def show_filter_name_drafts(elements, proposed_names, accept_proposals):
    """Transform proposed names without writing; return whether proposals were accepted.

    proposed_names is keyed by native UniqueId. The callback receives native
    FilterElements mapped to proposal text; the caller owns validation/commit.
    """
    elements = list(elements)
    if not callable(accept_proposals):
        raise TypeError("accept_proposals must be callable.")
    if any(not isinstance(element, FilterElement) for element in elements):
        raise TypeError("Expected native Revit FilterElement objects.")
    if set(proposed_names) != set(element.UniqueId for element in elements):
        raise ValueError("Proposals must correspond exactly to the supplied filters.")
    if any(not isinstance(value, basestring) for value in proposed_names.values()):
        raise TypeError("Filter-name proposals must be text.")
    if not elements:
        return False
    dialog = ReValueDialog(elements, launch_context='filter_names',
                          rename_writer=accept_proposals, initial_names=proposed_names,
                          draft_only=True)
    dialog.show_dialog()
    return dialog.applied


# ============================================================================
# Main Script Logic
# ============================================================================
def get_selected_elements():
    """Preserve preselection; otherwise choose on-screen or category selection."""
    selection = uidoc.Selection.GetElementIds()
    
    elements = []
    
    if selection.Count > 0:
        for elem_id in selection:
            elem = doc.GetElement(elem_id)
            if elem:
                elements.append(elem)
    
    if len(elements) == 0:
        choice = forms.CommandSwitchWindow.show(
            ['Select on Screen', 'Select Categories', 'Cancel'],
            message='Choose elements to work with')
        if not choice or choice == 'Cancel':
            return None
        if choice == 'Select Categories':
            from category_selection import select_by_categories
            return select_by_categories(doc, doc.ActiveView)
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select elements to re-value")
            for ref in refs:
                elem = doc.GetElement(ref.ElementId)
                if elem and elem not in elements:
                    elements.append(elem)
        except OperationCanceledException:
            return None
    
    return elements


def revalue_elements(revalue_map, is_instance_mode, target_param_name=''):
    """Re-value elements based on the revalue map (name or parameter target)."""
    if not revalue_map:
        forms.alert("No elements to re-value.")
        return False

    try:
        success_count = 0
        failed_count = 0

        if doc.IsModifiable:
            # When another transaction is already open, Revit may merge undo records.
            # We still execute safely, but cannot guarantee a new top-level undo item.
            print("INFO: Document is already modifiable; changes may merge into an existing undo record.")
            write_scope = SubTransaction(doc)
            write_scope.Start()
            try:
                for element, new_name in revalue_map.items():
                    try:
                        if target_param_name:
                            success = _safe_set_parameter_value(
                                element, target_param_name, new_name, is_instance_mode)
                        else:
                            if is_instance_mode:
                                success = _transactional_set_instance_name(element, new_name)
                            else:
                                success = _safe_set_type_name(element, new_name)

                        if success:
                            success_count += 1
                        else:
                            if target_param_name:
                                print("ERROR re-valuing element id {} parameter '{}' to '{}': No writable parameter found.".format(
                                    element.Id.IntegerValue, target_param_name, new_name))
                            else:
                                print("ERROR re-valuing element id {} to '{}': No writable name field found.".format(
                                    element.Id.IntegerValue, new_name))
                            failed_count += 1
                    except Exception as e:
                        if target_param_name:
                            print("ERROR re-valuing element id {} parameter '{}' to '{}': {}".format(
                                element.Id.IntegerValue, target_param_name, new_name, str(e)))
                        else:
                            print("ERROR re-valuing element id {} to '{}': {}".format(
                                element.Id.IntegerValue, new_name, str(e)))
                        failed_count += 1
                write_scope.Commit()
            except Exception:
                write_scope.RollBack()
                raise
        else:
            tg = TransactionGroup(doc, "Re-Value Elements")
            tg.Start()
            tx = Transaction(doc, "Re-Value Elements")
            tx.Start()
            try:
                for element, new_name in revalue_map.items():
                    try:
                        if target_param_name:
                            success = _safe_set_parameter_value(
                                element, target_param_name, new_name, is_instance_mode)
                        else:
                            if is_instance_mode:
                                success = _transactional_set_instance_name(element, new_name)
                            else:
                                success = _safe_set_type_name(element, new_name)

                        if success:
                            success_count += 1
                        else:
                            if target_param_name:
                                print("ERROR re-valuing element id {} parameter '{}' to '{}': No writable parameter found.".format(
                                    element.Id.IntegerValue, target_param_name, new_name))
                            else:
                                print("ERROR re-valuing element id {} to '{}': No writable name field found.".format(
                                    element.Id.IntegerValue, new_name))
                            failed_count += 1
                    except Exception as e:
                        if target_param_name:
                            print("ERROR re-valuing element id {} parameter '{}' to '{}': {}".format(
                                element.Id.IntegerValue, target_param_name, new_name, str(e)))
                        else:
                            print("ERROR re-valuing element id {} to '{}': {}".format(
                                element.Id.IntegerValue, new_name, str(e)))
                        failed_count += 1

                tx.Commit()
                tg.Assimilate()
            except Exception:
                if tx.GetStatus() == TransactionStatus.Started:
                    tx.RollBack()
                tg.RollBack()
                raise
        
        message = "Re-valued {} element(s) successfully.".format(success_count)
        if failed_count > 0:
            message += "\n{} element(s) failed (see output for details).".format(failed_count)
        
        forms.alert(message)
        return True
        
    except Exception as e:
        forms.alert("Error during re-value: {}".format(str(e)))
        return False


def _resolve_target_param_name(selected_source_name):
    """Normalize source selection into explicit write target.

    Empty values route to rename mode (empty target parameter).
    """
    if selected_source_name is None:
        return ''

    try:
        normalized = str(selected_source_name).strip()
    except Exception:
        return ''

    if not normalized:
        return ''

    lowered = normalized.lower()
    if lowered in ['<none>', '(none)', 'none']:
        return ''

    return normalized


# ============================================================================
# Main Execution
# ============================================================================
if __name__ == '__main__':
    elements = get_selected_elements()
    if elements is None:
        _pyscript.exit()
    
    if not elements:
        forms.alert("No elements selected.", exitscript=True)
    
    dialog = ReValueDialog(elements, is_instance_mode=False)
    dialog.show_dialog()
