# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
import System
import re
import traceback
import sys
import os
import datetime
import csv
import codecs
import uuid
from System.Windows.Controls import CheckBox
from System.Windows.Controls import TextBox
from System.Windows.Controls import ComboBox
from System.Windows.Controls.Primitives import ButtonBase, ToggleButton
from System.Windows import RoutedEventHandler
from System.Windows import Input
from System.Windows.Media import VisualTreeHelper
from System.Collections.ObjectModel import ObservableCollection
from System.Collections.Generic import List
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommandLinkId
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs


doc = revit.doc

DEFAULT_NAME_PATTERN = "{phase_abbrev~upper}-{level~upper}-{plan_type~upper}"
DEFAULT_SHEET_NAME_PATTERN = "{view_name}"
DEFAULT_TOKEN_DELIMITERS = " \\t\\r\\n!\"#$%&'()*+,-./:;<=>?@[\\\\]^_`{|}~"
CFG_NAME_PATTERN_KEY = "createviews_name_pattern"
CFG_SHEET_NAME_PATTERN_KEY = "createviews_sheet_name_pattern"
CFG_TOKEN_DELIMITERS_KEY = "createviews_token_delimiters"
CFG_SHEET_START_KEY = "createviews_sheet_start"
CFG_SHEET_INCREMENT_KEY = "createviews_sheet_increment"
CFG_DEPENDENT_COUNT_KEY = "createviews_dependent_count"
CFG_TEMPLATE_SHEET_KEY = "createviews_template_sheet"
CFG_COPY_DETAILING_KEY = "createviews_copy_detailing"
CFG_COPY_LEGENDS_KEY = "createviews_copy_legends"
CFG_COPY_SCHEDULES_KEY = "createviews_copy_schedules"
CFG_REMOVE_REVISIONS_KEY = "createviews_remove_revisions"
HISTORY_LIMIT = 25
CFG_NAME_PATTERN_HISTORY_KEY = "createviews_hist_name_pattern"
CFG_NAME_PATTERN_CURRENT_KEY = "createviews_curr_name_pattern"
CFG_SHEET_NAME_PATTERN_HISTORY_KEY = "createviews_hist_sheet_name_pattern"
CFG_SHEET_NAME_PATTERN_CURRENT_KEY = "createviews_curr_sheet_name_pattern"

NUMERIC_REGEX = re.compile(r'^\d+$')
ALPHA_REGEX = re.compile(r'^[A-Za-z]+$')
MIXED_SUFFIX_NUM_REGEX = re.compile(r'^(.*?)(\d+)$')

TEXT_HISTORY_FIELDS = [
    ("namePatternBox", CFG_NAME_PATTERN_HISTORY_KEY, DEFAULT_NAME_PATTERN, CFG_NAME_PATTERN_CURRENT_KEY),
    ("sheetNamePatternBox", CFG_SHEET_NAME_PATTERN_HISTORY_KEY, DEFAULT_SHEET_NAME_PATTERN, CFG_SHEET_NAME_PATTERN_CURRENT_KEY),
    ("phaseAbbrevBox", "createviews_hist_phase_abbrev", "", "createviews_curr_phase_abbrev"),
    ("prefixBox", "createviews_hist_prefix", "", "createviews_curr_prefix"),
    ("suffixBox", "createviews_hist_suffix", "", "createviews_curr_suffix"),
    ("floorNameBox", "createviews_hist_floor_name", "Floor", "createviews_curr_floor_name"),
    ("ceilingNameBox", "createviews_hist_ceiling_name", "Ceiling", "createviews_curr_ceiling_name"),
    ("structNameBox", "createviews_hist_struct_name", "Structural", "createviews_curr_struct_name")
]

RESETTABLE_CFG_KEYS = [
    CFG_NAME_PATTERN_KEY,
    CFG_SHEET_NAME_PATTERN_KEY,
    CFG_TOKEN_DELIMITERS_KEY,
    CFG_SHEET_START_KEY,
    CFG_SHEET_INCREMENT_KEY,
    CFG_DEPENDENT_COUNT_KEY,
    CFG_TEMPLATE_SHEET_KEY,
    CFG_COPY_DETAILING_KEY,
    CFG_COPY_LEGENDS_KEY,
    CFG_COPY_SCHEDULES_KEY,
    CFG_REMOVE_REVISIONS_KEY
]

for _field_name, _history_key, _default_value, _current_key in TEXT_HISTORY_FIELDS:
    RESETTABLE_CFG_KEYS.append(_history_key)
    RESETTABLE_CFG_KEYS.append(_current_key)

sheet_number_counter_state = {
    "signature": None,
    "generator": None,
    "index": 0,
    "error": None
}

token_delimiter_state = {
    "value": DEFAULT_TOKEN_DELIMITERS
}

sheet_number_clash_mode_state = {
    "detail": "Sheet number clash mode: Not evaluated."
}


class QueueRow(INotifyPropertyChanged):
    def __init__(
        self,
        row_id,
        level,
        plan_key,
        plan_type,
        template_name,
        scope_name,
        view_name,
        row_type,
        parent_row_id,
        parent_name,
        row_key=None,
        parent_row_key=None
    ):
        self._changed_handlers = []
        self.RowId = row_id
        self.RowKey = row_key or make_row_key()
        self.Level = level
        self.PlanKey = plan_key
        self.LevelName = level.Name if level else ""
        self.PlanType = plan_type
        self.TemplateName = template_name
        self.ScopeName = scope_name
        self.ViewName = view_name
        self.RowType = row_type
        self.ParentRowId = parent_row_id
        self.ParentRowKey = parent_row_key or ""
        self.ParentName = parent_name
        self.IncludeOnSheet = False
        self.SheetNumberOverride = ""
        self.SheetNameOverride = ""
        self.SheetNamePatternApplied = ""
        self.SheetTemplateName = ""
        self.SheetNumberAssigned = ""
        self.SheetNumberPreview = ""

    def add_PropertyChanged(self, handler):
        self._changed_handlers.append(handler)

    def remove_PropertyChanged(self, handler):
        if handler in self._changed_handlers:
            self._changed_handlers.remove(handler)

    def _notify(self, prop_name):
        try:
            args = PropertyChangedEventArgs(prop_name)
            for handler in list(self._changed_handlers):
                handler(self, args)
        except:
            pass

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name.startswith("_"):
            return
        if name in ("RowId", "RowKey", "Level", "PlanKey", "LevelName", "PlanType", "TemplateName", "ScopeName", "ViewName", "RowType", "ParentRowId", "ParentRowKey", "ParentName", "IncludeOnSheet", "SheetNumberOverride", "SheetNameOverride", "SheetTemplateName", "SheetNumberAssigned", "SheetNumberPreview"):
            try:
                self._notify(name)
            except:
                pass


class PlanSpec(object):
    def __init__(self, key, label, template_name):
        self.Key = key
        self.Label = label
        self.TemplateName = template_name


def _capture_traceback_text():
    try:
        text = traceback.format_exc()
        if text and text.strip() and text.strip() != "NoneType: None":
            return text
    except:
        pass

    try:
        ex_type, ex_value, ex_tb = sys.exc_info()
        if ex_type is not None:
            return ''.join(traceback.format_exception(ex_type, ex_value, ex_tb))
    except:
        pass

    return "No active exception was captured."


def make_row_key():
    try:
        return "cv-{}".format(uuid.uuid4().hex)
    except:
        return "cv-{}".format(str(next_row_id()))


def _exception_details(ex):
    parts = []

    try:
        parts.append("Python Exception Type: {}".format(type(ex)))
    except:
        pass

    try:
        parts.append("Python Exception str: {}".format(str(ex)))
    except:
        pass

    try:
        parts.append("Python Exception repr: {}".format(repr(ex)))
    except:
        pass

    try:
        clr_ex = getattr(ex, 'clsException', None)
        if clr_ex is not None:
            parts.append(".NET Exception: {}".format(clr_ex.ToString()))
    except:
        pass

    tb_text = _capture_traceback_text()
    if tb_text:
        parts.append("Traceback:\n{}".format(tb_text))

    if not parts:
        return "No exception details available."

    return "\n\n".join(parts)


def _write_debug_log(text):
    try:
        root = os.environ.get('TEMP') or os.environ.get('TMP') or '.'
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(root, 'createviews_error_{}.log'.format(stamp))
        with open(path, 'w') as fp:
            fp.write(text or '')
        return path
    except:
        return None


def show_error(message, details=None, title="Create Views Error"):
    head = message or "Unknown error."
    text = head
    detail_text = details
    if not detail_text:
        detail_text = _capture_traceback_text()

    if detail_text:
        text = "{}\n\n{}".format(head, detail_text)

    if not text or not text.strip():
        text = "{}\n\n{}".format(head, "Error text was empty.")

    log_path = _write_debug_log(text)
    if log_path:
        text = "{}\n\nDebug Log: {}".format(text, log_path)

    try:
        forms.alert(text)
        return
    except:
        pass

    print(text)

    try:
        System.Windows.MessageBox.Show(text, title)
        return
    except:
        pass


def _xaml_debug_preview(path_value, max_lines=220):
    lines = []
    try:
        with open(path_value, 'r') as fp:
            idx = 0
            for raw in fp:
                idx += 1
                lines.append("{:04d}: {}".format(idx, raw.rstrip("\n\r")))
                if idx >= max_lines:
                    break
    except Exception:
        lines.append("<failed to read xaml file>")
    return "\n".join(lines)


def natural_sort_key(value):
    text = (value or "").lower()
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', text)]


def cfg_get(name, default_value=None):
    cfg = script.get_config()
    try:
        value = getattr(cfg, name)
        if value is None:
            return default_value
        return value
    except:
        return default_value


def cfg_set(name, value):
    cfg = script.get_config()
    setattr(cfg, name, value)


def cfg_delete(name):
    cfg = script.get_config()
    try:
        delattr(cfg, name)
        return
    except:
        pass

    try:
        setattr(cfg, name, None)
    except:
        pass


def cfg_try_get(name):
    cfg = script.get_config()
    try:
        return True, getattr(cfg, name)
    except:
        return False, None


def as_text(value, default_value=""):
    if value is None:
        return default_value
    try:
        return str(value)
    except:
        return default_value


def as_bool(value, default_value=False):
    if value is None:
        return default_value

    if isinstance(value, bool):
        return value

    try:
        if isinstance(value, int):
            return value != 0
    except:
        pass

    text = as_text(value, "").strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default_value


