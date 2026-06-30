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
from System.Windows.Controls import CheckBox
from System.Windows.Controls import DataGridRow
from System.Windows.Controls import TextBox
from System.Windows.Controls import ComboBox
from System.Windows.Controls.Primitives import ButtonBase, ToggleButton
from System.Windows import RoutedEventHandler
from System.Windows import Input
from System.Windows.Media import VisualTreeHelper
from System.Collections.ObjectModel import ObservableCollection
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommandLinkId
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs


doc = revit.doc

DEFAULT_NAME_PATTERN = "{phase_abbrev~upper}-{level~upper}-{plan_type~upper}"
CFG_NAME_PATTERN_KEY = "createviews_name_pattern"
CFG_SHEET_START_KEY = "createviews_sheet_start"
CFG_SHEET_INCREMENT_KEY = "createviews_sheet_increment"
CFG_DEPENDENT_COUNT_KEY = "createviews_dependent_count"
CFG_TITLEBLOCK_NAME_KEY = "createviews_titleblock_name"
HISTORY_LIMIT = 25

NUMERIC_REGEX = re.compile(r'^\d+$')
ALPHA_REGEX = re.compile(r'^[A-Za-z]+$')
MIXED_SUFFIX_NUM_REGEX = re.compile(r'^(.*?)(\d+)$')

TEXT_HISTORY_FIELDS = [
    ("phaseAbbrevBox", "createviews_hist_phase_abbrev", ""),
    ("prefixBox", "createviews_hist_prefix", ""),
    ("suffixBox", "createviews_hist_suffix", ""),
    ("floorNameBox", "createviews_hist_floor_name", "Floor"),
    ("ceilingNameBox", "createviews_hist_ceiling_name", "Ceiling"),
    ("structNameBox", "createviews_hist_struct_name", "Structural")
]


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
        parent_name
    ):
        self._changed_handlers = []
        self.RowId = row_id
        self.Level = level
        self.PlanKey = plan_key
        self.LevelName = level.Name if level else ""
        self.PlanType = plan_type
        self.TemplateName = template_name
        self.ScopeName = scope_name
        self.ViewName = view_name
        self.RowType = row_type
        self.ParentRowId = parent_row_id
        self.ParentName = parent_name
        self.IncludeOnSheet = False
        self.SheetNumberOverride = ""
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
        if name in ("RowId", "Level", "PlanKey", "LevelName", "PlanType", "TemplateName", "ScopeName", "ViewName", "RowType", "ParentRowId", "ParentName", "IncludeOnSheet", "SheetNumberOverride", "SheetNumberPreview"):
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


def as_text(value, default_value=""):
    if value is None:
        return default_value
    try:
        return str(value)
    except:
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


def setup_history_combo(combo, history_key, default_value):
    items = read_history(history_key)
    combo.Items.Clear()
    for item in items:
        combo.Items.Add(item)

    if items:
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
    if case_key == "title":
        return value.title()
    return value


def render_name_pattern(pattern, token_values):
    def _replace(match):
        expr = (match.group(1) or "").strip()
        if not expr:
            return ""

        token_part = expr
        case_part = None
        if "~" in expr:
            token_part, case_part = expr.split("~", 1)

        token_key = token_part.strip().lower()
        token_value = token_values.get(token_key)
        if token_value is None:
            return match.group(0)

        return apply_token_case(token_value, case_part)

    return re.sub(r'\{([^{}]+)\}', _replace, pattern or "")


