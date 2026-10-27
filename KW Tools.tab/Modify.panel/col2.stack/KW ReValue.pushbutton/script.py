# -*- coding: utf-8 -*-
""""KW ReValue"
Re-value types/instances using advanced tokenization and pattern mapping.
Decompose names into tokens, apply parameter re-valuation, reconstruct with flexible syntax.
"""

__title__ = 'KW\nReValue'
__author__ = 'Kent Watson'

import clr
import os
import re
from decimal import Decimal, InvalidOperation
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xaml')

from System.Windows import Window, GridLength, GridUnitType
from System import Predicate
from System.Windows.Controls import ComboBoxItem, DataGridEditingUnit
from System.Windows.Data import CollectionViewSource
from System.Windows.Markup import XamlReader
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

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
element_id_value = get_elementid_value_func()

SCRIPT_DIR = os.path.dirname(__file__)

_ENV_PREFIX = 'KWReValue'
_SESSION_SETTING_DEFAULTS = {
    'mode': 'type',
    'delimiters': r'-_/,\|',
    'orig_param': '',
    'param1': '',
    'param2': '',
    'param3': '',
    'param4': '',
    'param5': '',
    'pattern': '{val1}',
    'final_case': 'None',
    'counter_start': 'A',
    'counter_increment': '1',
    'find_text': '',
    'replace_text': '',
    'match_whole_word': 'False',
    'match_case': 'True',
}


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

VAL_EXPR_REGEX = re.compile(r'\{([^{}]+)\}')
NUMERIC_REGEX = re.compile(r'^\d+$')
ALPHA_REGEX = re.compile(r'^[A-Za-z]+$')
MIXED_SUFFIX_NUM_REGEX = re.compile(r'^(.*?)(\d+)$')

def _parse_val_expression(expr):
    """Parse the inside of {...}.
    
    Supported start specs:
      valN      - 1-based absolute index
      end       - last token
      end-N     - Nth token from the end (end-1 = 2nd to last, end-2 = 3rd to last)
    
    Supported forms (start[:end][|delim]):
      valN
      end
      end-N
      valN:M
      valN:+K
      valN:end
      valN:end-K
      end-N:end
      end-N:end-K
      end-N:+K
      valN:M|delim
      valN:end|delim
      end-N:end|delim
      end-N:end-K|delim
    
    Delimiter can be:
      - Named: space, hyphen, underscore
      - Literal: -, _, /, etc. (but NOT spaces as literals; use 'space' instead)
    
    Returns:
      (start_idx, end_spec, delimiter_string_or_None)
      start_idx is an int (1-based) or a string 'end'/'end-N'
    """
    # Split off optional delimiter part: "core|delim"
    if '|' in expr:
        core, delim_part = expr.split('|', 1)
        delim_part_stripped = delim_part.strip()
        # Check named delimiters first
        if delim_part_stripped in NAMED_DELIMS:
            delimiter = NAMED_DELIMS[delim_part_stripped]
        else:
            # Use stripped version as literal fallback (handles most cases)
            delimiter = delim_part_stripped if delim_part_stripped else None
    else:
        core = expr
        delimiter = None

    core = core.strip()

    def _parse_start(s):
        """Parse a start spec string into int (1-based) or string 'end'/'end-N'."""
        if s.startswith('val'):
            try:
                return int(s[3:])
            except ValueError:
                return None
        elif s == 'end':
            return 'end'
        elif s.startswith('end-'):
            try:
                int(s[4:])  # validate numeric suffix
                return s
            except ValueError:
                return None
        return None

    if ':' not in core:
        start_idx = _parse_start(core)
        if start_idx is None:
            return None, None, delimiter
        return start_idx, None, delimiter

    start_str, end_str = core.split(':', 1)
    start_str = start_str.strip()
    end_str = end_str.strip()

    start_idx = _parse_start(start_str)
    if start_idx is None:
        return None, None, delimiter

    if end_str == 'end':
        end_spec = 'end'
    elif end_str.startswith('end-'):
        # Handle "end-N" syntax (all except last N tokens)
        try:
            k = int(end_str[4:])
            end_spec = 'end-%d' % k
        except ValueError:
            return None, None, delimiter
    elif end_str.startswith('+'):
        try:
            k = int(end_str[1:])
        except ValueError:
            return None, None, delimiter
        end_spec = '+%d' % k
    else:
        try:
            end_idx = int(end_str)
        except ValueError:
            return None, None, delimiter
        end_spec = end_idx

    return start_idx, end_spec, delimiter