def parse_history(raw_value):
    raw_text = as_text(raw_value, "")
    if not raw_text:
        return []

    items = []
    seen = set()
    for part in raw_text.split("\n"):
        text = (part or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
    return items


def read_history(key):
    return parse_history(cfg_get(key, ""))


def write_history(key, items):
    cfg_set(key, "\n".join(items[:HISTORY_LIMIT]))


def setup_history_combo(combo, history_key, default_value, current_key):
    items = read_history(history_key)
    combo.Items.Clear()
    for item in items:
        combo.Items.Add(item)

    has_current, current_value = cfg_try_get(current_key)
    if has_current:
        combo.Text = as_text(current_value, "")
    elif items:
        combo.Text = items[0]
    else:
        combo.Text = default_value or ""


def update_history(key, value):
    text = (value or "").strip()
    items = []
    if text:
        items.append(text)

    for existing in read_history(key):
        if text and existing.lower() == text.lower():
            continue
        items.append(existing)

    write_history(key, items)


def save_combo_current_text(combo, current_key):
    try:
        cfg_set(current_key, as_text(getattr(combo, "Text", None), ""))
        script.save_config()
    except:
        pass


def selected_text(combo, default_value=""):
    text = as_text(getattr(combo, "Text", None), "").strip()
    if text:
        return text

    item = combo.SelectedItem
    if item is None:
        return default_value
    return as_text(item, default_value)


def safe_name(name):
    illegal = '\\/:{}[]|;<>?'
    return ''.join(c for c in (name or "") if c not in illegal)


def apply_token_case(text, case_name):
    value = text or ""
    if not case_name:
        return value

    case_key = case_name.strip().lower()
    if case_key == "upper":
        return value.upper()
    if case_key == "lower":
        return value.lower()
    if case_key == "title":
        return value.title()
    return value


def _decode_delimiter_text(encoded_text):
    text = as_text(encoded_text, "")
    if not text:
        return ""

    out = []
    idx = 0
    length = len(text)
    while idx < length:
        ch = text[idx]
        if ch != "\\":
            out.append(ch)
            idx += 1
            continue

        idx += 1
        if idx >= length:
            out.append("\\")
            break

        esc = text[idx]
        idx += 1
        if esc == "t":
            out.append("\t")
        elif esc == "r":
            out.append("\r")
        elif esc == "n":
            out.append("\n")
        elif esc == "s":
            out.append(" ")
        elif esc == "\\":
            out.append("\\")
        else:
            out.append(esc)

    return "".join(out)


def _encode_delimiter_text(raw_text):
    out = []
    for ch in as_text(raw_text, ""):
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\n":
            out.append("\\n")
        elif ch == " ":
            out.append("\\s")
        else:
            out.append(ch)
    return "".join(out)


def _normalize_delimiters(raw_text):
    raw = as_text(raw_text, "")
    if not raw:
        raw = DEFAULT_TOKEN_DELIMITERS

    unique = []
    seen = set()
    for ch in raw:
        if ch in seen:
            continue
        seen.add(ch)
        unique.append(ch)

    if not unique:
        return DEFAULT_TOKEN_DELIMITERS

    return "".join(unique)


def _load_token_delimiters_from_config():
    persisted = as_text(cfg_get(CFG_TOKEN_DELIMITERS_KEY, DEFAULT_TOKEN_DELIMITERS), DEFAULT_TOKEN_DELIMITERS)
    normalized = _normalize_delimiters(persisted)
    token_delimiter_state["value"] = normalized
    return normalized


def _set_token_delimiters(value, persist=False):
    normalized = _normalize_delimiters(value)
    token_delimiter_state["value"] = normalized
    if persist:
        cfg_set(CFG_TOKEN_DELIMITERS_KEY, normalized)
        try:
            script.save_config()
        except:
            pass
    return normalized


def _tokenize_by_delimiters(text, delimiters):
    value = as_text(text, "")
    if not value:
        return []

    delimiter_set = set(delimiters or "")
    parts = []
    current = []
    for ch in value:
        if ch in delimiter_set:
            if current:
                parts.append("".join(current))
                current = []
            continue
        current.append(ch)

    if current:
        parts.append("".join(current))

    return parts


def _resolve_token_index(index_text, count):
    if count <= 0:
        return None

    text = as_text(index_text, "").strip().lower()
    if not text:
        return None

    if text.isdigit():
        value = int(text)
        if value < 1 or value > count:
            return None
        return value

    if text == "end":
        return count

    match = re.match(r'^end\s*([+-])\s*(\d+)$', text)
    if not match:
        return None

    sign = match.group(1)
    offset = int(match.group(2))
    if sign == "+":
        value = count + offset
    else:
        value = count - offset

    if value < 1 or value > count:
        return None
    return value


def _resolve_tokenized_value(base_value, selector_text, delimiters):
    value = as_text(base_value, "")
    selector = as_text(selector_text, "").strip()
    if not selector:
        return value

    parts = _tokenize_by_delimiters(value, delimiters)
    if not parts:
        return ""

    if ":" in selector:
        start_text, end_text = selector.split(":", 1)
        start_idx = _resolve_token_index(start_text, len(parts))
        end_idx = _resolve_token_index(end_text, len(parts))
        if start_idx is None or end_idx is None:
            return ""
        if start_idx > end_idx:
            return ""
        return " ".join(parts[start_idx - 1:end_idx])

    idx = _resolve_token_index(selector, len(parts))
    if idx is None:
        return ""
    return parts[idx - 1]


def _resolve_token_value(token_expr, token_values, delimiters):
    expr = as_text(token_expr, "").strip()
    if not expr:
        return None, False

    token_key = expr.lower()
    selector = ""
    if "." in expr:
        token_key, selector = expr.split(".", 1)
        token_key = token_key.strip().lower()
        selector = selector.strip()

    token_value = token_values.get(token_key)
    if token_value is None:
        return None, False

    if selector and token_key in ("scopebox", "level"):
        return _resolve_tokenized_value(token_value, selector, delimiters), True

    return as_text(token_value, ""), True


def render_name_pattern(pattern, token_values, delimiters=None):
    delimiter_text = _normalize_delimiters(delimiters if delimiters is not None else token_delimiter_state.get("value", DEFAULT_TOKEN_DELIMITERS))

    def _replace(match):
        expr = (match.group(1) or "").strip()
        if not expr:
            return ""

        token_part = expr
        case_part = None
        if "~" in expr:
            token_part, case_part = expr.split("~", 1)

        token_value, found = _resolve_token_value(token_part, token_values, delimiter_text)
        if not found:
            return match.group(0)

        return apply_token_case(token_value, case_part)

    return re.sub(r'\{([^{}]+)\}', _replace, pattern or "")


def build_view_name(pattern, token_values, prefix_text, suffix_text):
    base_name = render_name_pattern(pattern, token_values, token_delimiter_state.get("value", DEFAULT_TOKEN_DELIMITERS))
    return safe_name("{}{}{}".format(prefix_text or "", base_name, suffix_text or ""))


def _alpha_to_int(text):
    total = 0
    for ch in text.upper():
        total = (total * 26) + (ord(ch) - ord('A') + 1)
    return total


def _int_to_alpha(num):
    if num < 1:
        return ""

    chars = []
    while num > 0:
        num, rem = divmod(num - 1, 26)
        chars.append(chr(ord('A') + rem))
    chars.reverse()
    return ''.join(chars)


def build_counter_generator(start_text, increment_text):
    start_text = '' if start_text is None else str(start_text).strip()
    increment_text = '' if increment_text is None else str(increment_text).strip()

    if not start_text:
        return None, 'Start value is required.'

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

    return None, 'Unsupported start format. Use numeric, alphabetic, or prefix+numeric (e.g. SK-001).'


def _sheet_number_counter_signature():
    return (
        as_text(window.sheetStartBox.Text, "001"),
        as_text(window.sheetIncrementBox.Text, "1")
    )


def reset_sheet_number_counter_state():
    generator, error = build_counter_generator(window.sheetStartBox.Text, window.sheetIncrementBox.Text)
    sheet_number_counter_state["signature"] = _sheet_number_counter_signature()
    sheet_number_counter_state["generator"] = generator
    sheet_number_counter_state["index"] = 0
    sheet_number_counter_state["error"] = error
    return generator, error


def ensure_sheet_number_counter_state():
    signature = _sheet_number_counter_signature()
    if sheet_number_counter_state.get("signature") != signature:
        return reset_sheet_number_counter_state()
    return sheet_number_counter_state.get("generator"), sheet_number_counter_state.get("error")


def assign_next_sheet_number():
    generator, error = ensure_sheet_number_counter_state()
    if generator is None:
        return None, error

    try:
        value = generator(sheet_number_counter_state["index"])
    except Exception:
        return None, "Failed to generate the next sheet number."

    sheet_number_counter_state["index"] += 1
    return value, None


def get_row_sheet_number(row):
    if row is None:
        return ""

    override_no = (row.SheetNumberOverride or "").strip()
    if override_no:
        return override_no

    assigned_no = (row.SheetNumberAssigned or "").strip()
    if assigned_no:
        return assigned_no

    return (row.SheetNumberPreview or "").strip()


def set_row_sheet_number_preview(row):
    if row is None:
        return

    if not bool(row.IncludeOnSheet):
        row.SheetNumberPreview = ""
        return

    override_no = (row.SheetNumberOverride or "").strip()
    if override_no:
        row.SheetNumberPreview = override_no
        return

    assigned_no = (row.SheetNumberAssigned or "").strip()
    if assigned_no:
        row.SheetNumberPreview = assigned_no
        return

    assigned_no, error = assign_next_sheet_number()
    if assigned_no:
        row.SheetNumberAssigned = assigned_no
        row.SheetNumberPreview = assigned_no
    else:
        row.SheetNumberPreview = ""


def clear_row_sheet_number_assignment(row):
    if row is None:
        return

    row.SheetNumberAssigned = ""
    row.SheetNumberPreview = ""


def get_existing_sheet_number_set():
    numbers = set()
    try:
        sheets = DB.FilteredElementCollector(doc)\
            .OfClass(DB.ViewSheet)\
            .WhereElementIsNotElementType()\
            .ToElements()
    except:
        sheets = []

    for sheet in sheets:
        try:
            sheet_no = (sheet.SheetNumber or "").strip()
        except:
            sheet_no = ""

        if sheet_no:
            numbers.add(sheet_no.lower())

    return numbers


def get_revit_major_version():
    try:
        return int(as_text(doc.Application.VersionNumber, "0"))
    except:
        return 0


def _is_valid_element_id(element_id):
    try:
        if element_id is None:
            return False
        if element_id == DB.ElementId.InvalidElementId:
            return False
        return element_id.IntegerValue > 0
    except:
        return False


def _sheet_collection_display_from_id(collection_id):
    try:
        if not _is_valid_element_id(collection_id):
            return "<No Collection>"
        collection_obj = doc.GetElement(collection_id)
        if collection_obj is None:
            return "Collection Id {}".format(collection_id.IntegerValue)
        try:
            return as_text(getattr(collection_obj, 'Name', None), "") or "Collection Id {}".format(collection_id.IntegerValue)
        except:
            return "Collection Id {}".format(collection_id.IntegerValue)
    except:
        return "<Unknown Collection>"


def get_sheet_collection_identity(sheet):
    if sheet is None:
        return None, "<Unknown Collection>", False, "Sheet is missing."

    # Revit 2025+ API path.
    try:
        has_prop = hasattr(sheet, 'SheetCollectionId')
    except:
        has_prop = False

    if has_prop:
        try:
            collection_id = getattr(sheet, 'SheetCollectionId', DB.ElementId.InvalidElementId)
            if _is_valid_element_id(collection_id):
                return "id:{}".format(collection_id.IntegerValue), _sheet_collection_display_from_id(collection_id), True, None
            return "none", "<No Collection>", True, None
        except:
            return None, "<Unknown Collection>", False, "Could not read ViewSheet.SheetCollectionId."

    # Fallback path for API/runtime mismatches where the property is unavailable.
    try:
        source_param = sheet.LookupParameter("Sheet Collection")
    except:
        source_param = None

    if source_param is None:
        return None, "<Unknown Collection>", False, "ViewSheet.SheetCollectionId is unavailable and 'Sheet Collection' parameter lookup failed."

    try:
        if not source_param.HasValue:
            return "none", "<No Collection>", True, None
    except:
        return "none", "<No Collection>", True, None

    try:
        storage = source_param.StorageType
        if storage == DB.StorageType.ElementId:
            value_id = source_param.AsElementId()
            if _is_valid_element_id(value_id):
                return "id:{}".format(value_id.IntegerValue), _sheet_collection_display_from_id(value_id), True, None
            return "none", "<No Collection>", True, None
        if storage == DB.StorageType.String:
            value = as_text(source_param.AsString(), "").strip()
            if value:
                return "name:{}".format(value.lower()), value, True, None
            return "none", "<No Collection>", True, None
        if storage == DB.StorageType.Integer:
            value = source_param.AsInteger()
            return "int:{}".format(value), "Collection Value {}".format(value), True, None
        if storage == DB.StorageType.Double:
            value = source_param.AsDouble()
            return "dbl:{}".format(value), "Collection Value {}".format(value), True, None
    except:
        pass

    return None, "<Unknown Collection>", False, "Could not resolve sheet collection identity."


def get_existing_sheet_number_collection_pair_set():
    pairs = set()
    unresolved_count = 0

    try:
        sheets = DB.FilteredElementCollector(doc)\
            .OfClass(DB.ViewSheet)\
            .WhereElementIsNotElementType()\
            .ToElements()
    except:
        sheets = []

    for sheet in sheets:
        try:
            sheet_no = (sheet.SheetNumber or "").strip()
        except:
            sheet_no = ""

        if not sheet_no:
            continue

        collection_key, _collection_display, resolved, _reason = get_sheet_collection_identity(sheet)
        if not resolved or not collection_key:
            unresolved_count += 1
            continue

        pairs.add((sheet_no.lower(), collection_key))

    return pairs, unresolved_count


def _validate_sheet_numbers_global(include_rows, sheet_numbers):
    duplicate_numbers = []
    seen = set()

    for row in include_rows:
        sheet_no = sheet_numbers.get(row.RowId, "")
        key = sheet_no.lower()
        if key in seen:
            duplicate_numbers.append(sheet_no)
        seen.add(key)

    if duplicate_numbers:
        unique_duplicates = sorted(list(set(duplicate_numbers)), key=natural_sort_key)
        return "Duplicate sheet numbers in queue: {}".format(", ".join(unique_duplicates))

    existing_sheet_numbers = get_existing_sheet_number_set()
    clashes = []
    for row in include_rows:
        sheet_no = sheet_numbers.get(row.RowId, "")
        if sheet_no and sheet_no.lower() in existing_sheet_numbers:
            clashes.append(sheet_no)

    if clashes:
        unique_clashes = sorted(list(set(clashes)), key=natural_sort_key)
        return "Sheet number clash with existing sheets: {}".format(", ".join(unique_clashes))

    return None


def plan_key_to_view_family(plan_key):
    if plan_key == "floor":
        return DB.ViewFamily.FloorPlan
    if plan_key == "ceiling":
        return DB.ViewFamily.CeilingPlan
    if plan_key == "struct":
        return DB.ViewFamily.StructuralPlan
    return None


def get_vft(view_family):
    collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    for vft in collector:
        try:
            if vft.ViewFamily == view_family:
                return vft
        except:
            continue
    return None


def get_plan_specs(window_ref):
    specs = []
    if bool(window_ref.floorPlanBox.IsChecked):
        specs.append(PlanSpec(
            "floor",
            selected_text(window_ref.floorNameBox, "Floor") or "Floor",
            selected_text(window_ref.floorTemplateCombo, "<None>")
        ))
    if bool(window_ref.ceilingPlanBox.IsChecked):
        specs.append(PlanSpec(
            "ceiling",
            selected_text(window_ref.ceilingNameBox, "Ceiling") or "Ceiling",
            selected_text(window_ref.ceilingTemplateCombo, "<None>")
        ))
    if bool(window_ref.structPlanBox.IsChecked):
        specs.append(PlanSpec(
            "struct",
            selected_text(window_ref.structNameBox, "Structural") or "Structural",
            selected_text(window_ref.structTemplateCombo, "<None>")
        ))
    return specs


def _safe_titleblock_display(tb):
    fam = ""
    name = ""

    try:
        fam = as_text(getattr(tb, 'FamilyName', None), "")
    except:
        fam = ""

    # Type name access can be inconsistent across wrapped Revit element types.
    try:
        name = as_text(tb.Name, "")
    except:
        name = ""

    if not name:
        try:
            name = as_text(DB.Element.Name.GetValue(tb), "")
        except:
            pass

    if not name:
        try:
            p = tb.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
            if p:
                name = as_text(p.AsString(), "")
        except:
            pass

    if not fam:
        try:
            p = tb.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
            if p:
                fam = as_text(p.AsString(), "")
        except:
            pass

    if not fam:
        fam = "<Family>"
    if not name:
        name = "<Type>"

    return "{} : {}".format(fam, name)


def _safe_sheet_display(sheet):
    number = as_text(getattr(sheet, 'SheetNumber', None), "")
    name = as_text(getattr(sheet, 'Name', None), "")
    if not number and not name:
        return "<Unnamed Sheet>"
    if not number:
        return name
    if not name:
        return number
    return "{} - {}".format(number, name)


def _is_placeholder_sheet(sheet):
    try:
        return bool(getattr(sheet, 'IsPlaceholder', False))
    except:
        return False


def get_sheet_titleblock_type_id(sheet):
    if sheet is None:
        return DB.ElementId.InvalidElementId

    try:
        title_blocks = DB.FilteredElementCollector(doc, sheet.Id)\
            .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)\
            .WhereElementIsNotElementType()\
            .ToElements()
    except:
        title_blocks = []

    for tb in title_blocks:
        try:
            return tb.GetTypeId()
        except:
            continue

    return DB.ElementId.InvalidElementId