def build_view_name(pattern, token_values, prefix_text, suffix_text):
    base_name = render_name_pattern(pattern, token_values)
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
    persisted_pattern = cfg_get(CFG_NAME_PATTERN_KEY, DEFAULT_NAME_PATTERN)
    try:
        window.namePatternBox.Text = persisted_pattern or DEFAULT_NAME_PATTERN
    except:
        window.namePatternBox.Text = DEFAULT_NAME_PATTERN

    for field_name, history_key, default_value in TEXT_HISTORY_FIELDS:
        try:
            setup_history_combo(getattr(window, field_name), history_key, default_value)
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
    window.phaseBox.SelectedIndex = len(phases) - 1

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
    struct_templates = [t for t in all_templates if t.ViewType == DB.ViewType.EngineeringPlan]

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
        "struct": struct_templates
    }

    print("CreateViews: load titleblocks")
    titleblock_types = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)\
        .WhereElementIsElementType()\
        .ToElements()
    titleblock_types = sorted(titleblock_types, key=lambda tb: natural_sort_key(_safe_titleblock_display(tb)))

    window.titleblockMap = {}
    window.titleblockCombo.Items.Add("<None>")
    window.titleblockMap["<None>"] = None
    for tb in titleblock_types:
        display = _safe_titleblock_display(tb)
        window.titleblockCombo.Items.Add(display)
        window.titleblockMap[display] = tb

    saved_tb = as_text(cfg_get(CFG_TITLEBLOCK_NAME_KEY, "<None>"), "<None>")
    if saved_tb in window.titleblockMap:
        window.titleblockCombo.SelectedItem = saved_tb
    else:
        window.titleblockCombo.SelectedIndex = 0

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


def rebuild_queue_preview():
    if is_refreshing_preview[0]:
        return

    is_refreshing_preview[0] = True
    suppress_checkbox_events[0] = True
    try:
        for row in queue_rows:
            row.SheetNumberPreview = ""

        ordered_rows = get_display_order_rows()
        include_rows = [r for r in ordered_rows if bool(r.IncludeOnSheet)]
        if not include_rows:
            return

        counter_gen, _error = build_counter_generator(window.sheetStartBox.Text, window.sheetIncrementBox.Text)
        if counter_gen is None:
            for row in include_rows:
                row.SheetNumberPreview = (row.SheetNumberOverride or "").strip()
            return

        idx = 0
        for row in include_rows:
            override_no = (row.SheetNumberOverride or "").strip()
            if override_no:
                row.SheetNumberPreview = override_no
            else:
                row.SheetNumberPreview = counter_gen(idx)
                idx += 1
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


def build_sheet_number_map(include_rows):
    sheet_numbers = {}
    duplicate_numbers = []
    seen = set()

    has_auto = False
    for row in include_rows:
        if not (row.SheetNumberOverride or "").strip():
            has_auto = True
            break

    counter_gen = None
    if has_auto:
        counter_gen, counter_error = build_counter_generator(window.sheetStartBox.Text, window.sheetIncrementBox.Text)
        if counter_gen is None:
            return None, counter_error

    idx = 0
    for row in include_rows:
        override_no = (row.SheetNumberOverride or "").strip()
        if override_no:
            sheet_no = override_no
        else:
            sheet_no = counter_gen(idx)
            idx += 1

        key = sheet_no.lower()
        if key in seen:
            duplicate_numbers.append(sheet_no)
        seen.add(key)
        sheet_numbers[row.RowId] = sheet_no

    if duplicate_numbers:
        unique_duplicates = sorted(list(set(duplicate_numbers)), key=natural_sort_key)
        return None, "Duplicate sheet numbers in queue: {}".format(", ".join(unique_duplicates))

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
                duplicate_primary = False
                for existing in queue_rows:
                    if existing.RowType != "Primary":
                        continue
                    if existing.PlanKey != spec.Key:
                        continue
                    if existing.Level and existing.Level.Id.IntegerValue == lvl.Id.IntegerValue:
                        duplicate_primary = True
                        break

                if duplicate_primary:
                    continue

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
                    source.ViewName
                )
                row.IncludeOnSheet = bool(source.IncludeOnSheet)
                queue_rows.Add(row)
                added += 1
    finally:
        batch_preview_update_active[0] = False

    schedule_queue_preview_refresh()

    if added == 0:
        forms.alert("No dependent rows were added.")


def include_all(sender=None, args=None):
    commit_queue_grid_edits()
    batch_preview_update_active[0] = True
    try:
        for row in queue_rows:
            row.IncludeOnSheet = True
    finally:
        batch_preview_update_active[0] = False

    schedule_queue_preview_refresh()


