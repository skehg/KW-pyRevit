# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
import System
import re
import traceback
from System.Windows.Controls import CheckBox
doc = revit.doc
DEFAULT_NAME_PATTERN = "{phase_abbrev~upper}-{level~upper}-{plan_type~upper}"
CFG_NAME_PATTERN_KEY = "createviews_name_pattern"
HISTORY_LIMIT = 25

TEXT_HISTORY_FIELDS = [
    ("phaseAbbrevBox", "createviews_hist_phase_abbrev", ""),
    ("prefixBox", "createviews_hist_prefix", ""),
    ("suffixBox", "createviews_hist_suffix", ""),
    ("floorNameBox", "createviews_hist_floor_name", "Floor"),
    ("ceilingNameBox", "createviews_hist_ceiling_name", "Ceiling"),
    ("structNameBox", "createviews_hist_struct_name", "Structural")
]


def show_error(message):
    text = message or "Unknown error."
    try:
        forms.alert(text)
        return
    except:
        pass

    try:
        System.Windows.MessageBox.Show(text, "Create Views Error")
        return
    except:
        pass

    print(text)


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

# ---------------------------------------------------------
# Load WPF UI
# ---------------------------------------------------------
xaml_path = __file__.replace("script.py", "CreateViews.xaml")
try:
    window = forms.WPFWindow(xaml_path)
except Exception:
    show_error("Failed to load CreateViews.xaml:\n\n{}".format(traceback.format_exc()))
    forms.alert("Create Views cannot start due to a UI load error.", exitscript=True)

# Load persisted Name Pattern preference (if available)
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

def select_levels_dialog(doc):
    # Load the XAML
    xaml_path = __file__.replace("script.py", "SelectLevels.xaml")
    try:
        dlg = forms.WPFWindow(xaml_path)
    except Exception:
        show_error("Failed to load SelectLevels.xaml:\n\n{}".format(traceback.format_exc()))
        return None

    # Collect levels once and handle sorting/filtering in the UI callbacks
    all_levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements())

    dlg.level_checkboxes = []
    dlg.level_states = {}

    def _level_id(level):
        return level.Id.IntegerValue

    def sync_states_from_visible():
        for cb in dlg.level_checkboxes:
            level = cb.Tag
            dlg.level_states[_level_id(level)] = bool(cb.IsChecked)

    def get_sorted_filtered_levels():
        levels = list(all_levels)
        sort_option = dlg.sortCombo.SelectedItem
        if sort_option == "Name":
            levels = sorted(levels, key=lambda lvl: natural_sort_key(lvl.Name))
        else:
            levels = sorted(levels, key=lambda lvl: lvl.Elevation)

        filter_text = (dlg.filterBox.Text or "").strip().lower()
        if filter_text:
            levels = [lvl for lvl in levels if filter_text in (lvl.Name or "").lower()]
        return levels

    def rebuild_level_checkboxes():
        sync_states_from_visible()
        dlg.levelsPanel.Children.Clear()
        dlg.level_checkboxes = []

        for lvl in get_sorted_filtered_levels():
            cb = CheckBox()
            cb.Content = lvl.Name
            cb.Tag = lvl

            level_id = _level_id(lvl)
            if dlg.level_states.get(level_id, False):
                cb.IsChecked = True

            dlg.levelsPanel.Children.Add(cb)
            dlg.level_checkboxes.append(cb)

    def sort_changed(sender, args):
        rebuild_level_checkboxes()

    def filter_changed(sender, args):
        rebuild_level_checkboxes()

    dlg.sortCombo.Items.Add("Height (Level)")
    dlg.sortCombo.Items.Add("Name")
    dlg.sortCombo.SelectedIndex = 0
    dlg.sortCombo.SelectionChanged += sort_changed
    dlg.filterBox.TextChanged += filter_changed

    rebuild_level_checkboxes()

    # --- Button events ---
    def ok_click(sender, args):
        dlg.DialogResult = True
        dlg.Close()

    def cancel_click(sender, args):
        dlg.DialogResult = False
        dlg.Close()

    def select_all(sender, args):
        for cb in dlg.level_checkboxes:
            cb.IsChecked = True
            dlg.level_states[_level_id(cb.Tag)] = True

    def select_none(sender, args):
        for cb in dlg.level_checkboxes:
            cb.IsChecked = False
            dlg.level_states[_level_id(cb.Tag)] = False

    dlg.okButton.Click += ok_click
    dlg.cancelButton.Click += cancel_click
    dlg.selectAllButton.Click += select_all
    dlg.selectNoneButton.Click += select_none

    # Show dialog
    result = dlg.ShowDialog()
    if not result:
        return None

    # Return selected levels
    sync_states_from_visible()
    selected = [lvl for lvl in all_levels if dlg.level_states.get(_level_id(lvl), False)]
    return selected