def get_template_plan_reference(template_sheet):
    if template_sheet is None:
        return None, None

    try:
        viewport_ids = list(template_sheet.GetAllViewports())
    except:
        viewport_ids = []

    for viewport_id in viewport_ids:
        viewport = doc.GetElement(viewport_id)
        if viewport is None:
            continue

        view_obj = doc.GetElement(viewport.ViewId)
        if view_obj is None:
            continue

        try:
            if isinstance(view_obj, DB.ViewPlan):
                return viewport, view_obj
        except:
            continue

    return None, None


def get_template_legend_viewports(template_sheet):
    results = []
    if template_sheet is None:
        return results

    try:
        viewport_ids = list(template_sheet.GetAllViewports())
    except:
        viewport_ids = []

    for viewport_id in viewport_ids:
        viewport = doc.GetElement(viewport_id)
        if viewport is None:
            continue

        view_obj = doc.GetElement(viewport.ViewId)
        if view_obj is None:
            continue

        try:
            if view_obj.ViewType == DB.ViewType.Legend:
                results.append((viewport, view_obj))
        except:
            continue

    return results


def get_template_schedule_instances(template_sheet):
    schedules = []
    if template_sheet is None:
        return schedules

    try:
        all_instances = DB.FilteredElementCollector(doc, template_sheet.Id)\
            .OfClass(DB.ScheduleSheetInstance)\
            .ToElements()
    except:
        all_instances = []

    for inst in all_instances:
        try:
            if inst.IsTitleblockRevisionSchedule:
                continue
        except:
            pass

        schedules.append(inst)

    return schedules


def copy_template_sheet_parameters(template_sheet, new_sheet, warnings_list=None):
    if template_sheet is None or new_sheet is None:
        return

    def _warn(msg):
        if warnings_list is not None:
            warnings_list.append(msg)

    # Revit 2025+ exposes Sheet Collection through ViewSheet.SheetCollectionId.
    has_sheet_collection_property = False
    try:
        source_sheet_collection_id = getattr(template_sheet, 'SheetCollectionId', DB.ElementId.InvalidElementId)
        has_sheet_collection_property = hasattr(template_sheet, 'SheetCollectionId')
    except:
        source_sheet_collection_id = DB.ElementId.InvalidElementId
        has_sheet_collection_property = False

    copied_sheet_collection = False
    source_has_sheet_collection_value = False

    try:
        if source_sheet_collection_id and source_sheet_collection_id != DB.ElementId.InvalidElementId:
            source_has_sheet_collection_value = True
    except:
        source_has_sheet_collection_value = False

    try:
        if source_sheet_collection_id and source_sheet_collection_id != DB.ElementId.InvalidElementId:
            new_sheet.SheetCollectionId = source_sheet_collection_id
            try:
                current_id = getattr(new_sheet, 'SheetCollectionId', DB.ElementId.InvalidElementId)
                copied_sheet_collection = (current_id == source_sheet_collection_id)
            except:
                copied_sheet_collection = False
    except:
        copied_sheet_collection = False

    # Fallback: try parameter-by-name if property assignment is unavailable or did not persist.
    if not copied_sheet_collection:
        try:
            source_param = template_sheet.LookupParameter("Sheet Collection")
            target_param = new_sheet.LookupParameter("Sheet Collection")
        except:
            source_param = None
            target_param = None

        if source_param is not None and target_param is not None:
            try:
                if (not target_param.IsReadOnly) and source_param.HasValue:
                    source_has_sheet_collection_value = True
                    storage = source_param.StorageType
                    if storage == DB.StorageType.String:
                        target_param.Set(source_param.AsString())
                    elif storage == DB.StorageType.Integer:
                        target_param.Set(source_param.AsInteger())
                    elif storage == DB.StorageType.Double:
                        target_param.Set(source_param.AsDouble())
                    elif storage == DB.StorageType.ElementId:
                        target_param.Set(source_param.AsElementId())

                    try:
                        if storage == DB.StorageType.ElementId:
                            copied_sheet_collection = (target_param.AsElementId() == source_param.AsElementId())
                        elif storage == DB.StorageType.Integer:
                            copied_sheet_collection = (target_param.AsInteger() == source_param.AsInteger())
                        elif storage == DB.StorageType.Double:
                            copied_sheet_collection = (target_param.AsDouble() == source_param.AsDouble())
                        else:
                            copied_sheet_collection = (as_text(target_param.AsString(), "") == as_text(source_param.AsString(), ""))
                    except:
                        copied_sheet_collection = False
            except:
                copied_sheet_collection = False

    # If neither API property nor parameter lookup can resolve a source value, surface it.
    if not source_has_sheet_collection_value:
        try:
            revit_major = int(as_text(doc.Application.VersionNumber, "0"))
        except:
            revit_major = 0

        if revit_major >= 2025:
            if not has_sheet_collection_property:
                _warn("Sheet Collection could not be copied for template sheet '{}': this Revit API build does not expose ViewSheet.SheetCollectionId. Consider Revit 2025.3+ API/runtime alignment.".format(as_text(getattr(template_sheet, 'SheetNumber', None), "?")))
            else:
                _warn("Sheet Collection source value was not resolvable for template sheet '{}'. The sheet may have no collection assigned, or localized parameter name lookup ('Sheet Collection') did not match.".format(as_text(getattr(template_sheet, 'SheetNumber', None), "?")))

    if source_has_sheet_collection_value and not copied_sheet_collection:
        _warn("Could not copy Sheet Collection from template sheet '{}' to new sheet '{}'. Check whether the target sheet allows editing SheetCollectionId in this project state.".format(as_text(getattr(template_sheet, 'SheetNumber', None), "?"), as_text(getattr(new_sheet, 'SheetNumber', None), "?")))

    excluded_names = set(["sheet number", "sheet name", "revisions on sheet"])
    excluded_bips = set([
        int(DB.BuiltInParameter.SHEET_NUMBER),
        int(DB.BuiltInParameter.SHEET_NAME),
        int(DB.BuiltInParameter.SHEET_CURRENT_REVISION)
    ])

    try:
        source_params = list(template_sheet.Parameters)
    except:
        source_params = []

    for source_param in source_params:
        if source_param is None:
            continue

        try:
            source_id_int = source_param.Id.IntegerValue
        except:
            source_id_int = None

        if source_id_int in excluded_bips:
            continue

        try:
            param_name = as_text(source_param.Definition.Name, "").strip()
        except:
            param_name = ""

        if not param_name:
            continue

        if param_name.lower() in excluded_names:
            continue

        try:
            if not source_param.HasValue:
                continue
        except:
            pass

        try:
            target_param = new_sheet.LookupParameter(param_name)
        except:
            target_param = None

        if target_param is None:
            continue

        try:
            if target_param.IsReadOnly:
                continue
        except:
            continue

        try:
            storage = source_param.StorageType
            if storage == DB.StorageType.String:
                target_param.Set(source_param.AsString())
            elif storage == DB.StorageType.Integer:
                target_param.Set(source_param.AsInteger())
            elif storage == DB.StorageType.Double:
                target_param.Set(source_param.AsDouble())
            elif storage == DB.StorageType.ElementId:
                target_param.Set(source_param.AsElementId())
        except:
            continue


def _ensure_crop_enabled(view_obj):
    if view_obj is None:
        return

    try:
        crop_param = view_obj.get_Parameter(DB.BuiltInParameter.VIEWER_CROP_REGION)
        if crop_param and not crop_param.AsInteger():
            crop_param.Set(1)
    except:
        pass


def _hide_view_elements_temp(view_obj):
    if view_obj is None:
        return

    try:
        element_ids = DB.FilteredElementCollector(doc, view_obj.Id).WhereElementIsNotElementType().ToElementIds()
        if element_ids and element_ids.Count > 0:
            view_obj.HideElementsTemporary(element_ids)
    except:
        pass


def _clear_view_temp_hide(view_obj):
    if view_obj is None:
        return

    try:
        view_obj.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)
    except:
        pass


def align_viewport_to_template_center(template_view, template_viewport, target_view, target_viewport):
    if template_view is None or template_viewport is None or target_view is None or target_viewport is None:
        return False

    try:
        _ensure_crop_enabled(template_view)
        _ensure_crop_enabled(target_view)
        _hide_view_elements_temp(template_view)
        _hide_view_elements_temp(target_view)
        target_viewport.SetBoxCenter(template_viewport.GetBoxCenter())
        return True
    except:
        return False
    finally:
        _clear_view_temp_hide(target_view)
        _clear_view_temp_hide(template_view)