def include_none(sender=None, args=None):
    commit_queue_grid_edits()
    batch_preview_update_active[0] = True
    try:
        for row in queue_rows:
            row.IncludeOnSheet = False
    finally:
        batch_preview_update_active[0] = False

    schedule_queue_preview_refresh()


def _parse_bool(text):
    value = (text or "").strip().lower()
    return value in ("1", "true", "yes", "y", "on")


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
        "RowType", "Level", "PlanKey", "PlanType", "Template", "Scope Box",
        "View Name", "Include On Sheet", "Sheet Override", "Parent View"
    ]

    try:
        with codecs.open(path, 'w', encoding='utf-8-sig') as fp:
            writer = csv.writer(fp)
            writer.writerow(header)
            for row in rows:
                writer.writerow([
                    as_text(row.RowType, ""),
                    as_text(row.LevelName, ""),
                    as_text(row.PlanKey, ""),
                    as_text(row.PlanType, ""),
                    as_text(row.TemplateName, ""),
                    as_text(row.ScopeName, ""),
                    as_text(row.ViewName, ""),
                    "True" if bool(row.IncludeOnSheet) else "False",
                    as_text(row.SheetNumberOverride, ""),
                    as_text(row.ParentName, "")
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
        "View Name", "Include On Sheet", "Sheet Override", "Parent View"
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
            parent_name
        )
        row.IncludeOnSheet = _parse_bool(csv_row.get("Include On Sheet"))
        row.SheetNumberOverride = (csv_row.get("Sheet Override") or "").strip()
        imported_rows.append(row)

    if not imported_rows:
        forms.alert("No valid queue rows were found in CSV.")
        return

    primary_by_name = {}
    for row in imported_rows:
        if row.RowType != "Primary":
            continue
        key = (row.ViewName or "").strip().lower()
        if key and key not in primary_by_name:
            primary_by_name[key] = row.RowId

    for row in imported_rows:
        if row.RowType != "Dependent":
            continue
        key = (row.ParentName or "").strip().lower()
        parent_id = primary_by_name.get(key)
        if parent_id is None:
            warnings.append("Dependent row missing parent in CSV queue: {}".format(row.ViewName))
            continue
        row.ParentRowId = parent_id

    batch_preview_update_active[0] = True
    try:
        queue_rows.Clear()
        for row in imported_rows:
            row.ViewName = unique_queue_name(row.ViewName, row.RowId)
            queue_rows.Add(row)
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
    schedule_queue_preview_refresh()


def on_grid_checkbox_toggled(sender, args):
    if suppress_checkbox_events[0]:
        return
    schedule_queue_preview_refresh()


def on_grid_sorted(sender, args):
    # Keep numbering synced when user sorts by a column.
    schedule_queue_preview_refresh()


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


def _find_parent_row(dep_obj):
    current = dep_obj
    while current is not None:
        try:
            if isinstance(current, DataGridRow):
                return current
        except:
            pass
        try:
            current = VisualTreeHelper.GetParent(current)
        except:
            return None
    return None


def on_queuegrid_preview_click(sender, args):
    try:
        source = args.OriginalSource
        current = source
        while current is not None:
            if isinstance(current, ToggleButton):
                return
            if isinstance(current, TextBox):
                return
            if isinstance(current, ComboBox):
                return
            if isinstance(current, ButtonBase):
                return
            try:
                current = VisualTreeHelper.GetParent(current)
            except:
                current = None

        if isinstance(source, ToggleButton):
            return

        row = _find_parent_row(args.OriginalSource)
        if row is None:
            return

        mods = Input.Keyboard.Modifiers
        ctrl = bool(mods & Input.ModifierKeys.Control)
        shift = bool(mods & Input.ModifierKeys.Shift)

        if not ctrl and not shift:
            try:
                window.queueGrid.SelectedItems.Clear()
            except:
                pass

        try:
            row.IsSelected = True
            window.queueGrid.CurrentItem = row.Item
        except:
            pass
    except:
        pass


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
        selected_tb_name = selected_text(window.titleblockCombo, "<None>")
        if selected_tb_name == "<None>":
            return False, "Select a titleblock when Include on Sheet is enabled."

        _sheet_map, sheet_error = build_sheet_number_map(get_included_rows_in_order())
        if sheet_error:
            return False, sheet_error

    return True, ""


def save_ui_settings():
    try:
        entered_pattern = (window.namePatternBox.Text or "").strip() or DEFAULT_NAME_PATTERN
        cfg_set(CFG_NAME_PATTERN_KEY, entered_pattern)
        cfg_set(CFG_SHEET_START_KEY, as_text(window.sheetStartBox.Text, "001"))
        cfg_set(CFG_SHEET_INCREMENT_KEY, as_text(window.sheetIncrementBox.Text, "1"))
        cfg_set(CFG_DEPENDENT_COUNT_KEY, as_text(window.dependentCountBox.Text, "1"))
        cfg_set(CFG_TITLEBLOCK_NAME_KEY, selected_text(window.titleblockCombo, "<None>"))

        for field_name, history_key, _default_value in TEXT_HISTORY_FIELDS:
            combo = getattr(window, field_name)
            update_history(history_key, as_text(getattr(combo, "Text", None), ""))

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


window.sortCombo.Items.Clear()
window.sortCombo.Items.Add("Height (Level)")
window.sortCombo.Items.Add("Name")
window.sortCombo.SelectedIndex = 0

window.sortCombo.SelectionChanged += on_sort_changed
window.filterBox.TextChanged += on_filter_changed
window.selectAllLevelsButton.Click += on_level_select_all
window.selectNoneLevelsButton.Click += on_level_select_none
window.addRowsButton.Click += add_rows
window.removeSelectedButton.Click += remove_selected_rows
window.duplicateDependentButton.Click += duplicate_as_dependent
window.includeAllButton.Click += include_all
window.includeNoneButton.Click += include_none
window.exportCsvButton.Click += export_queue_csv
window.importCsvButton.Click += import_queue_csv
window.moveUpButton.Click += move_up
window.moveDownButton.Click += move_down
window.sheetStartBox.TextChanged += on_grid_changed
window.sheetIncrementBox.TextChanged += on_grid_changed
window.queueGrid.RowEditEnding += on_grid_changed
window.queueGrid.Sorting += on_grid_sorted
window.queueGrid.AddHandler(ToggleButton.CheckedEvent, RoutedEventHandler(on_grid_checkbox_toggled))
window.queueGrid.AddHandler(ToggleButton.UncheckedEvent, RoutedEventHandler(on_grid_checkbox_toggled))
window.queueGrid.PreviewMouseLeftButtonDown += on_queuegrid_preview_click
window.okButton.Click += ok_click
window.cancelButton.Click += cancel_click


rebuild_level_checkboxes()
schedule_queue_preview_refresh()


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
placed_views = []
warnings = []

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
        selected_tb_name = selected_text(window.titleblockCombo, "<None>")
        selected_tb = window.titleblockMap.get(selected_tb_name)
        titleblock_id = selected_tb.Id if selected_tb else DB.ElementId.InvalidElementId

        sheet_number_map, counter_error = build_sheet_number_map(include_rows)
        if sheet_number_map is None:
            raise Exception(counter_error)

        with revit.Transaction("Create Sheets and Place Views"):
            for row in include_rows:
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
                try:
                    sheet.Name = row.ViewName
                except:
                    pass

                created_sheets.append("{} - {}".format(sheet_no, row.ViewName))

                if DB.Viewport.CanAddViewToSheet(doc, sheet.Id, view_obj.Id):
                    DB.Viewport.Create(doc, sheet.Id, view_obj.Id, DB.XYZ(0, 0, 0))
                    placed_views.append("{} -> {}".format(view_obj.Name, sheet_no))
                else:
                    warnings.append("Could not place '{}' on sheet {}.".format(view_obj.Name, sheet_no))

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

if warnings:
    msg.append("\nWarnings")
    for warning in warnings:
        msg.append("- " + warning)

if not msg:
    msg.append("No changes were made.")

forms.alert("\n".join(msg))