def _resolve_window(tokens, start_idx, end_spec):
    """Resolve a token window. start_idx may be int (1-based) or string 'end'/'end-N'."""
    n = len(tokens)
    if n == 0:
        return []

    # Resolve start_pos from start_idx
    if isinstance(start_idx, basestring):
        if start_idx == 'end':
            start_pos = n - 1
        elif start_idx.startswith('end-'):
            try:
                k = int(start_idx[4:])
            except ValueError:
                return []
            start_pos = n - 1 - k
            if start_pos < 0:
                start_pos = 0
        else:
            return []
    else:
        if start_idx < 1:
            start_idx = 1
        if start_idx > n:
            return []
        start_pos = start_idx - 1

    if end_spec is None:
        end_pos = start_pos
    elif end_spec == 'end':
        end_pos = n - 1
    elif isinstance(end_spec, basestring) and end_spec.startswith('end-'):
        try:
            k = int(end_spec[4:])
        except ValueError:
            return []
        end_pos = max(start_pos, n - 1 - k)
    elif isinstance(end_spec, int):
        end_pos = min(end_spec - 1, n - 1)
    elif isinstance(end_spec, basestring) and end_spec.startswith('+'):
        try:
            k = int(end_spec[1:])
        except ValueError:
            return []
        end_pos = min(start_pos + k, n - 1)
    else:
        return []

    if end_pos < start_pos:
        return []

    return tokens[start_pos:end_pos + 1]


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


def _parse_progression_expression(expression):
    """Parse inc/seq expressions that reference one valN or paramN value."""
    parts = expression.split(':')
    if len(parts) != 3:
        return None

    operation = parts[0].strip().lower()
    source_ref = parts[1].strip().lower()
    if operation not in ['inc', 'seq']:
        return None
    if not PROGRESSION_SOURCE_REGEX.match(source_ref):
        return None

    try:
        increment = int(parts[2].strip())
    except Exception:
        return None

    return operation, source_ref, increment


CASE_MODIFIERS = ('upper', 'lower', 'title', 'sentence')


def _split_case_modifier(expression):
    """Split a recognized ~case suffix from a pattern placeholder."""
    if '~' not in expression:
        return expression, None
    core, modifier = expression.rsplit('~', 1)
    modifier = modifier.strip().lower()
    if modifier in CASE_MODIFIERS:
        return core.strip(), modifier
    return expression, None


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


def _resolve_progression_source(source_ref, tokens, param_dict):
    """Get one token or selected parameter value for an inc/seq operation."""
    if source_ref.startswith('val'):
        try:
            token_index = int(source_ref[3:]) - 1
            if token_index >= 0 and token_index < len(tokens):
                return tokens[token_index]
        except Exception:
            pass
        return ''

    return param_dict.get(source_ref, '')


def _sequence_source_refs(pattern):
    """Return distinct source references used by sequence expressions."""
    source_refs = []
    for match in VAL_EXPR_REGEX.finditer(pattern or ''):
        expression, unused_case = _split_case_modifier(match.group(1).strip())
        parsed = _parse_progression_expression(expression)
        if parsed and parsed[0] == 'seq' and parsed[1] not in source_refs:
            source_refs.append(parsed[1])
    return source_refs


def build_counter_generator(start_text, increment_text):
    """Build counter generator supporting numeric, alpha, and prefix+numeric."""
    start_text = '' if start_text is None else str(start_text).strip()
    increment_text = '' if increment_text is None else str(increment_text).strip()

    if not start_text:
        return None, 'Start value is required when using {count} or {param6}.'

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


