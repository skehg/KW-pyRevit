# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms
import System
import re
from System.Windows.Controls import CheckBox
doc = revit.doc


def natural_sort_key(value):
    text = (value or "").lower()
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', text)]

# ---------------------------------------------------------
# Load WPF UI
# ---------------------------------------------------------
xaml_path = __file__.replace("script.py", "CreateViews.xaml")
window = forms.WPFWindow(xaml_path)

def select_levels_dialog(doc):
    # Load the XAML
    xaml_path = __file__.replace("script.py", "SelectLevels.xaml")
    dlg = forms.WPFWindow(xaml_path)

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
result = window.ShowDialog()
if not result:
    forms.alert("Cancelled.", exitscript=True)

selected_phase_name = window.phaseBox.SelectedItem
selected_phase = phase_map[selected_phase_name]

prefix = window.prefixBox.Text or ""
suffix = window.suffixBox.Text or ""
raw_phase = window.phaseAbbrevBox.Text
phase_abbrev = raw_phase + "-" if raw_phase else ""#selected_phase.Name
floor_label = window.floorNameBox.Text or "Floor"
ceiling_label = window.ceilingNameBox.Text or "Ceiling"
struct_label = window.structNameBox.Text or "Structural"
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

with revit.Transaction("Create Views"):
    for lvl in levels:
        level_name = lvl.Name
        selected_scope = window.scopeBoxMap[window.scopeBoxCombo.SelectedItem]

        # FLOOR PLAN
        if create_floor and floor_vft:
            name = safe_name("{}{}{}-{}{}".format(prefix, phase_abbrev, level_name, floor_label, suffix))
            template_name = window.floorTemplateCombo.SelectedItem  # or ceiling/struct
            if name not in existing_names:
                v = DB.ViewPlan.Create(doc, floor_vft.Id, lvl.Id)
                v.Name = name
                v.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).Set(selected_phase.Id)
                created.append(name)
            else:
                skipped.append(name)
            if template_name != "<None>":
                template = next((t for t in templates if t.Name == template_name), None)
                if template:
                    v.ViewTemplateId = template.Id
            if selected_scope:
                param = v.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
                if param:
                    param.Set(selected_scope.Id)

        # CEILING PLAN
        if create_ceiling and ceiling_vft:
            name = safe_name("{}{}{}-{}{}".format(prefix, phase_abbrev, level_name, ceiling_label, suffix))
            template_name = window.ceilingTemplateCombo.SelectedItem  # or ceiling/struct
            if template_name != "<None>":
                template = next((t for t in templates if t.Name == template_name), None)
                if template:
                    v.ViewTemplateId = template.Id
            if selected_scope:
                param = v.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
                if param:
                    param.Set(selected_scope.Id)
            if name not in existing_names:
                v = DB.ViewPlan.Create(doc, ceiling_vft.Id, lvl.Id)
                v.Name = name
                v.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).Set(selected_phase.Id)
                created.append(name)
            else:
                skipped.append(name)

        # STRUCTURAL PLAN
        if create_struct and struct_vft:
            name = safe_name("{}{}{}-{}{}".format(prefix, phase_abbrev, level_name, struct_label, suffix))
            template_name = window.structTemplateCombo.SelectedItem  # or ceiling/struct
            if template_name != "<None>":
                template = next((t for t in templates if t.Name == template_name), None)
                if template:
                    v.ViewTemplateId = template.Id
            if selected_scope:
                param = v.get_Parameter(DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP)
                if param:
                    param.Set(selected_scope.Id)
            if name not in existing_names:
                v = DB.ViewPlan.Create(doc, struct_vft.Id, lvl.Id)
                v.Name = name
                v.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).Set(selected_phase.Id)
                created.append(name)
            else:
                skipped.append(name)        
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