# ---------------------------------------------------------
# Populate Phase List
# ---------------------------------------------------------
phase_collector = DB.FilteredElementCollector(doc).OfClass(DB.Phase)
phases = list(phase_collector)

if not phases:
    forms.alert("No phases found in this document.", exitscript=True)

# Sort by Revit's internal phase sequence number
phases = sorted(
    phases,
    key=lambda p: p.get_Parameter(DB.BuiltInParameter.PHASE_SEQUENCE_NUMBER).AsInteger()
)

# Populate dropdown
phase_map = {}
for p in phases:
    label = p.Name
    phase_map[label] = p
    window.phaseBox.Items.Add(label)

# Select the last phase by default
window.phaseBox.SelectedIndex = len(phases) - 1

# ---------------------------------------------------------
# Populate Scope Box List
# ---------------------------------------------------------
scope_boxes = DB.FilteredElementCollector(doc)\
    .OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)\
    .WhereElementIsNotElementType()\
    .ToElements()
scope_boxes = sorted(scope_boxes, key=lambda sb: natural_sort_key(sb.Name))

window.scopeBoxMap = {}

window.scopeBoxCombo.Items.Add("<None>")
window.scopeBoxMap["<None>"] = None

for sb in scope_boxes:
    name = sb.Name
    window.scopeBoxCombo.Items.Add(name)
    window.scopeBoxMap[name] = sb

window.scopeBoxCombo.SelectedIndex = 0

# ---------------------------------------------------------
# Populate View Template Lists
# ---------------------------------------------------------
templates = DB.FilteredElementCollector(doc)\
    .OfClass(DB.View)\
    .ToElements()

templates = [t for t in templates if t.IsTemplate]

# Group by ViewType
floor_templates = [t for t in templates if t.ViewType == DB.ViewType.FloorPlan]
ceiling_templates = [t for t in templates if t.ViewType == DB.ViewType.CeilingPlan]
struct_templates = [t for t in templates if t.ViewType == DB.ViewType.EngineeringPlan]


def populate_template_combo(combo, items):
    combo.Items.Add("<None>")
    sorted_items = sorted(items, key=lambda t: natural_sort_key(t.Name))
    for t in sorted_items:
        combo.Items.Add(t.Name)
    combo.SelectedIndex = 0

populate_template_combo(window.floorTemplateCombo, floor_templates)
populate_template_combo(window.ceilingTemplateCombo, ceiling_templates)
populate_template_combo(window.structTemplateCombo, struct_templates)

# ---------------------------------------------------------
# Button Events
# ---------------------------------------------------------
def ok_click(sender, args):
    try:
        entered_pattern = (window.namePatternBox.Text or "").strip() or DEFAULT_NAME_PATTERN
        cfg_set(CFG_NAME_PATTERN_KEY, entered_pattern)

        for field_name, history_key, _default_value in TEXT_HISTORY_FIELDS:
            combo = getattr(window, field_name)
            update_history(history_key, as_text(getattr(combo, "Text", None), ""))

        script.save_config()
    except:
        pass

    window.DialogResult = True
    window.Close()

def cancel_click(sender, args):
    window.DialogResult = False
    window.Close()

window.okButton.Click += ok_click
window.cancelButton.Click += cancel_click

# ---------------------------------------------------------
# Show UI
# ---------------------------------------------------------
try:
    result = window.ShowDialog()
except Exception:
    show_error("Failed to show Create Views dialog:\n\n{}".format(traceback.format_exc()))
    forms.alert("Create Views dialog failed to open.", exitscript=True)

if not result:
    forms.alert("Cancelled.", exitscript=True)

def selected_text(combo, default_value=""):
    text = as_text(getattr(combo, "Text", None), "").strip()
    if text:
        return text

    item = combo.SelectedItem
    if item is None:
        return default_value
    return as_text(item, default_value)

selected_phase_name = selected_text(window.phaseBox)
selected_phase = phase_map.get(selected_phase_name)
if selected_phase is None:
    selected_phase = phases[-1]

prefix = selected_text(window.prefixBox, "")
suffix = selected_text(window.suffixBox, "")
name_pattern = (window.namePatternBox.Text or "").strip() or DEFAULT_NAME_PATTERN
raw_phase = selected_text(window.phaseAbbrevBox, "")
phase_abbrev = raw_phase or ""
floor_label = selected_text(window.floorNameBox, "Floor")
ceiling_label = selected_text(window.ceilingNameBox, "Ceiling")
struct_label = selected_text(window.structNameBox, "Structural")
#phase_label = selected_phase.Name