def apply_template_viewport_settings(template_viewport, target_viewport):
    if template_viewport is None or target_viewport is None:
        return

    # Match viewport type first; this carries most title/graphics settings.
    try:
        template_type_id = template_viewport.GetTypeId()
        if template_type_id and template_type_id != target_viewport.GetTypeId():
            target_viewport.ChangeTypeId(template_type_id)
    except:
        pass

    # Best-effort copy of writable instance parameters that are not identity fields.
    excluded_ids = set([
        int(DB.BuiltInParameter.VIEWPORT_SHEET_NUMBER),
        int(DB.BuiltInParameter.VIEWPORT_SHEET_NAME),
        int(DB.BuiltInParameter.VIEWPORT_VIEW_NAME),
        int(DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
    ])

    try:
        template_params = list(template_viewport.Parameters)
    except:
        template_params = []

    for source_param in template_params:
        if source_param is None:
            continue

        try:
            source_id = source_param.Id
            source_int = source_id.IntegerValue
        except:
            continue

        if source_int in excluded_ids:
            continue

        try:
            if not source_param.HasValue:
                continue
        except:
            pass

        try:
            target_param = target_viewport.get_Parameter(source_id)
        except:
            target_param = None

        if target_param is None:
            continue

        try:
            if target_param.IsReadOnly:
                continue
        except:
            continue

        try:
            storage = source_param.StorageType
            if storage == DB.StorageType.String:
                target_param.Set(source_param.AsString())
            elif storage == DB.StorageType.Integer:
                target_param.Set(source_param.AsInteger())
            elif storage == DB.StorageType.Double:
                target_param.Set(source_param.AsDouble())
            elif storage == DB.StorageType.ElementId:
                target_param.Set(source_param.AsElementId())
        except:
            continue


def remove_template_inherited_revisions(sheet, template_revision_ints):
    if sheet is None:
        return

    if not template_revision_ints:
        return

    try:
        current_ids = sheet.GetAdditionalRevisionIds()
    except:
        current_ids = None

    if not current_ids:
        return

    keep_ids = List[DB.ElementId]()
    for rev_id in current_ids:
        try:
            if rev_id.IntegerValue not in template_revision_ints:
                keep_ids.Add(rev_id)
        except:
            keep_ids.Add(rev_id)

    try:
        sheet.SetAdditionalRevisionIds(keep_ids)
    except:
        pass


xaml_path = __file__.replace("script.py", "CreateViews.xaml")
print("CreateViews: startup begin")
try:
    window = forms.WPFWindow(xaml_path)
    print("CreateViews: XAML loaded")
except Exception as ex:
    detail = _exception_details(ex)
    xaml_preview = _xaml_debug_preview(xaml_path)
    show_error(
        "Failed to load CreateViews.xaml",
        "XAML Path: {}\n\n{}\n\nXAML Preview:\n{}".format(xaml_path, detail, xaml_preview),
        "Create Views - XAML Load Failure"
    )
    forms.alert("Create Views cannot start due to a UI load error.", exitscript=True)


try:
    print("CreateViews: apply defaults")
    _load_token_delimiters_from_config()
    persisted_pattern = as_text(cfg_get(CFG_NAME_PATTERN_KEY, DEFAULT_NAME_PATTERN), DEFAULT_NAME_PATTERN).strip() or DEFAULT_NAME_PATTERN
    persisted_sheet_name_pattern = as_text(cfg_get(CFG_SHEET_NAME_PATTERN_KEY, DEFAULT_SHEET_NAME_PATTERN), DEFAULT_SHEET_NAME_PATTERN).strip() or DEFAULT_SHEET_NAME_PATTERN
    if not read_history(CFG_NAME_PATTERN_HISTORY_KEY):
        write_history(CFG_NAME_PATTERN_HISTORY_KEY, [persisted_pattern])
    if not read_history(CFG_SHEET_NAME_PATTERN_HISTORY_KEY):
        write_history(CFG_SHEET_NAME_PATTERN_HISTORY_KEY, [persisted_sheet_name_pattern])

    has_pattern_current, _pattern_current = cfg_try_get(CFG_NAME_PATTERN_CURRENT_KEY)
    if not has_pattern_current:
        cfg_set(CFG_NAME_PATTERN_CURRENT_KEY, persisted_pattern)

    has_sheet_pattern_current, _sheet_pattern_current = cfg_try_get(CFG_SHEET_NAME_PATTERN_CURRENT_KEY)
    if not has_sheet_pattern_current:
        cfg_set(CFG_SHEET_NAME_PATTERN_CURRENT_KEY, persisted_sheet_name_pattern)

    for field_name, history_key, default_value, current_key in TEXT_HISTORY_FIELDS:
        try:
            setup_history_combo(getattr(window, field_name), history_key, default_value, current_key)
        except:
            pass

    window.sheetStartBox.Text = as_text(cfg_get(CFG_SHEET_START_KEY, "001"), "001")
    window.sheetIncrementBox.Text = as_text(cfg_get(CFG_SHEET_INCREMENT_KEY, "1"), "1")
    window.dependentCountBox.Text = as_text(cfg_get(CFG_DEPENDENT_COUNT_KEY, "1"), "1")

    print("CreateViews: load phases")
    phase_collector = DB.FilteredElementCollector(doc).OfClass(DB.Phase)
    phases = list(phase_collector)
    if not phases:
        forms.alert("No phases found in this document.", exitscript=True)

    phases = sorted(
        phases,
        key=lambda p: p.get_Parameter(DB.BuiltInParameter.PHASE_SEQUENCE_NUMBER).AsInteger()
    )

    phase_map = {}
    for p in phases:
        label = p.Name
        phase_map[label] = p
        window.phaseBox.Items.Add(label)

    default_phase_index = len(phases) - 1
    for idx, phase_obj in enumerate(phases):
        try:
            if (phase_obj.Name or "").strip().lower() == "new construction":
                default_phase_index = idx
                break
        except:
            continue

    window.phaseBox.SelectedIndex = default_phase_index

    print("CreateViews: load scope boxes")
    scope_boxes = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)\
        .WhereElementIsNotElementType()\
        .ToElements()
    scope_boxes = sorted(scope_boxes, key=lambda sb: natural_sort_key(sb.Name))

    scope_box_map = {}
    scope_name_items = []

    scope_box_map["<None>"] = None
    scope_name_items.append("<None>")
    window.scopeBoxCombo.Items.Add("<None>")

    for sb in scope_boxes:
        name = sb.Name
        scope_box_map[name] = sb
        scope_name_items.append(name)
        window.scopeBoxCombo.Items.Add(name)
    window.scopeBoxCombo.SelectedIndex = 0

    print("CreateViews: load templates")
    all_templates = DB.FilteredElementCollector(doc)\
        .OfClass(DB.View)\
        .ToElements()
    all_templates = [t for t in all_templates if t.IsTemplate]

    floor_templates = [t for t in all_templates if t.ViewType == DB.ViewType.FloorPlan]
    ceiling_templates = [t for t in all_templates if t.ViewType == DB.ViewType.CeilingPlan]
    struct_templates = list(floor_templates)

    def populate_template_combo(combo, items):
        combo.Items.Clear()
        combo.Items.Add("<None>")
        sorted_items = sorted(items, key=lambda t: natural_sort_key(as_text(getattr(t, 'Name', ''), '')))
        for t in sorted_items:
            combo.Items.Add(as_text(getattr(t, 'Name', ''), ''))
        combo.SelectedIndex = 0

    populate_template_combo(window.floorTemplateCombo, floor_templates)
    populate_template_combo(window.ceilingTemplateCombo, ceiling_templates)
    populate_template_combo(window.structTemplateCombo, struct_templates)

    template_lists = {
        "floor": floor_templates,
        "ceiling": ceiling_templates,
        "struct": floor_templates
    }

    print("CreateViews: load template sheets")
    template_sheets = DB.FilteredElementCollector(doc)\
        .OfClass(DB.ViewSheet)\
        .WhereElementIsNotElementType()\
        .ToElements()
    template_sheets = [s for s in template_sheets if not _is_placeholder_sheet(s)]
    template_sheets = sorted(template_sheets, key=lambda s: natural_sort_key(_safe_sheet_display(s)))

    window.templateSheetMap = {}
    window.templateSheetCombo.Items.Add("<None>")
    window.templateSheetMap["<None>"] = None

    for sheet in template_sheets:
        display = _safe_sheet_display(sheet)
        unique_display = display
        suffix = 2
        while unique_display in window.templateSheetMap:
            unique_display = "{} ({})".format(display, suffix)
            suffix += 1

        window.templateSheetCombo.Items.Add(unique_display)
        window.templateSheetMap[unique_display] = sheet

    saved_template_sheet = as_text(cfg_get(CFG_TEMPLATE_SHEET_KEY, "<None>"), "<None>")
    if saved_template_sheet in window.templateSheetMap:
        window.templateSheetCombo.SelectedItem = saved_template_sheet
    else:
        window.templateSheetCombo.SelectedIndex = 0

    window.copyDetailingBox.IsChecked = as_bool(cfg_get(CFG_COPY_DETAILING_KEY, True), True)
    window.copyLegendsBox.IsChecked = as_bool(cfg_get(CFG_COPY_LEGENDS_KEY, True), True)
    window.copySchedulesBox.IsChecked = as_bool(cfg_get(CFG_COPY_SCHEDULES_KEY, True), True)
    window.removeRevisionsBox.IsChecked = as_bool(cfg_get(CFG_REMOVE_REVISIONS_KEY, True), True)

    print("CreateViews: setup queue grid")
    queue_rows = ObservableCollection[object]()
    window.queueGrid.ItemsSource = queue_rows
    scope_column = None
    try:
        scope_column = getattr(window, 'gridScopeColumn', None)
    except:
        scope_column = None

    if scope_column is None:
        try:
            for col in window.queueGrid.Columns:
                try:
                    if hasattr(col, 'Header') and str(col.Header) == 'Scope Box':
                        scope_column = col
                        break
                except:
                    continue
        except:
            scope_column = None

    if scope_column is not None:
        try:
            scope_column.ItemsSource = scope_name_items
        except Exception as ex:
            show_error(
                "Failed to bind Scope Box dropdown values",
                _exception_details(ex),
                "Create Views - Grid Setup"
            )

    print("CreateViews: queue setup complete")
except Exception as ex:
    show_error(
        "Create Views initialization failed",
        _exception_details(ex),
        "Create Views - Initialization Failure"
    )
    forms.alert("Create Views failed during initialization. See traceback dialog for details.", exitscript=True)

row_id_counter = [0]
is_refreshing_preview = [False]
suppress_checkbox_events = [False]
preview_refresh_pending = [False]
batch_preview_update_active = [False]

all_levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements())
level_states = {}
level_checkboxes = []

selection = revit.get_selection()
for elid in selection.element_ids:
    el = doc.GetElement(elid)
    if isinstance(el, DB.Level):
        level_states[el.Id.IntegerValue] = True


def next_row_id():
    row_id_counter[0] += 1
    return row_id_counter[0]


def get_selected_phase():
    phase_name = selected_text(window.phaseBox)
    phase_obj = phase_map.get(phase_name)
    if phase_obj is None:
        phase_obj = phases[-1]
    return phase_obj


def get_selected_levels():
    result = []
    for lvl in all_levels:
        if level_states.get(lvl.Id.IntegerValue, False):
            result.append(lvl)
    return result


def sync_level_states_from_visible():
    for cb in level_checkboxes:
        level_obj = cb.Tag
        level_states[level_obj.Id.IntegerValue] = bool(cb.IsChecked)


def get_sorted_filtered_levels():
    levels = list(all_levels)
    sort_option = selected_text(window.sortCombo, "Height (Level)")
    if sort_option == "Name":
        levels = sorted(levels, key=lambda lvl: natural_sort_key(lvl.Name))
    else:
        levels = sorted(levels, key=lambda lvl: lvl.Elevation)

    filter_text = (window.filterBox.Text or "").strip().lower()
    if filter_text:
        levels = [lvl for lvl in levels if filter_text in (lvl.Name or "").lower()]
    return levels


def rebuild_level_checkboxes():
    sync_level_states_from_visible()
    del level_checkboxes[:]
    window.levelsPanel.Children.Clear()

    for lvl in get_sorted_filtered_levels():
        cb = CheckBox()
        # Escape underscore so WPF does not treat it as an access-key marker.
        cb.Content = (lvl.Name or "").replace("_", "__")
        cb.Tag = lvl
        cb.Margin = System.Windows.Thickness(0, 0, 0, 4)

        if level_states.get(lvl.Id.IntegerValue, False):
            cb.IsChecked = True

        window.levelsPanel.Children.Add(cb)
        level_checkboxes.append(cb)


def resolve_template(plan_key, template_name):
    if not template_name or template_name == "<None>":
        return None
    for temp in template_lists.get(plan_key, []):
        if temp.Name == template_name:
            return temp
    return None


def get_row_by_id(row_id):
    if row_id is None:
        return None
    for row in queue_rows:
        if row.RowId == row_id:
            return row
    return None