def apply_pattern(input_text, pattern, param_dict, tokenizer_func=None,
                  sequence_seeds=None, row_index=0, warnings=None):
    """Apply pattern to input_text using tokenization and parameter substitution.
    
    First applies tokenization for {valN}, then parameter substitution for {paramN}.
    """
    if tokenizer_func is None:
        tokenizer_func = tokenize
    
    tokens = tokenizer_func(input_text)
    sequence_seeds = sequence_seeds or {}
    if warnings is None:
        warnings = []
    
    def replace_match(m):
        inner = m.group(1).strip()
        expression, case_modifier = _split_case_modifier(inner)

        progression = _parse_progression_expression(expression)
        if progression:
            operation, source_ref, increment = progression
            source_value = _resolve_progression_source(
                source_ref, tokens, param_dict)

            if operation == 'inc':
                result, error = _increment_value(source_value, increment)
            else:
                seed_value = sequence_seeds.get(source_ref, '')
                if not seed_value:
                    error = 'sequence seed is blank'
                    result = source_value
                else:
                    result, error = _increment_value(
                        seed_value, row_index * increment)
                    if error:
                        result = source_value

            if error:
                warnings.append('{}: {}'.format(inner, error))
            return apply_case_conversion(result, case_modifier)

        if expression.lower() == 'orig':
            return apply_case_conversion(param_dict.get('orig', ''), case_modifier)

        if expression.lower() == 'count':
            return apply_case_conversion(param_dict.get('count', ''), case_modifier)
        
        # Try parameter substitution first ({paramN})
        if expression.lower().startswith('param'):
            try:
                param_num = int(expression[5:])
                key = 'param{}'.format(param_num)
                if key in param_dict:
                    return apply_case_conversion(param_dict[key], case_modifier)
                return apply_case_conversion('', case_modifier)
            except ValueError:
                pass
        
        # Try token extraction ({valN}, {valN:M}, etc)
        start_idx, end_spec, delim = _parse_val_expression(expression)

        if start_idx is None:
            return m.group(0)

        window_tokens = _resolve_window(tokens, start_idx, end_spec)
        joiner = delim if delim is not None else '-'
        return apply_case_conversion(joiner.join(window_tokens), case_modifier)

    result = VAL_EXPR_REGEX.sub(replace_match, pattern)
    return result


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

    Views and other instance-like elements are first tried through writable
    parameters when available, then fall back to the standard name setter.
    """
    if element is None:
        return False

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
    
    with open(xaml_file, 'r') as f:
        xaml_string = f.read()
    
    window = XamlReader.Parse(xaml_string)
    return window


# ============================================================================
# Preview Item Class
# ============================================================================
FILTER_CONDITIONS = (
    'Equals', 'Does not equal', 'Contains', 'Starts with', 'Ends with',
    'Is blank', 'Is not blank', 'Greater than', 'Less than',
    'Greater than or equal to', 'Less than or equal to',
)
NUMERIC_FILTER_CONDITIONS = FILTER_CONDITIONS[7:]


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
    if condition == 'Starts with':
        return actual.startswith(target)
    if condition == 'Ends with':
        return actual.endswith(target)
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

    @property
    def HasChanges(self):
        return self.NewName != self.CurrentName
    
    def format_value(self, pattern, param_values, tokenizer_func, counter_value='', original_value='', find_text='', replace_text='', sequence_seeds=None, row_index=0, match_whole_word=False, match_case=True, final_case='None'):
        """Format new name using tokenization and parameter substitution"""
        if self.final:
            return
        
        self.tooltip = ''
        try:
            if not pattern:
                self.NewName = ''
                self.tooltip = 'Pattern Required'
                return
            
            pattern = pattern.strip()
            
            # Build parameter dict for substitution
            param_dict = {}
            for i, val in enumerate(param_values, 1):
                param_dict['param{}'.format(i)] = val if val else ''

            param_dict['orig'] = '' if original_value is None else str(original_value)

            # Counter aliases: {param6} and {count}
            param_dict['param6'] = '' if counter_value is None else str(counter_value)
            param_dict['count'] = '' if counter_value is None else str(counter_value)
            
            # Use the tokenization + parameter substitution pattern application
            warnings = []
            new_name = apply_pattern(
                self.CurrentName, pattern, param_dict, tokenizer_func,
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
    def __init__(self, elements, is_instance_mode=False):
        """Initialize dialog with list of elements"""
        # Load XAML window
        self.window = load_xaml_window()
        
        # Store data
        self.elements = elements
        self.is_instance_mode = is_instance_mode
        self.preview_items = ObservableCollection[object]()
        self.available_params = []
        self.param_values_map = {}
        self._suspend_events = False
        self._pattern_before_original = None
        
        # Get controls - mode toggle
        self.radio_type = self.window.FindName('radio_type')
        self.radio_instance = self.window.FindName('radio_instance')
        
        # Get controls - delimiters
        self.txt_delimiters = self.window.FindName('txt_delimiters')
        
        # Get controls - original parameter dropdown
        self.combo_orig_param = self.window.FindName('combo_orig_param')
        
        # Get controls - parameters (5 combos)
        self.param_combos = [
            self.window.FindName('combo_param1'),
            self.window.FindName('combo_param2'),
            self.window.FindName('combo_param3'),
            self.window.FindName('combo_param4'),
            self.window.FindName('combo_param5')
        ]
        
        # Get controls - pattern
        self.txt_pattern = self.window.FindName('txt_pattern')
        self.btn_use_orig = self.window.FindName('btn_use_orig')
        self.combo_final_case = self.window.FindName('combo_final_case')

        # Get controls - optional counter
        self.txt_counter_start = self.window.FindName('txt_counter_start')
        self.txt_counter_increment = self.window.FindName('txt_counter_increment')

        # Get controls - final value find/replace
        self.txt_find = self.window.FindName('txt_find')
        self.txt_replace = self.window.FindName('txt_replace')
        self.chk_match_whole_word = self.window.FindName('chk_match_whole_word')
        self.chk_match_case = self.window.FindName('chk_match_case')
        
        # Get controls - tokenization display
        self.txt_tokenization = self.window.FindName('txt_tokenization')
        
        # Get controls - grid and buttons
        self.preview_grid = self.window.FindName('preview_grid')
        self.txt_filter_current = self.window.FindName('txt_filter_current')
        self.txt_filter_new = self.window.FindName('txt_filter_new')
        self.btn_help = self.window.FindName('btn_help')
        self.btn_apply = self.window.FindName('btn_apply')
        self.btn_close = self.window.FindName('btn_close')
        self.more_settings = self.window.FindName('more_settings')
        self.settings_row = self.window.FindName('settings_row')
        self.preview_row = self.window.FindName('preview_row')
        self.btn_edit_filters = self.window.FindName('btn_edit_filters')
        self.btn_clear_filters = self.window.FindName('btn_clear_filters')
        self.txt_filter_summary = self.window.FindName('txt_filter_summary')
        self.txt_filter_status = self.window.FindName('txt_filter_status')
        self.parameter_filter = None
        self._parameter_filter_error = ''
        number_format = CultureInfo.CurrentCulture.NumberFormat
        self._decimal_separator = number_format.NumberDecimalSeparator
        self._group_separator = number_format.NumberGroupSeparator
        
        # Wire up events
        if self.radio_type:
            self.radio_type.Checked += self.OnModeChanged
        if self.radio_instance:
            self.radio_instance.Checked += self.OnModeChanged
        if self.txt_delimiters:
            self.txt_delimiters.TextChanged += self.OnSettingsChanged
        if self.combo_orig_param:
            self.combo_orig_param.SelectionChanged += self.OnSettingsChanged
        if self.combo_final_case:
            self.combo_final_case.SelectionChanged += self.OnSettingsChanged
        
        for combo in self.param_combos:
            combo.SelectionChanged += self.OnSettingsChanged

        if self.txt_counter_start:
            self.txt_counter_start.TextChanged += self.OnSettingsChanged
        if self.txt_counter_increment:
            self.txt_counter_increment.TextChanged += self.OnSettingsChanged
        if self.txt_find:
            self.txt_find.TextChanged += self.OnSettingsChanged
        if self.txt_replace:
            self.txt_replace.TextChanged += self.OnSettingsChanged
        for checkbox in (self.chk_match_whole_word, self.chk_match_case):
            checkbox.Checked += self.OnSettingsChanged
            checkbox.Unchecked += self.OnSettingsChanged
        
        self.txt_pattern.TextChanged += self.OnSettingsChanged
        self.btn_use_orig.Click += self.OnUseOriginal
        self.preview_grid.SelectedCellsChanged += self.OnGridSelectionChanged
        self.txt_filter_current.TextChanged += self.OnPreviewFilterChanged
        self.txt_filter_new.TextChanged += self.OnPreviewFilterChanged
        self.more_settings.Expanded += self.OnMoreSettingsChanged
        self.more_settings.Collapsed += self.OnMoreSettingsChanged
        self.btn_edit_filters.Click += self.OnEditFilters
        self.btn_clear_filters.Click += self.OnClearFilters

        if self.btn_help:
            self.btn_help.Click += self.OnHelp
        
        self.btn_apply.Click += self.OnApply
        self.btn_close.Click += self.OnClose
        
        # Initialize data
        self.initialize_data()
        
    def initialize_data(self):
        """Initialize parameter list and preview items"""
        self._suspend_events = True
        session_settings = load_session_settings()

        # Set mode
        self.is_instance_mode = str(session_settings.get('mode', 'type')).lower() == 'instance'
        if self.radio_type:
            self.radio_type.IsChecked = not self.is_instance_mode
        if self.radio_instance:
            self.radio_instance.IsChecked = self.is_instance_mode
        
        # Set delimiters
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

        if self.txt_counter_start:
            self.txt_counter_start.Text = session_settings.get('counter_start', 'A') or 'A'
        if self.txt_counter_increment:
            self.txt_counter_increment.Text = session_settings.get('counter_increment', '1') or '1'
        if self.txt_find:
            self.txt_find.Text = session_settings.get('find_text', '') or ''
        if self.txt_replace:
            self.txt_replace.Text = session_settings.get('replace_text', '') or ''
        self.chk_match_whole_word.IsChecked = session_settings['match_whole_word'].lower() == 'true'
        self.chk_match_case.IsChecked = session_settings['match_case'].lower() == 'true'
        
        # Collect all parameters
        self.available_params, self.param_values_map = collect_all_parameters(
            self.elements, self.is_instance_mode)
        
        self.populate_source_parameters(session_settings.get('orig_param', ''))
        
        # Populate parameter combo boxes (5 slots)
        for i, combo in enumerate(self.param_combos):
            if combo:
                combo.Items.Add('')
                for param_name in self.available_params:
                    combo.Items.Add(param_name)

                param_key = 'param{}'.format(i + 1)
                prev_selection = session_settings.get(param_key, '')
                if prev_selection and prev_selection in self.available_params:
                    combo.SelectedItem = prev_selection
                else:
                    combo.SelectedIndex = 0
        
        # Create preview items
        for elem in self.elements:
            if self.is_instance_mode:
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
            self.preview_items.Add(preview_item)
        
        # Set grid data source
        self.preview_grid.ItemsSource = self.preview_items
        self.preview_view = CollectionViewSource.GetDefaultView(self.preview_items)
        self.preview_view.Filter = Predicate[object](self.matches_preview_filters)
        
        # Set pattern
        self.txt_pattern.Text = session_settings.get('pattern', '{val1}') or '{val1}'
        
        self._suspend_events = False

        # Store normalized values into current-session settings.
        self.persist_settings()

        # Build initial preview.
        self.update_preview()

        # Update tokenization display for first item
        self.update_tokenization_display()

    def populate_source_parameters(self, previous_selection):
        """Keep the system default distinct from real, possibly bracketed names."""
        if not self.combo_orig_param:
            return
        self.combo_orig_param.Items.Clear()
        self.default_source_item = ComboBoxItem()
        self.default_source_item.Content = get_default_source_label(
            self.elements, self.is_instance_mode)
        self.default_source_item.ToolTip = (
            'System default: use each element/type name, not a selected parameter.')
        self.combo_orig_param.Items.Add(self.default_source_item)
        for param_name in self.available_params:
            self.combo_orig_param.Items.Add(param_name)
        if previous_selection and previous_selection in self.available_params:
            self.combo_orig_param.SelectedItem = previous_selection
        else:
            self.combo_orig_param.SelectedIndex = 0

    def _selected_combo_text(self, combo):
        """Get selected ComboBox item text safely."""
        if not combo or not combo.SelectedItem:
            return ''
        return str(combo.SelectedItem).strip()

    def _pattern_uses_counter(self):
        """Return True when pattern contains {count} or {param6}."""
        pattern = self.txt_pattern.Text if self.txt_pattern else ''
        if not pattern:
            return False
        return re.search(
            r'\{\s*(count|param6)(?:\s*~\s*(?:upper|lower|title|sentence))?\s*\}',
            pattern, re.IGNORECASE) is not None

    def persist_settings(self):
        """Persist current UI settings for this Revit session only."""
        mode = 'instance' if self.is_instance_mode else 'type'
        save_session_setting('mode', mode)
        save_session_setting('delimiters', self.get_delimiters())
        save_session_setting('orig_param', self.get_selected_original_param_name())

        for i, combo in enumerate(self.param_combos):
            save_session_setting('param{}'.format(i + 1), self._selected_combo_text(combo))

        pattern = self.txt_pattern.Text if self.txt_pattern else ''
        save_session_setting('pattern', pattern)
        save_session_setting('final_case', self._selected_final_case())

        start_text = self.txt_counter_start.Text if self.txt_counter_start else 'A'
        increment_text = self.txt_counter_increment.Text if self.txt_counter_increment else '1'
        save_session_setting('counter_start', start_text)
        save_session_setting('counter_increment', increment_text)

        find_text = self.txt_find.Text if self.txt_find else ''
        replace_text = self.txt_replace.Text if self.txt_replace else ''
        save_session_setting('find_text', find_text)
        save_session_setting('replace_text', replace_text)
        save_session_setting('match_whole_word', bool(self.chk_match_whole_word.IsChecked))
        save_session_setting('match_case', bool(self.chk_match_case.IsChecked))
    
    def get_delimiters(self):
        """Get current delimiters from UI"""
        if self.txt_delimiters:
            return self.txt_delimiters.Text or DEFAULT_DELIMITERS
        return DEFAULT_DELIMITERS
    
    def get_tokenizer_func(self):
        """Get tokenizer function with current delimiters"""
        delimiters = self.get_delimiters()
        return build_tokenizer(delimiters)

    def _selected_final_case(self):
        """Return the selected final-case option."""
        if not self.combo_final_case or not self.combo_final_case.SelectedItem:
            return 'None'
        selected = self.combo_final_case.SelectedItem
        if hasattr(selected, 'Content'):
            selected = selected.Content
        return str(selected)
    
    def get_param_value(self, element, param_name):
        """Get parameter value as string from element"""
        if not param_name:
            return ""
        
        param_name = str(param_name).strip()
        if not param_name:
            return ""
        
        try:
            # In type mode, resolve selected element to type before lookup.
            target = element
            if not self.is_instance_mode:
                resolved_type = _get_element_type(element)
                if resolved_type:
                    target = resolved_type

            # Instance mode may include type parameters in selectors.
            # Try instance first, then fallback to type.
            if self.is_instance_mode:
                param = None
                try:
                    param = target.LookupParameter(param_name)
                except:
                    param = None

                if not param:
                    resolved_type = _get_element_type(element)
                    if resolved_type:
                        try:
                            param = resolved_type.LookupParameter(param_name)
                        except:
                            param = None
            else:
                param = target.LookupParameter(param_name)

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
        """Get values for all 5 selected parameters"""
        values = []
        for combo in self.param_combos:
            if combo:
                selected = combo.SelectedItem
                if selected:
                    param_name = str(selected).strip()
                    if param_name:
                        values.append(self.get_param_value(element, param_name))
                    else:
                        values.append("")
                else:
                    values.append("")
            else:
                values.append("")
        return values
    
    def get_original_source_text(self, element):
        """Get the text to use as source for tokenization"""
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
        if not self.combo_orig_param:
            return ''

        selected = self.combo_orig_param.SelectedItem
        if selected is self.default_source_item or not selected:
            return ''

        return str(selected).strip()
    
    def update_tokenization_display(self):
        """Update tokenization display for first selected item"""
        if self.txt_tokenization and len(self.preview_items) > 0:
            first_item = self.preview_items[0]
            source_text = self.get_original_source_text(first_item.Element)
            
            tokenizer_func = self.get_tokenizer_func()
            tokens = tokenizer_func(source_text)
            
            if tokens:
                token_display = ', '.join(['[{0}] {1}'.format(i+1, t) for i, t in enumerate(tokens)])
                self.txt_tokenization.Text = 'Tokens: {}'.format(token_display)
            else:
                self.txt_tokenization.Text = 'Tokens: (none)'

    def get_counter_generator(self):
        """Build counter generator only when pattern asks for a counter token."""
        if not self._pattern_uses_counter():
            return None, None

        start_text = self.txt_counter_start.Text if self.txt_counter_start else ''
        increment_text = self.txt_counter_increment.Text if self.txt_counter_increment else '1'
        return build_counter_generator(start_text, increment_text)
    
    def update_preview(self):
        """Update preview grid with new names using current pattern"""
        pattern = self.txt_pattern.Text
        tokenizer_func = self.get_tokenizer_func()
        counter_gen, counter_error = self.get_counter_generator()

        if counter_error:
            for item in self.preview_items:
                item.CurrentName = self.get_original_source_text(item.Element)
                item.NewName = ''
                item.tooltip = 'Counter Error: {}'.format(counter_error)

            self.refresh_preview_filters()
            self.update_tokenization_display()
            return
        
        row_contexts = []
        for item in self.preview_items:
            # CurrentName column always reflects the selected tokenization source.
            original_source = self.get_original_source_text(item.Element)
            item.CurrentName = original_source
            param_values = self.get_selected_param_values(item.Element)
            row_contexts.append((original_source, param_values))

        sequence_seeds = {}
        if row_contexts:
            first_source, first_values = row_contexts[0]
            first_param_dict = {}
            for param_index, value in enumerate(first_values, 1):
                first_param_dict['param{}'.format(param_index)] = value if value else ''
            first_tokens = tokenizer_func(first_source)
            for source_ref in _sequence_source_refs(pattern):
                sequence_seeds[source_ref] = _resolve_progression_source(
                    source_ref, first_tokens, first_param_dict)

        for idx, item in enumerate(self.preview_items):
            original_source, param_values = row_contexts[idx]
            counter_value = counter_gen(idx) if counter_gen else ''
            find_text = self.txt_find.Text if self.txt_find else ''
            replace_text = self.txt_replace.Text if self.txt_replace else ''
            item.format_value(
                pattern,
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
        
        self.refresh_preview_filters()
        self.update_tokenization_display()
    
    def OnModeChanged(self, sender, args):
        """Called when instance/type mode changes"""
        if self._suspend_events:
            return

        # Re-initialize with new mode
        if self.radio_instance:
            self.is_instance_mode = self.radio_instance.IsChecked
        else:
            self.is_instance_mode = False

        self._suspend_events = True
        
        # Recollect parameters and reinitialize
        self.available_params, self.param_values_map = collect_all_parameters(
            self.elements, self.is_instance_mode)

        session_settings = load_session_settings()

        self.populate_source_parameters(session_settings.get('orig_param', ''))
        
        # Clear and rebuild parameter combos
        for i, combo in enumerate(self.param_combos):
            combo.Items.Clear()
            combo.Items.Add('')
            for param_name in self.available_params:
                combo.Items.Add(param_name)

            param_key = 'param{}'.format(i + 1)
            prev_selection = session_settings.get(param_key, '')
            if prev_selection and prev_selection in self.available_params:
                combo.SelectedItem = prev_selection
            else:
                combo.SelectedIndex = 0
        
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
            self.preview_items.Add(preview_item)

        self._suspend_events = False
        self.persist_settings()
        self.refresh_preview_filters()
        self.update_preview()
    
    def OnSettingsChanged(self, sender, args):
        """Called when patterns or parameters change"""
        if self._suspend_events:
            return
        if self.btn_use_orig.IsChecked and self.txt_pattern.Text != '{orig}':
            self.btn_use_orig.IsChecked = False
            self._pattern_before_original = None
        self.persist_settings()
        self.update_preview()
    
    def OnGridSelectionChanged(self, sender, args):
        """Called when grid selection changes"""
        self.update_tokenization_display()

    def matches_preview_filters(self, item):
        """Match both header filters without changing preview values or counters."""
        current_filter = self.txt_filter_current.Text.lower()
        new_filter = self.txt_filter_new.Text.lower()
        return (item.FilterMatch and current_filter in item.CurrentName.lower()
                and new_filter in item.NewName.lower())

    def refresh_preview_filters(self):
        """Cache read-only parameter matches before refreshing the WPF view."""
        self._parameter_filter_error = ''
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
        self.preview_view.Refresh()
        rules = count_rules(self.parameter_filter)
        self.txt_filter_summary.Text = (
            '{} rule(s) - Custom grouping'.format(rules) if rules else 'No parameter filters')
        self.txt_filter_summary.ToolTip = serialize_expression(self.parameter_filter)
        self.btn_clear_filters.IsEnabled = self.parameter_filter is not None
        self.btn_apply.IsEnabled = not bool(self._parameter_filter_error)
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
        if not self.commit_preview_edits():
            return
        from filter_editor import FilterEditor
        editor = FilterEditor(self.window, self.available_params, self.parameter_filter)
        accepted, node = editor.show()
        if accepted:
            self.parameter_filter = node
            self.refresh_preview_filters()

    def OnClearFilters(self, sender, args):
        if not self.commit_preview_edits():
            return
        self.parameter_filter = None
        self.refresh_preview_filters()

    def OnPreviewFilterChanged(self, sender, args):
        if self._suspend_events:
            return
        if not self.commit_preview_edits():
            return
        self.refresh_preview_filters()

    def OnMoreSettingsChanged(self, sender, args):
        """Reclaim space when collapsed, including after dragging the divider."""
        self.settings_row.Height = (
            GridLength(2, GridUnitType.Star)
            if self.more_settings.IsExpanded else GridLength.Auto)
        self.preview_row.Height = GridLength(3, GridUnitType.Star)

    def OnHelp(self, sender, args):
        """Lazy-load help viewer only when Help is clicked."""
        try:
            from help_viewer import show_help
            show_help(SCRIPT_DIR, "KW ReValue")
        except Exception as ex:
            forms.alert("Could not open Help window: {}".format(str(ex)))
    
    def OnApply(self, sender, args):
        """Apply changes and reload the preview without closing the dialog."""
        if not self.commit_preview_edits():
            return
        if self._parameter_filter_error:
            forms.alert(self._parameter_filter_error)
            return
        revalue_map = self.get_revalue_map()
        if not revalue_map:
            forms.alert("No changes to apply.")
            return
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

    def OnUseOriginal(self, sender, args):
        """Temporarily use the source value, or restore the previous pattern."""
        if self.btn_use_orig.IsChecked:
            self._pattern_before_original = self.txt_pattern.Text
            self.txt_pattern.Text = '{orig}'
        elif self._pattern_before_original is not None:
            pattern = self._pattern_before_original
            self._pattern_before_original = None
            self.txt_pattern.Text = pattern

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
            if item.NewName and item.NewName != item.CurrentName:
                revalue_map[item.Element] = item.NewName
        return revalue_map


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

    Empty/placeholder values route to rename mode (empty target parameter).
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