# ---------------------------------------------------------
# Determine which view types to create
# ---------------------------------------------------------
create_floor = window.floorPlanBox.IsChecked
create_ceiling = window.ceilingPlanBox.IsChecked
create_struct = window.structPlanBox.IsChecked

if not (create_floor or create_ceiling or create_struct):
    forms.alert("Select at least one view type.", exitscript=True)

# ---------------------------------------------------------
# Collect selected levels
# ---------------------------------------------------------
selection = revit.get_selection()
levels = []

# If user selected levels manually
for elid in selection.element_ids:
    el = doc.GetElement(elid)
    if isinstance(el, DB.Level):
        levels.append(el)

# If no levels selected → open the level selection dialog
if not levels:
    levels = select_levels_dialog(doc)
    if not levels:
        forms.alert("No levels selected.", exitscript=True)

# ---------------------------------------------------------
# Helper: find ViewFamilyType by ViewFamily
# ---------------------------------------------------------
def get_vft(view_family):
    collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    for vft in collector:
        try:
            if vft.ViewFamily == view_family:
                return vft
        except:
            continue
    return None

floor_vft = get_vft(DB.ViewFamily.FloorPlan) if create_floor else None
ceiling_vft = get_vft(DB.ViewFamily.CeilingPlan) if create_ceiling else None
struct_vft = get_vft(DB.ViewFamily.StructuralPlan) if create_struct else None

missing_vfts = []
if create_floor and not floor_vft:
    missing_vfts.append("Floor Plan")
if create_ceiling and not ceiling_vft:
    missing_vfts.append("Ceiling Plan")
if create_struct and not struct_vft:
    missing_vfts.append("Structural Plan")
if missing_vfts:
    forms.alert("Could not find ViewFamilyType for: {}".format(", ".join(missing_vfts)), exitscript=True)

# ---------------------------------------------------------
# Create Views
# ---------------------------------------------------------
existing_views = DB.FilteredElementCollector(doc)\
    .OfClass(DB.ViewPlan)\
    .WhereElementIsNotElementType()\
    .ToElements()

existing_names = set([v.Name for v in existing_views])

created = []
skipped = []

def safe_name(name):
    illegal = '\\/:{}[]|;<>?'
    return ''.join(c for c in name if c not in illegal)

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

def create_plan_view(level, vft, plan_label, template_name, selected_scope, pattern):
    scope_name = selected_scope.Name if selected_scope else ""
    token_values = {
        "phase": selected_phase.Name,
        "phase_abbrev": phase_abbrev,
        "plan_type": plan_label,
        "scopebox": scope_name,
        "level": level.Name
    }

    name = build_view_name(pattern, token_values, prefix, suffix).strip()
    if not name:
        skipped.append("<empty name for level '{}' plan '{}'>".format(level.Name, plan_label))
        return

    if name in existing_names:
        skipped.append(name)
        return

    v = DB.ViewPlan.Create(doc, vft.Id, level.Id)
    v.Name = name
    v.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).Set(selected_phase.Id)

    if template_name != "<None>":
        template = next((t for t in templates if t.Name == template_name), None)
        if template:
            v.ViewTemplateId = template.Id

    if selected_scope:
        param = v.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
        if param:
            param.Set(selected_scope.Id)

    existing_names.add(name)
    created.append(name)

try:
    with revit.Transaction("Create Views"):
        selected_scope_name = selected_text(window.scopeBoxCombo, "<None>")
        selected_scope = window.scopeBoxMap.get(selected_scope_name)

        for lvl in levels:
            # FLOOR PLAN
            if create_floor and floor_vft:
                create_plan_view(
                    lvl,
                    floor_vft,
                    floor_label,
                    selected_text(window.floorTemplateCombo, "<None>"),
                    selected_scope,
                    name_pattern
                )

            # CEILING PLAN
            if create_ceiling and ceiling_vft:
                create_plan_view(
                    lvl,
                    ceiling_vft,
                    ceiling_label,
                    selected_text(window.ceilingTemplateCombo, "<None>"),
                    selected_scope,
                    name_pattern
                )

            # STRUCTURAL PLAN
            if create_struct and struct_vft:
                create_plan_view(
                    lvl,
                    struct_vft,
                    struct_label,
                    selected_text(window.structTemplateCombo, "<None>"),
                    selected_scope,
                    name_pattern
                )
except Exception:
    forms.alert("Create Views failed:\n\n{}".format(traceback.format_exc()), exitscript=True)
# ---------------------------------------------------------
# Report
# ---------------------------------------------------------
msg = []

if created:
    msg.append("Created:")
    for v in created:
        msg.append("  • " + v)

if skipped:
    msg.append("\nSkipped (already existed):")
    for v in skipped:
        msg.append("  • " + v)

forms.alert("\n".join(msg))