def get_parent_display_name(row):
    if row is None:
        return ""

    parent_row = get_row_by_id(getattr(row, 'ParentRowId', None))
    if parent_row is not None:
        return as_text(getattr(parent_row, 'ViewName', None), "")

    return as_text(getattr(row, 'ParentName', None), "")


def queue_name_exists(name, exclude_row_id=None):
    target = (name or "").strip().lower()
    if not target:
        return False
    for row in queue_rows:
        if exclude_row_id is not None and row.RowId == exclude_row_id:
            continue
        if (row.ViewName or "").strip().lower() == target:
            return True
    return False


def unique_queue_name(base_name, exclude_row_id=None):
    base = (base_name or "").strip()
    if not base:
        base = "Unnamed"

    if not queue_name_exists(base, exclude_row_id):
        return base

    idx = 2
    while True:
        candidate = "{} ({})".format(base, idx)
        if not queue_name_exists(candidate, exclude_row_id):
            return candidate
        idx += 1


def unique_name_in_existing_set(base_name, existing_name_set):
    base = (base_name or "").strip() or "Unnamed"
    candidate = base
    idx = 2
    while candidate.lower() in existing_name_set:
        candidate = "{} ({})".format(base, idx)
        idx += 1
    return candidate


def resolve_name_clash(view_name, row_type, clash_policy):
    if clash_policy.get("repeat_all") and clash_policy.get("action") in ("skip", "rename"):
        return clash_policy.get("action")

    dlg = TaskDialog("Create Views - Name Clash")
    dlg.MainInstruction = "A {} view name already exists.".format(row_type)
    dlg.MainContent = "Existing name: {}\nChoose how to proceed.".format(view_name)
    dlg.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, "Skip this view")
    dlg.AddCommandLink(TaskDialogCommandLinkId.CommandLink2, "Rename this view")
    dlg.VerificationText = "Repeat for all remaining name clashes in this run"

    result = dlg.Show()
    repeat_all = dlg.WasVerificationChecked()

    if result == TaskDialogCommandLinkId.CommandLink2:
        action = "rename"
    else:
        action = "skip"

    if repeat_all:
        clash_policy["action"] = action
        clash_policy["repeat_all"] = True

    return action


def build_row_name(level_obj, plan_label, scope_name):
    phase_obj = get_selected_phase()
    prefix = selected_text(window.prefixBox, "")
    suffix = selected_text(window.suffixBox, "")
    name_pattern = (window.namePatternBox.Text or "").strip() or DEFAULT_NAME_PATTERN
    raw_phase = selected_text(window.phaseAbbrevBox, "")
    phase_abbrev = raw_phase or ""

    token_values = {
        "phase": phase_obj.Name,
        "phase_abbrev": phase_abbrev,
        "plan_type": plan_label,
        "scopebox": scope_name if scope_name and scope_name != "<None>" else "",
        "level": level_obj.Name if level_obj else ""
    }
    generated = build_view_name(name_pattern, token_values, prefix, suffix).strip()
    return generated


def build_sheet_name_for_row(row):
    if row is None:
        return ""

    pattern = (window.sheetNamePatternBox.Text or "").strip() or DEFAULT_SHEET_NAME_PATTERN
    phase_obj = get_selected_phase()
    raw_phase = selected_text(window.phaseAbbrevBox, "")
    phase_abbrev = raw_phase or ""
    scope_name = row.ScopeName if row.ScopeName and row.ScopeName != "<None>" else ""

    token_values = {
        "phase": phase_obj.Name if phase_obj else "",
        "phase_abbrev": phase_abbrev,
        "plan_type": row.PlanType or "",
        "scopebox": scope_name,
        "level": row.LevelName or "",
        "view_name": row.ViewName or "",
        "sheet_number": get_row_sheet_number(row)
    }

    return safe_name(render_name_pattern(pattern, token_values, token_delimiter_state.get("value", DEFAULT_TOKEN_DELIMITERS))).strip()


def apply_sheet_name_pattern_to_queue():
    for row in get_display_order_rows():
        generated = build_sheet_name_for_row(row)
        if not generated:
            continue

        current_name = (row.SheetNameOverride or "").strip()
        last_applied = (row.SheetNamePatternApplied or "").strip()

        if current_name and current_name != last_applied:
            continue

        row.SheetNameOverride = generated
        row.SheetNamePatternApplied = generated


def rebuild_queue_preview():
    if is_refreshing_preview[0]:
        return

    is_refreshing_preview[0] = True
    suppress_checkbox_events[0] = True
    try:
        ensure_sheet_number_counter_state()

        for row in queue_rows:
            row.SheetNumberPreview = ""

        for row in get_display_order_rows():
            set_row_sheet_number_preview(row)

        apply_sheet_name_pattern_to_queue()
    finally:
        suppress_checkbox_events[0] = False
        is_refreshing_preview[0] = False


def schedule_queue_preview_refresh():
    if batch_preview_update_active[0]:
        return

    if preview_refresh_pending[0]:
        return

    preview_refresh_pending[0] = True

    def _run_refresh():
        preview_refresh_pending[0] = False
        rebuild_queue_preview()

    try:
        window.Dispatcher.BeginInvoke(System.Action(_run_refresh))
    except:
        _run_refresh()


def get_included_rows_in_order():
    return [r for r in get_display_order_rows() if bool(r.IncludeOnSheet)]


def build_sheet_number_map(include_rows, warnings_list=None):
    sheet_numbers = {}

    for row in include_rows:
        sheet_no = get_row_sheet_number(row)
        if not sheet_no:
            return None, "Missing sheet number for included row: {}".format(row.ViewName)
        sheet_numbers[row.RowId] = sheet_no

    revit_major = get_revit_major_version()
    if revit_major < 2025:
        sheet_number_clash_mode_state["detail"] = "Sheet number clash mode: Global (Revit < 2025)."
        error = _validate_sheet_numbers_global(include_rows, sheet_numbers)
        if error:
            return None, error
        return sheet_numbers, None

    row_collection_map = {}
    unresolved_rows = []

    for row in include_rows:
        template_sheet_name = (row.SheetTemplateName or "").strip()
        template_sheet = None
        try:
            template_sheet = window.templateSheetMap.get(template_sheet_name)
        except:
            template_sheet = None

        collection_key, collection_display, resolved, reason = get_sheet_collection_identity(template_sheet)
        if not resolved or not collection_key:
            unresolved_rows.append((row, reason or "Unknown collection resolution error."))
            continue

        row_collection_map[row.RowId] = (collection_key, collection_display)

    existing_pairs, unresolved_existing_count = get_existing_sheet_number_collection_pair_set()

    if unresolved_rows or unresolved_existing_count > 0:
        sheet_number_clash_mode_state["detail"] = "Sheet number clash mode: Global fallback (Revit 2025+, unresolved Sheet Collection identity)."
        if warnings_list is not None:
            if unresolved_rows:
                warnings_list.append(
                    "Sheet Collection identity could not be resolved for {} queued row(s); using global sheet-number clash checks."
                    .format(len(unresolved_rows))
                )
            if unresolved_existing_count > 0:
                warnings_list.append(
                    "Sheet Collection identity could not be resolved for {} existing sheet(s); using global sheet-number clash checks."
                    .format(unresolved_existing_count)
                )

        error = _validate_sheet_numbers_global(include_rows, sheet_numbers)
        if error:
            return None, error
        return sheet_numbers, None

    sheet_number_clash_mode_state["detail"] = "Sheet number clash mode: Collection-aware (Revit 2025+, by Sheet Collection)."

    duplicate_pairs = []
    seen_pairs = set()
    for row in include_rows:
        sheet_no = sheet_numbers.get(row.RowId, "")
        collection_key, collection_display = row_collection_map.get(row.RowId, ("none", "<No Collection>"))
        pair = (sheet_no.lower(), collection_key)
        if pair in seen_pairs:
            duplicate_pairs.append("{} [{}]".format(sheet_no, collection_display))
        seen_pairs.add(pair)

    if duplicate_pairs:
        unique_duplicates = sorted(list(set(duplicate_pairs)), key=natural_sort_key)
        return None, "Duplicate sheet numbers in queue within the same sheet collection: {}".format(", ".join(unique_duplicates))

    collection_clashes = []
    for row in include_rows:
        sheet_no = sheet_numbers.get(row.RowId, "")
        collection_key, collection_display = row_collection_map.get(row.RowId, ("none", "<No Collection>"))
        if (sheet_no.lower(), collection_key) in existing_pairs:
            collection_clashes.append("{} [{}]".format(sheet_no, collection_display))

    if collection_clashes:
        unique_clashes = sorted(list(set(collection_clashes)), key=natural_sort_key)
        return None, "Sheet number clash with existing sheets in the same sheet collection: {}".format(", ".join(unique_clashes))

    return sheet_numbers, None


def get_display_order_rows():
    rows = []
    try:
        for item in window.queueGrid.Items:
            if item is None:
                continue
            if getattr(item, 'RowId', None) is None:
                continue
            rows.append(item)
    except:
        rows = []

    if rows:
        return rows
    return list(queue_rows)


def set_queue_rows_order(ordered_rows):
    queue_rows.Clear()
    for row in ordered_rows:
        queue_rows.Add(row)


def commit_queue_grid_edits():
    try:
        window.queueGrid.CommitEdit()
    except:
        pass
    try:
        window.queueGrid.CommitEdit()
    except:
        pass


def reselect_rows_by_id(selected_ids):
    try:
        window.queueGrid.SelectedItems.Clear()
    except:
        pass

    for row in queue_rows:
        try:
            if row.RowId in selected_ids:
                window.queueGrid.SelectedItems.Add(row)
        except:
            pass


def move_selected_rows(direction):
    commit_queue_grid_edits()
    selected = get_selected_queue_rows()
    if not selected:
        forms.alert("Select one or more rows to move.")
        return

    selected_ids = set([r.RowId for r in selected])
    rows = list(queue_rows)
    count = len(rows)
    changed = False

    if direction == "up":
        for i in range(1, count):
            if rows[i].RowId in selected_ids and rows[i - 1].RowId not in selected_ids:
                rows[i - 1], rows[i] = rows[i], rows[i - 1]
                changed = True
    elif direction == "down":
        for i in range(count - 2, -1, -1):
            if rows[i].RowId in selected_ids and rows[i + 1].RowId not in selected_ids:
                rows[i], rows[i + 1] = rows[i + 1], rows[i]
                changed = True

    if not changed:
        return

    set_queue_rows_order(rows)
    reselect_rows_by_id(selected_ids)
    schedule_queue_preview_refresh()


def move_up(sender=None, args=None):
    move_selected_rows("up")


def move_down(sender=None, args=None):
    move_selected_rows("down")


def _dependent_name_from_pattern(base_name, row_id_to_exclude=None):
    clean_base = (base_name or "").strip()
    if not clean_base:
        clean_base = "Dependent"

    if not queue_name_exists(clean_base, row_id_to_exclude):
        return clean_base

    suffix = 1
    while True:
        candidate = "{}-D{:02d}".format(clean_base, suffix)
        if not queue_name_exists(candidate, row_id_to_exclude):
            return candidate
        suffix += 1


def add_rows(sender=None, args=None):
    commit_queue_grid_edits()
    sync_level_states_from_visible()
    selected_levels = get_selected_levels()
    if not selected_levels:
        forms.alert("Select at least one level on the right before adding rows.")
        return

    specs = get_plan_specs(window)
    if not specs:
        forms.alert("Select at least one plan type before adding rows.")
        return

    default_scope_name = selected_text(window.scopeBoxCombo, "<None>")
    if default_scope_name not in scope_box_map:
        default_scope_name = "<None>"

    added_count = 0
    batch_preview_update_active[0] = True
    try:
        for lvl in selected_levels:
            for spec in specs:
                proposed_name = build_row_name(lvl, spec.Label, default_scope_name)
                proposed_name = unique_queue_name(proposed_name)

                row = QueueRow(
                    next_row_id(),
                    lvl,
                    spec.Key,
                    spec.Label,
                    spec.TemplateName,
                    default_scope_name,
                    proposed_name,
                    "Primary",
                    None,
                    ""
                )
                queue_rows.Add(row)
                added_count += 1
    finally:
        batch_preview_update_active[0] = False

    schedule_queue_preview_refresh()

    if added_count == 0:
        forms.alert("No new rows were added. Matching primary rows already exist in the queue.")


def remove_selected_rows(sender=None, args=None):
    commit_queue_grid_edits()
    selected = get_selected_queue_rows()
    if not selected:
        forms.alert("Select one or more queue rows to remove.")
        return

    remove_ids = set([row.RowId for row in selected])
    for row in list(queue_rows):
        if row.ParentRowId in remove_ids:
            remove_ids.add(row.RowId)

    for row in list(queue_rows):
        if row.RowId in remove_ids:
            queue_rows.Remove(row)

    schedule_queue_preview_refresh()


def duplicate_as_dependent(sender=None, args=None):
    commit_queue_grid_edits()
    selected = get_selected_queue_rows()
    source_rows = [row for row in selected if row.RowType == "Primary"]
    if not source_rows:
        forms.alert("Select at least one Primary row to duplicate as dependent.")
        return

    try:
        count = int((window.dependentCountBox.Text or "1").strip())
    except:
        forms.alert("Dependents / source must be an integer.")
        return

    if count < 1:
        forms.alert("Dependents / source must be at least 1.")
        return

    default_scope_name = selected_text(window.scopeBoxCombo, "<None>")
    if default_scope_name not in scope_box_map:
        default_scope_name = "<None>"

    added = 0
    batch_preview_update_active[0] = True
    try:
        for source in source_rows:
            for idx in range(1, count + 1):
                pattern_base = build_row_name(source.Level, source.PlanType, default_scope_name)
                dep_name = _dependent_name_from_pattern(pattern_base)
                row = QueueRow(
                    next_row_id(),
                    source.Level,
                    source.PlanKey,
                    source.PlanType,
                    source.TemplateName,
                    default_scope_name,
                    dep_name,
                    "Dependent",
                    source.RowId,
                    source.ViewName,
                    parent_row_key=source.RowKey
                )
                row.IncludeOnSheet = bool(source.IncludeOnSheet)
                row.SheetTemplateName = (source.SheetTemplateName or "").strip()
                queue_rows.Add(row)
                added += 1
    finally:
        batch_preview_update_active[0] = False

    schedule_queue_preview_refresh()

    if added == 0:
        forms.alert("No dependent rows were added.")


def include_all(sender=None, args=None):
    commit_queue_grid_edits()
    current_template_sheet = selected_text(window.templateSheetCombo, "<None>")
    batch_preview_update_active[0] = True
    try:
        for row in queue_rows:
            row.IncludeOnSheet = True
            row.SheetTemplateName = current_template_sheet
    finally:
        batch_preview_update_active[0] = False

    schedule_queue_preview_refresh()


def include_none(sender=None, args=None):
    commit_queue_grid_edits()
    batch_preview_update_active[0] = True
    try:
        for row in queue_rows:
            row.IncludeOnSheet = False
            clear_row_sheet_number_assignment(row)
            row.SheetTemplateName = ""
    finally:
        batch_preview_update_active[0] = False

    reset_sheet_number_counter_state()
    schedule_queue_preview_refresh()


def _parse_bool(text):
    return as_bool(text, False)


def _normalize_plan_key(raw_key, raw_label):
    key = (raw_key or "").strip().lower()
    label = (raw_label or "").strip().lower()

    if key in ("floor", "ceiling", "struct"):
        return key

    if "ceiling" in label:
        return "ceiling"
    if "struct" in label or "engineering" in label:
        return "struct"
    return "floor"


def _default_plan_label(plan_key):
    if plan_key == "ceiling":
        return selected_text(window.ceilingNameBox, "Ceiling") or "Ceiling"
    if plan_key == "struct":
        return selected_text(window.structNameBox, "Structural") or "Structural"
    return selected_text(window.floorNameBox, "Floor") or "Floor"


def export_queue_csv(sender=None, args=None):
    commit_queue_grid_edits()
    path = forms.save_file(
        file_ext='csv',
        default_name='create_views_queue.csv',
        title='Export View Queue CSV'
    )
    if not path:
        return

    rows = get_display_order_rows()
    if not rows:
        forms.alert("Queue is empty. Nothing to export.")
        return

    header = [
        "Row Key", "Parent Row Key", "RowType", "Level", "PlanKey", "PlanType", "Template", "Scope Box",
        "View Name", "Include On Sheet", "Sheet No. Override", "Sheet Name Override", "Sheet Template", "Parent View"
    ]

    try:
        with codecs.open(path, 'w', encoding='utf-8-sig') as fp:
            writer = csv.writer(fp)
            writer.writerow(header)
            for row in rows:
                writer.writerow([
                    as_text(getattr(row, 'RowKey', None), ""),
                    as_text(getattr(row, 'ParentRowKey', None), ""),
                    as_text(row.RowType, ""),
                    as_text(row.LevelName, ""),
                    as_text(row.PlanKey, ""),
                    as_text(row.PlanType, ""),
                    as_text(row.TemplateName, ""),
                    as_text(row.ScopeName, ""),
                    as_text(row.ViewName, ""),
                    "True" if bool(row.IncludeOnSheet) else "False",
                    as_text(row.SheetNumberOverride, ""),
                    as_text(row.SheetNameOverride, ""),
                    as_text(row.SheetTemplateName, ""),
                    get_parent_display_name(row)
                ])
    except Exception as ex:
        show_error("Failed to export queue CSV.", _exception_details(ex), "Create Views - CSV Export")
        return

    forms.alert("Queue exported to:\n{}".format(path))


def import_queue_csv(sender=None, args=None):
    commit_queue_grid_edits()
    path = forms.pick_file(file_ext='csv', title='Import View Queue CSV')
    if not path:
        return

    required = set([
        "RowType", "Level", "PlanKey", "PlanType", "Template", "Scope Box",
        "View Name", "Include On Sheet", "Parent View"
    ])

    rows_raw = []
    try:
        with codecs.open(path, 'r', encoding='utf-8-sig') as fp:
            reader = csv.DictReader(fp)
            field_names = set(reader.fieldnames or [])
            if not required.issubset(field_names):
                missing = sorted(list(required - field_names), key=natural_sort_key)
                forms.alert("CSV is missing required columns: {}".format(", ".join(missing)))
                return
            for item in reader:
                rows_raw.append(item)
    except Exception as ex:
        show_error("Failed to import queue CSV.", _exception_details(ex), "Create Views - CSV Import")
        return

    if not rows_raw:
        forms.alert("CSV contains no rows.")
        return

    levels_by_name = {}
    for lvl in all_levels:
        levels_by_name[(lvl.Name or "").strip().lower()] = lvl

    imported_rows = []
    warnings = []
    rowkey_to_imported = {}

    for csv_row in rows_raw:
        level_name = (csv_row.get("Level") or "").strip()
        level_obj = levels_by_name.get(level_name.lower())
        if level_obj is None:
            warnings.append("Skipped row for missing level: {}".format(level_name or "<blank>"))
            continue

        plan_key = _normalize_plan_key(csv_row.get("PlanKey"), csv_row.get("PlanType"))
        plan_label = (csv_row.get("PlanType") or "").strip() or _default_plan_label(plan_key)

        row_type = (csv_row.get("RowType") or "Primary").strip().title()
        if row_type not in ("Primary", "Dependent"):
            row_type = "Primary"

        scope_name = (csv_row.get("Scope Box") or "").strip() or "<None>"
        if scope_name not in scope_box_map:
            scope_name = "<None>"

        template_name = (csv_row.get("Template") or "").strip() or "<None>"
        view_name = (csv_row.get("View Name") or "").strip()
        if not view_name:
            view_name = build_row_name(level_obj, plan_label, scope_name)

        row_key = (csv_row.get("Row Key") or "").strip() or make_row_key()
        while row_key.lower() in rowkey_to_imported:
            warnings.append("Duplicate Row Key found in CSV; generated a new key for row: {}".format(view_name))
            row_key = make_row_key()

        parent_row_key = (csv_row.get("Parent Row Key") or "").strip()
        parent_name = (csv_row.get("Parent View") or "").strip()
        row = QueueRow(
            next_row_id(),
            level_obj,
            plan_key,
            plan_label,
            template_name,
            scope_name,
            view_name,
            row_type,
            None,
            parent_name,
            row_key=row_key,
            parent_row_key=parent_row_key
        )
        row.IncludeOnSheet = _parse_bool(csv_row.get("Include On Sheet"))
        row.SheetNumberOverride = (csv_row.get("Sheet No. Override") or csv_row.get("Sheet Override") or "").strip()
        row.SheetNameOverride = (csv_row.get("Sheet Name Override") or "").strip()
        row.SheetTemplateName = (csv_row.get("Sheet Template") or "").strip()
        imported_rows.append(row)
        rowkey_to_imported[row_key.lower()] = row

    if not imported_rows:
        forms.alert("No valid queue rows were found in CSV.")
        return

    primary_by_name = {}
    for row in imported_rows:
        if row.RowType != "Primary":
            continue
        key = (row.ViewName or "").strip().lower()
        if key and key not in primary_by_name:
            primary_by_name[key] = row

    for row in imported_rows:
        if row.RowType != "Dependent":
            continue
        parent_row = None

        key = (row.ParentRowKey or "").strip().lower()
        if key:
            parent_row = rowkey_to_imported.get(key)

        if parent_row is None:
            key = (row.ParentName or "").strip().lower()
            parent_row = primary_by_name.get(key)

        if parent_row is None:
            warnings.append("Dependent row missing parent in CSV queue: {}".format(row.ViewName))
            continue
        row.ParentRowId = parent_row.RowId
        row.ParentRowKey = parent_row.RowKey
        row.ParentName = parent_row.ViewName

    batch_preview_update_active[0] = True
    try:
        queue_rows.Clear()
        for row in imported_rows:
            row.ViewName = unique_queue_name(row.ViewName, row.RowId)
            queue_rows.Add(row)

        for row in imported_rows:
            if row.RowType != "Dependent":
                continue
            parent_row = get_row_by_id(row.ParentRowId)
            if parent_row is not None:
                row.ParentName = parent_row.ViewName
    finally:
        batch_preview_update_active[0] = False

    schedule_queue_preview_refresh()

    if warnings:
        forms.alert("Queue imported with warnings:\n- {}".format("\n- ".join(warnings)))
    else:
        forms.alert("Queue imported from:\n{}".format(path))


def on_sort_changed(sender, args):
    rebuild_level_checkboxes()


def on_filter_changed(sender, args):
    rebuild_level_checkboxes()


def on_level_select_all(sender, args):
    for cb in level_checkboxes:
        cb.IsChecked = True
        level_obj = cb.Tag
        level_states[level_obj.Id.IntegerValue] = True


def on_level_select_none(sender, args):
    for cb in level_checkboxes:
        cb.IsChecked = False
        level_obj = cb.Tag
        level_states[level_obj.Id.IntegerValue] = False


def on_grid_changed(sender=None, args=None):
    for row in queue_rows:
        current_name = (row.SheetNameOverride or "").strip()
        if current_name and current_name != (row.SheetNamePatternApplied or "").strip():
            row.SheetNamePatternApplied = ""

    if sender in (window.sheetStartBox, window.sheetIncrementBox):
        reset_sheet_number_counter_state()
    schedule_queue_preview_refresh()


def _get_queue_row_from_toggle_event(args):
    current = getattr(args, 'OriginalSource', None)
    while current is not None:
        row = getattr(current, 'DataContext', None)
        if row is not None and getattr(row, 'RowId', None) is not None:
            return row
        try:
            current = VisualTreeHelper.GetParent(current)
        except:
            current = None
    return None


def on_grid_checkbox_toggled(sender, args):
    if suppress_checkbox_events[0]:
        return

    row = _get_queue_row_from_toggle_event(args)
    if row is not None:
        if bool(getattr(row, 'IncludeOnSheet', False)):
            row.SheetTemplateName = selected_text(window.templateSheetCombo, "<None>")
            if not (row.SheetNumberOverride or "").strip() and not (row.SheetNumberAssigned or "").strip():
                assigned_no, _error = assign_next_sheet_number()
                if assigned_no:
                    row.SheetNumberAssigned = assigned_no
                    row.SheetNumberPreview = assigned_no
        else:
            clear_row_sheet_number_assignment(row)
            row.SheetTemplateName = ""

    schedule_queue_preview_refresh()


def on_grid_sorted(sender, args):
    # Keep numbering synced when user sorts by a column.
    schedule_queue_preview_refresh()


def on_combo_text_changed(sender, args):
    combo = None
    for field_name, history_key, _default_value, current_key in TEXT_HISTORY_FIELDS:
        field_combo = getattr(window, field_name)
        if sender == field_combo:
            combo = field_combo
            break
        try:
            if sender == field_combo.EditableTextBox:
                combo = field_combo
                break
        except:
            pass

    if combo is None:
        return

    for field_name, history_key, _default_value, current_key in TEXT_HISTORY_FIELDS:
        if combo == getattr(window, field_name):
            save_combo_current_text(combo, current_key)
            if field_name == "namePatternBox":
                cfg_set(CFG_NAME_PATTERN_KEY, as_text(getattr(combo, "Text", None), "").strip() or DEFAULT_NAME_PATTERN)
                try:
                    script.save_config()
                except:
                    pass
                schedule_queue_preview_refresh()
            elif field_name == "sheetNamePatternBox":
                cfg_set(CFG_SHEET_NAME_PATTERN_KEY, as_text(getattr(combo, "Text", None), "").strip() or DEFAULT_SHEET_NAME_PATTERN)
                try:
                    script.save_config()
                except:
                    pass
                schedule_queue_preview_refresh()
            elif field_name == "phaseAbbrevBox":
                schedule_queue_preview_refresh()
            break


def on_settings_expander_toggled(sender=None, args=None):
    update_dynamic_layout()
    try:
        window.Dispatcher.BeginInvoke(System.Action(update_dynamic_layout))
    except:
        pass


def _is_finite_positive(value):
    try:
        if value is None:
            return False
        numeric = float(value)
    except:
        return False

    if numeric <= 0.0:
        return False

    try:
        if numeric == float("inf") or numeric == float("-inf"):
            return False
    except:
        pass

    return True


def update_dynamic_layout(sender=None, args=None):
    try:
        window.UpdateLayout()
    except:
        pass

    try:
        levels_top = window.levelsGroupBox.TranslatePoint(System.Windows.Point(0, 0), window)
        naming_bottom = window.namingSettingsBox.TranslatePoint(
            System.Windows.Point(0, window.namingSettingsBox.ActualHeight),
            window
        )
    except:
        return

    target_height = naming_bottom.Y - levels_top.Y
    if not _is_finite_positive(target_height):
        return

    if target_height < 140.0:
        target_height = 140.0

    # Hard cap prevents accidental runaway sizes during transient layout states.
    if target_height > 1200.0:
        target_height = 1200.0

    try:
        window.levelsGroupBox.Height = target_height
    except:
        pass


def reset_saved_settings(sender=None, args=None):
    for key in RESETTABLE_CFG_KEYS:
        cfg_delete(key)

    try:
        script.save_config()
    except:
        pass

    window.namePatternBox.Text = DEFAULT_NAME_PATTERN
    window.sheetNamePatternBox.Text = DEFAULT_SHEET_NAME_PATTERN
    window.sheetStartBox.Text = "001"
    window.sheetIncrementBox.Text = "1"
    window.dependentCountBox.Text = "1"
    window.templateSheetCombo.SelectedIndex = 0
    window.copyDetailingBox.IsChecked = True
    window.copyLegendsBox.IsChecked = True
    window.copySchedulesBox.IsChecked = True
    window.removeRevisionsBox.IsChecked = True
    _set_token_delimiters(DEFAULT_TOKEN_DELIMITERS, persist=False)

    cfg_set(CFG_NAME_PATTERN_KEY, DEFAULT_NAME_PATTERN)
    cfg_set(CFG_NAME_PATTERN_CURRENT_KEY, DEFAULT_NAME_PATTERN)
    write_history(CFG_NAME_PATTERN_HISTORY_KEY, [DEFAULT_NAME_PATTERN])
    cfg_set(CFG_SHEET_NAME_PATTERN_KEY, DEFAULT_SHEET_NAME_PATTERN)
    cfg_set(CFG_SHEET_NAME_PATTERN_CURRENT_KEY, DEFAULT_SHEET_NAME_PATTERN)
    write_history(CFG_SHEET_NAME_PATTERN_HISTORY_KEY, [DEFAULT_SHEET_NAME_PATTERN])
    cfg_set(CFG_TOKEN_DELIMITERS_KEY, DEFAULT_TOKEN_DELIMITERS)
    try:
        script.save_config()
    except:
        pass

    for field_name, history_key, default_value, current_key in TEXT_HISTORY_FIELDS:
        try:
            setup_history_combo(getattr(window, field_name), history_key, default_value, current_key)
        except:
            pass

    reset_sheet_number_counter_state()
    schedule_queue_preview_refresh()
    forms.alert("Saved settings have been reset.")


def get_selected_queue_rows():
    rows = []
    seen = set()

    try:
        for item in list(window.queueGrid.SelectedItems):
            if item is None:
                continue
            row_id = getattr(item, 'RowId', None)
            if row_id is None or row_id in seen:
                continue
            seen.add(row_id)
            rows.append(item)
    except:
        pass

    # Some WPF DataGrid states expose multi-selection better through SelectedCells.
    try:
        for cell_info in list(window.queueGrid.SelectedCells):
            item = getattr(cell_info, 'Item', None)
            if item is None:
                continue
            row_id = getattr(item, 'RowId', None)
            if row_id is None or row_id in seen:
                continue
            seen.add(row_id)
            rows.append(item)
    except:
        pass

    if not rows:
        try:
            current_item = window.queueGrid.CurrentItem
            if current_item is not None:
                row_id = getattr(current_item, 'RowId', None)
                if row_id is not None and row_id not in seen:
                    seen.add(row_id)
                    rows.append(current_item)
        except:
            pass

    return rows


def validate_before_create():
    if len(list(queue_rows)) == 0:
        return False, "Add at least one queue row before creating views."

    specs = get_plan_specs(window)
    if not specs:
        return False, "Select at least one plan type."

    selected_phase = get_selected_phase()
    if selected_phase is None:
        return False, "Select a valid phase."

    for row in queue_rows:
        row.ViewName = (row.ViewName or "").strip()
        if not row.ViewName:
            return False, "Each queue row requires a non-empty View Name."

    seen = set()
    for row in queue_rows:
        key = row.ViewName.lower()
        if key in seen:
            return False, "Queue contains duplicate view names: {}".format(row.ViewName)
        seen.add(key)

    parent_ids = set([r.RowId for r in queue_rows])
    for row in queue_rows:
        if row.RowType == "Dependent" and row.ParentRowId not in parent_ids:
            return False, "A dependent row has no parent row in queue: {}".format(row.ViewName)

    includes = [r for r in queue_rows if bool(r.IncludeOnSheet)]
    if includes:
        for row in includes:
            template_sheet_name = (row.SheetTemplateName or "").strip()
            if not template_sheet_name:
                return False, "Select a Sheet Template for included row: {}".format(row.ViewName)

            template_sheet = window.templateSheetMap.get(template_sheet_name)
            if template_sheet is None:
                return False, "Sheet Template was not found for included row: {}".format(row.ViewName)

            titleblock_id = get_sheet_titleblock_type_id(template_sheet)
            if titleblock_id == DB.ElementId.InvalidElementId:
                return False, "Sheet Template must contain a titleblock instance for row: {}".format(row.ViewName)

            template_viewport, _template_view = get_template_plan_reference(template_sheet)
            if template_viewport is None:
                return False, "Sheet Template must contain at least one plan viewport for row: {}".format(row.ViewName)

        _sheet_map, sheet_error = build_sheet_number_map(get_included_rows_in_order())
        if sheet_error:
            return False, sheet_error

    return True, ""


def save_ui_settings():
    try:
        entered_pattern = (window.namePatternBox.Text or "").strip() or DEFAULT_NAME_PATTERN
        entered_sheet_name_pattern = (window.sheetNamePatternBox.Text or "").strip() or DEFAULT_SHEET_NAME_PATTERN
        cfg_set(CFG_NAME_PATTERN_KEY, entered_pattern)
        cfg_set(CFG_SHEET_NAME_PATTERN_KEY, entered_sheet_name_pattern)
        cfg_set(CFG_SHEET_START_KEY, as_text(window.sheetStartBox.Text, "001"))
        cfg_set(CFG_SHEET_INCREMENT_KEY, as_text(window.sheetIncrementBox.Text, "1"))
        cfg_set(CFG_DEPENDENT_COUNT_KEY, as_text(window.dependentCountBox.Text, "1"))
        cfg_set(CFG_TEMPLATE_SHEET_KEY, selected_text(window.templateSheetCombo, "<None>"))
        cfg_set(CFG_COPY_DETAILING_KEY, bool(window.copyDetailingBox.IsChecked))
        cfg_set(CFG_COPY_LEGENDS_KEY, bool(window.copyLegendsBox.IsChecked))
        cfg_set(CFG_COPY_SCHEDULES_KEY, bool(window.copySchedulesBox.IsChecked))
        cfg_set(CFG_REMOVE_REVISIONS_KEY, bool(window.removeRevisionsBox.IsChecked))

        for field_name, history_key, _default_value, current_key in TEXT_HISTORY_FIELDS:
            combo = getattr(window, field_name)
            combo_text = as_text(getattr(combo, "Text", None), "")
            cfg_set(current_key, combo_text)
            update_history(history_key, combo_text)

        script.save_config()
    except:
        pass


def ok_click(sender, args):
    valid, message = validate_before_create()
    if not valid:
        forms.alert(message)
        return

    save_ui_settings()
    window.DialogResult = True
    window.Close()


def cancel_click(sender, args):
    window.DialogResult = False
    window.Close()


def on_help_click(sender=None, args=None):
    """Lazy-load help subsystem only when user requests Help."""
    try:
        from help_viewer import show_help
        show_help(os.path.dirname(__file__), "Create Views")
    except Exception as ex:
        show_error(
            "Could not open help.",
            _exception_details(ex),
            "Create Views - Help"
        )


def on_edit_delimiters_click(sender=None, args=None):
    encoded_current = _encode_delimiter_text(token_delimiter_state.get("value", DEFAULT_TOKEN_DELIMITERS))
    user_input = forms.ask_for_string(
        default=encoded_current,
        prompt="Enter token delimiters. Use escapes: \\s (space), \\t, \\n, \\r, \\\\.",
        title="Create Views - Token Delimiters"
    )
    if user_input is None:
        return

    decoded = _decode_delimiter_text(user_input)
    normalized = _set_token_delimiters(decoded, persist=True)
    forms.alert("Token delimiters updated to: {}".format(_encode_delimiter_text(normalized)))
    schedule_queue_preview_refresh()


window.sortCombo.Items.Clear()
window.sortCombo.Items.Add("Height (Level)")
window.sortCombo.Items.Add("Name")
window.sortCombo.SelectedIndex = 0

window.sortCombo.SelectionChanged += on_sort_changed
window.filterBox.TextChanged += on_filter_changed
window.phaseBox.SelectionChanged += on_grid_changed
window.selectAllLevelsButton.Click += on_level_select_all
window.selectNoneLevelsButton.Click += on_level_select_none
window.addRowsButton.Click += add_rows
window.removeSelectedButton.Click += remove_selected_rows
window.duplicateDependentButton.Click += duplicate_as_dependent
window.includeAllButton.Click += include_all
window.includeNoneButton.Click += include_none
window.exportCsvButton.Click += export_queue_csv
window.importCsvButton.Click += import_queue_csv
window.templateSheetCombo.SelectionChanged += on_grid_changed
window.sheetStartBox.TextChanged += on_grid_changed
window.sheetIncrementBox.TextChanged += on_grid_changed
window.queueGrid.RowEditEnding += on_grid_changed
window.queueGrid.Sorting += on_grid_sorted

for expander_name in ("phaseSettingsExpander", "planTypesExpander", "sheetPlacementExpander"):
    try:
        expander = getattr(window, expander_name)
        expander.Expanded += on_settings_expander_toggled
        expander.Collapsed += on_settings_expander_toggled
    except:
        pass

window.SizeChanged += update_dynamic_layout
window.ContentRendered += update_dynamic_layout

for field_name, history_key, _default_value, _current_key in TEXT_HISTORY_FIELDS:
    combo = getattr(window, field_name)
    combo.AddHandler(TextBox.TextChangedEvent, RoutedEventHandler(on_combo_text_changed))

window.queueGrid.AddHandler(ToggleButton.CheckedEvent, RoutedEventHandler(on_grid_checkbox_toggled))
window.queueGrid.AddHandler(ToggleButton.UncheckedEvent, RoutedEventHandler(on_grid_checkbox_toggled))
window.helpButton.Click += on_help_click
window.delimitersButton.Click += on_edit_delimiters_click
window.resetSettingsButton.Click += reset_saved_settings
window.okButton.Click += ok_click
window.cancelButton.Click += cancel_click


rebuild_level_checkboxes()
schedule_queue_preview_refresh()
update_dynamic_layout()


try:
    result = window.ShowDialog()
    print("CreateViews: dialog closed")
except Exception as ex:
    detail = _exception_details(ex)
    show_error(
        "Failed to show Create Views dialog",
        detail,
        "Create Views - Dialog Failure"
    )
    forms.alert("Create Views dialog failed to open.", exitscript=True)

if not result:
    forms.alert("Cancelled.", exitscript=True)


selected_phase = get_selected_phase()

view_family_map = {
    "floor": get_vft(DB.ViewFamily.FloorPlan),
    "ceiling": get_vft(DB.ViewFamily.CeilingPlan),
    "struct": get_vft(DB.ViewFamily.StructuralPlan)
}

missing_vfts = []
for plan_key in set([r.PlanKey for r in queue_rows]):
    if plan_key not in view_family_map or view_family_map[plan_key] is None:
        if plan_key == "floor":
            missing_vfts.append("Floor Plan")
        elif plan_key == "ceiling":
            missing_vfts.append("Ceiling Plan")
        elif plan_key == "struct":
            missing_vfts.append("Structural Plan")

if missing_vfts:
    forms.alert("Could not find ViewFamilyType for: {}".format(", ".join(sorted(list(set(missing_vfts))))), exitscript=True)


existing_views = DB.FilteredElementCollector(doc)\
    .OfClass(DB.ViewPlan)\
    .WhereElementIsNotElementType()\
    .ToElements()
existing_names = set([v.Name.lower() for v in existing_views])

queue_name_map = {}
for row in queue_rows:
    queue_name_map[row.RowId] = row.ViewName

created_primary = []
created_dependent = []
created_sheets = []
created_sheet_objs = []
created_sheet_sources = []
placed_views = []
warnings = []
sheet_clash_mode_line = ""

row_to_view = {}
name_clash_policy = {"action": None, "repeat_all": False}

phase_param_id = DB.BuiltInParameter.VIEW_PHASE
scope_param_id = DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP


def apply_scope(view_obj, scope_name):
    if not view_obj:
        return
    scope_obj = scope_box_map.get(scope_name)
    if scope_obj:
        param = view_obj.get_Parameter(scope_param_id)
        if param:
            param.Set(scope_obj.Id)


try:
    with revit.Transaction("Create Primary Views"):
        for row in queue_rows:
            if row.RowType != "Primary":
                continue

            view_name = (row.ViewName or "").strip()
            if not view_name:
                warnings.append("Skipped empty name row for level '{}'".format(row.LevelName))
                continue

            if view_name.lower() in existing_names:
                action = resolve_name_clash(view_name, "primary", name_clash_policy)
                if action == "skip":
                    warnings.append("Skipped existing view name: {}".format(view_name))
                    continue

                new_name = unique_name_in_existing_set(view_name, existing_names)
                warnings.append("Renamed on clash: {} -> {}".format(view_name, new_name))
                view_name = new_name
                row.ViewName = new_name

            vft = view_family_map.get(row.PlanKey)
            if vft is None:
                warnings.append("Skipped row missing ViewFamilyType: {}".format(view_name))
                continue

            view_obj = DB.ViewPlan.Create(doc, vft.Id, row.Level.Id)
            view_obj.Name = view_name

            phase_param = view_obj.get_Parameter(phase_param_id)
            if phase_param:
                phase_param.Set(selected_phase.Id)

            template_obj = resolve_template(row.PlanKey, row.TemplateName)
            if template_obj:
                view_obj.ViewTemplateId = template_obj.Id

            apply_scope(view_obj, row.ScopeName)

            row_to_view[row.RowId] = view_obj
            existing_names.add(view_name.lower())
            created_primary.append(view_name)

    with revit.Transaction("Create Dependent Views"):
        for row in queue_rows:
            if row.RowType != "Dependent":
                continue

            parent_view = row_to_view.get(row.ParentRowId)
            if parent_view is None:
                warnings.append("Skipped dependent '{}' because parent was not created.".format(row.ViewName))
                continue

            view_name = (row.ViewName or "").strip()
            if not view_name:
                warnings.append("Skipped dependent with empty name (parent: {}).".format(row.ParentName))
                continue

            if view_name.lower() in existing_names:
                action = resolve_name_clash(view_name, "dependent", name_clash_policy)
                if action == "skip":
                    warnings.append("Skipped existing dependent name: {}".format(view_name))
                    continue

                new_name = unique_name_in_existing_set(view_name, existing_names)
                warnings.append("Renamed on clash: {} -> {}".format(view_name, new_name))
                view_name = new_name
                row.ViewName = new_name

            new_id = parent_view.Duplicate(DB.ViewDuplicateOption.AsDependent)
            dep_view = doc.GetElement(new_id)
            if dep_view is None:
                warnings.append("Failed to duplicate dependent: {}".format(view_name))
                continue

            dep_view.Name = view_name
            apply_scope(dep_view, row.ScopeName)

            template_obj = resolve_template(row.PlanKey, row.TemplateName)
            if template_obj:
                try:
                    dep_view.ViewTemplateId = template_obj.Id
                except:
                    pass

            row_to_view[row.RowId] = dep_view
            existing_names.add(view_name.lower())
            created_dependent.append(view_name)

    include_rows = get_included_rows_in_order()
    if include_rows:
        copy_detailing = bool(window.copyDetailingBox.IsChecked)
        copy_legends = bool(window.copyLegendsBox.IsChecked)
        copy_schedules = bool(window.copySchedulesBox.IsChecked)
        remove_revisions = bool(window.removeRevisionsBox.IsChecked)

        sheet_number_map, counter_error = build_sheet_number_map(include_rows, warnings)
        if sheet_number_map is None:
            raise Exception(counter_error)

        sheet_clash_mode_line = as_text(sheet_number_clash_mode_state.get("detail"), "")

        if copy_detailing:
            warnings.append("Copy detailing is not implemented in this version; checkbox currently acts as a placeholder.")

        with revit.Transaction("Create Sheets and Place Views"):
            for row in include_rows:
                template_sheet_name = (row.SheetTemplateName or "").strip()
                template_sheet = window.templateSheetMap.get(template_sheet_name)
                if template_sheet is None:
                    warnings.append("Skipped sheet row with missing Sheet Template: {}".format(row.ViewName))
                    continue

                titleblock_id = get_sheet_titleblock_type_id(template_sheet)
                if titleblock_id == DB.ElementId.InvalidElementId:
                    warnings.append("Skipped sheet row with invalid Sheet Template titleblock: {}".format(row.ViewName))
                    continue

                template_ref_viewport, template_ref_view = get_template_plan_reference(template_sheet)
                if template_ref_viewport is None or template_ref_view is None:
                    warnings.append("Skipped sheet row with invalid Sheet Template viewport: {}".format(row.ViewName))
                    continue

                template_legends = get_template_legend_viewports(template_sheet)
                template_schedules = get_template_schedule_instances(template_sheet)

                template_sheet_collection_id = DB.ElementId.InvalidElementId
                try:
                    template_sheet_collection_id = getattr(template_sheet, 'SheetCollectionId', DB.ElementId.InvalidElementId)
                except:
                    template_sheet_collection_id = DB.ElementId.InvalidElementId

                template_additional_revision_ids = set()
                try:
                    for rev_id in template_sheet.GetAdditionalRevisionIds():
                        template_additional_revision_ids.add(rev_id.IntegerValue)
                except:
                    pass

                view_obj = row_to_view.get(row.RowId)
                if view_obj is None:
                    warnings.append("Skipped sheet row without created view: {}".format(row.ViewName))
                    continue

                sheet_no = sheet_number_map.get(row.RowId)
                if not sheet_no:
                    warnings.append("Skipped row with invalid sheet number: {}".format(row.ViewName))
                    continue

                sheet = DB.ViewSheet.Create(doc, titleblock_id)
                sheet.SheetNumber = sheet_no

                desired_sheet_name = (row.SheetNameOverride or "").strip() or row.ViewName
                try:
                    sheet.Name = desired_sheet_name
                except:
                    pass

                copy_template_sheet_parameters(template_sheet, sheet, warnings)

                created_sheets.append("{} - {}".format(sheet_no, desired_sheet_name))
                created_sheet_objs.append(sheet)
                created_sheet_sources.append((sheet, template_sheet_collection_id))

                if DB.Viewport.CanAddViewToSheet(doc, sheet.Id, view_obj.Id):
                    new_viewport = DB.Viewport.Create(doc, sheet.Id, view_obj.Id, DB.XYZ(0, 0, 0))

                    apply_template_viewport_settings(template_ref_viewport, new_viewport)

                    aligned = align_viewport_to_template_center(
                        template_ref_view,
                        template_ref_viewport,
                        view_obj,
                        new_viewport
                    )

                    if not aligned:
                        try:
                            new_viewport.SetBoxCenter(template_ref_viewport.GetBoxCenter())
                            warnings.append("Used viewport-box fallback alignment for '{}' on sheet {}.".format(view_obj.Name, sheet_no))
                        except:
                            warnings.append("Could not align '{}' to template center on sheet {}.".format(view_obj.Name, sheet_no))

                    if copy_legends:
                        for template_legend_viewport, legend_view in template_legends:
                            try:
                                if not DB.Viewport.CanAddViewToSheet(doc, sheet.Id, legend_view.Id):
                                    continue

                                legend_origin = template_legend_viewport.GetBoxCenter()
                                new_legend_viewport = DB.Viewport.Create(doc, sheet.Id, legend_view.Id, legend_origin)

                                try:
                                    template_legend_type_id = template_legend_viewport.GetTypeId()
                                    if template_legend_type_id != new_legend_viewport.GetTypeId():
                                        new_legend_viewport.ChangeTypeId(template_legend_type_id)
                                except:
                                    pass
                            except:
                                warnings.append("Could not copy a legend to sheet {}.".format(sheet_no))

                    if copy_schedules:
                        for template_schedule in template_schedules:
                            try:
                                schedule_view_id = template_schedule.ScheduleId
                                schedule_point = template_schedule.Point
                                DB.ScheduleSheetInstance.Create(doc, sheet.Id, schedule_view_id, schedule_point)
                            except:
                                warnings.append("Could not copy a schedule to sheet {}.".format(sheet_no))

                    if remove_revisions:
                        remove_template_inherited_revisions(sheet, template_additional_revision_ids)

                    placed_views.append("{} -> {}".format(view_obj.Name, sheet_no))
                else:
                    warnings.append("Could not place '{}' on sheet {}.".format(view_obj.Name, sheet_no))

        # Some project states appear to require a post-creation commit before SheetCollection assignment persists.
        if created_sheet_sources:
            with revit.Transaction("Finalize Sheet Collection Assignment"):
                for sheet, source_collection_id in created_sheet_sources:
                    try:
                        if source_collection_id and source_collection_id != DB.ElementId.InvalidElementId:
                            sheet.SheetCollectionId = source_collection_id
                    except:
                        try:
                            warnings.append("Could not finalize Sheet Collection for sheet {}.".format(sheet.SheetNumber))
                        except:
                            warnings.append("Could not finalize Sheet Collection for a created sheet.")

                try:
                    doc.Regenerate()
                except:
                    pass

                for sheet, source_collection_id in created_sheet_sources:
                    try:
                        current_id = getattr(sheet, 'SheetCollectionId', DB.ElementId.InvalidElementId)
                        if source_collection_id and source_collection_id != DB.ElementId.InvalidElementId and current_id != source_collection_id:
                            warnings.append("Sheet Collection did not persist after finalize transaction for sheet {}.".format(sheet.SheetNumber))
                    except:
                        warnings.append("Could not verify finalized Sheet Collection for a created sheet.")

except Exception as ex:
    detail = _exception_details(ex)
    show_error(
        "Create Views failed",
        detail,
        "Create Views - Runtime Failure"
    )
    forms.alert("Create Views failed. See traceback dialog for details.", exitscript=True)


msg = []
if created_primary:
    msg.append("Primary views created ({})".format(len(created_primary)))
if created_dependent:
    msg.append("Dependent views created ({})".format(len(created_dependent)))
if created_sheets:
    msg.append("Sheets created ({})".format(len(created_sheets)))
if placed_views:
    msg.append("Views placed on sheets ({})".format(len(placed_views)))
if sheet_clash_mode_line:
    msg.append(sheet_clash_mode_line)

if warnings:
    msg.append("\nWarnings")
    for warning in warnings:
        msg.append("- " + warning)

if not msg:
    msg.append("No changes were made.")

forms.alert("\n".join(msg))
