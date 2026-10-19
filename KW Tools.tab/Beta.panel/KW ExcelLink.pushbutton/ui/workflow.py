# -*- coding: utf-8 -*-
__title__ = "KW ExcelLink"
from pyrevit import forms

from core.element_refs import ReferenceCatalog
from core.parameter_map import build_parameter_usage_map
from core.presets import default_preset_name, find_preset, load_preset, preset_label
from core.schedule_defaults import (
    build_schedule_layout,
    read_schedule_defaults,
    schedule_parameters,
)
from core.selection import (
    category_options,
    elements_for_category,
    resolve_source_elements,
)
from core.types import element_id_value
from core.workbook_builder import (
    build_import_workbook,
    build_preset_workbook,
    build_sheet,
)
from ui.import_dialogs import pick_xlsx, report_import_issues
from ui.preset_dialogs import choose_preset, manage_presets, report_preset_issues
from ui.wizard import ChoiceWizardWindow, ParameterWizardWindow


SELECTION_MODES = (
    "Selected Elements",
    "Current View",
    "Entire Model",
)
IMPORT_MODE = "Import edited XLSX..."
LOAD_PRESET = "Load preset..."
MANAGE_PRESETS = "Manage presets..."
DEFAULT_PRESET_PREFIX = "Open default preset: "
PARAMETER_MODES = (
    "Types Mode",
    "Instances Mode",
)


def _run_import(uidoc, doc):
    file_path = pick_xlsx()
    if not file_path:
        return None
    workbook, source_elements, issues, missing = build_import_workbook(doc, file_path)
    report_import_issues(file_path, issues, missing)
    if workbook is None:
        forms.alert(
            "None of the rows in this workbook match elements in the active model.",
            title=__title__,
        )
        return None
    return workbook, source_elements


def _run_preset(uidoc, doc, item, selection_mode=None):
    preset = load_preset(item["path"])
    selection_mode = selection_mode or preset.get("selectionMode")
    if selection_mode not in SELECTION_MODES:
        selection_mode = "Current View"
    dialog = ChoiceWizardWindow(
        SELECTION_MODES, "Selection Mode - {0}".format(item["name"]),
        [selection_mode],
    )
    dialog.ShowDialog()
    if dialog.action != "next":
        return None
    selection_mode = dialog.selected[0]
    source_elements = resolve_source_elements(uidoc, selection_mode)
    if not source_elements:
        forms.alert(
            "Preset '{0}' loads elements from '{1}', but none were found.".format(
                item["name"], selection_mode
            ),
            title=__title__,
        )
        return None
    workbook, issues = build_preset_workbook(
        doc, preset, selection_mode, source_elements
    )
    report_preset_issues(item["name"], issues)
    if workbook is None:
        forms.alert(
            "Nothing in preset '{0}' matches elements in '{1}'. "
            "See the pyRevit output window for details.".format(
                item["name"], selection_mode
            ),
            title=__title__,
        )
        return None
    workbook["presetName"] = item["name"]
    return workbook, source_elements


def _step_one_options():
    options = []
    default_item = find_preset(default_preset_name())
    if default_item is not None:
        options.append(DEFAULT_PRESET_PREFIX + preset_label(default_item))
    options.extend(SELECTION_MODES)
    options.extend((LOAD_PRESET, IMPORT_MODE, MANAGE_PRESETS))
    return options, default_item


def run_wizard(uidoc, doc, workbook=None, source_elements=None, sheet_index=0):
    """Navigate without rebuilding the workbook until every step is accepted."""
    previous = workbook or {}
    selection_mode = previous.get("selectionMode") or "Current View"
    parameter_mode = previous.get("parameterMode") or PARAMETER_MODES[1]
    old_sheets = dict(
        (int(sheet["categoryId"]), sheet) for sheet in previous.get("sheets", [])
    )
    fields = dict((key, list(sheet["parameters"])) for key, sheet in old_sheets.items())
    schedule = None
    schedule_by_category = {}
    selected_ids = set(old_sheets)
    options = category_options(source_elements) if source_elements else []
    step = 4 if workbook is not None else 1
    category_index = max(0, min(sheet_index, len(old_sheets) - 1))
    categories = []
    if workbook is not None:
        # Keep the workbook's sheet order when returning from the grid.
        by_id = dict((item["category_id"], item) for item in options)
        categories = [by_id[int(s["categoryId"])] for s in previous["sheets"]
                      if int(s["categoryId"]) in by_id]
        if not categories:
            step = 2
    while True:
        if step == 1:
            choices, default_item = _step_one_options()
            dialog = ChoiceWizardWindow(
                choices, "Step 1 of 5 - Selection Mode", [selection_mode], back=False
            )
            dialog.ShowDialog()
            if dialog.action == "cancel":
                return None
            choice = dialog.selected[0]
            if choice == MANAGE_PRESETS:
                manage_presets()
                continue
            if choice == IMPORT_MODE:
                result = _run_import(uidoc, doc)
                if result is not None:
                    return result
                continue
            if choice == LOAD_PRESET or choice.startswith(DEFAULT_PRESET_PREFIX):
                item = choose_preset() if choice == LOAD_PRESET else default_item
                result = _run_preset(uidoc, doc, item, selection_mode) if item else None
                if result is not None:
                    return result
                continue
            selection_mode = choice
            source_elements = resolve_source_elements(uidoc, selection_mode)
            schedule = read_schedule_defaults(uidoc, selection_mode)
            options = category_options(source_elements)
            if not options:
                forms.alert("No categorized elements were found for this scope.", title=__title__)
                continue
            step = 2
        elif step == 2:
            dialog = ChoiceWizardWindow(
                [item["label"] for item in options],
                "Step 2 of 5 - Category Selection",
                [item["label"] for item in options if item["category_id"] in selected_ids],
                multiple=True,
            )
            dialog.ShowDialog()
            if dialog.action == "cancel":
                return None
            selected_ids = set(item["category_id"] for item in options
                               if item["label"] in dialog.selected)
            if dialog.action == "back":
                step = 1
                continue
            categories = [item for item in options if item["category_id"] in selected_ids]
            step = 3
        elif step == 3:
            dialog = ChoiceWizardWindow(
                PARAMETER_MODES, "Step 3 of 5 - Parameter Mode", [parameter_mode]
            )
            dialog.ShowDialog()
            if dialog.action == "cancel":
                return None
            if dialog.selected:
                parameter_mode = dialog.selected[0]
            if dialog.action == "back":
                step = 2
                continue
            category_index = 0
            step = 4
        else:
            category = categories[category_index]
            key = category["category_id"]
            elements = elements_for_category(source_elements, key)
            usage = build_parameter_usage_map(doc, elements)
            if not usage:
                forms.alert("This category has no available parameters.", title=__title__)
                step = 2
                continue
            if schedule is not None and key not in fields:
                fields[key] = schedule_parameters(schedule, usage)
                schedule_by_category[key] = schedule
            dialog = ParameterWizardWindow(
                category["label"], usage, parameter_mode, fields.get(key),
                last=category_index == len(categories) - 1,
            )
            dialog.ShowDialog()
            if dialog.action == "cancel":
                return None
            fields[key] = list(dialog.selected_parameters)
            if dialog.action == "back":
                if category_index:
                    category_index -= 1
                else:
                    step = 3
                continue
            if category_index < len(categories) - 1:
                category_index += 1
                continue
            catalog = ReferenceCatalog(doc)
            sheets = []
            schedule_issues = []
            for category in categories:
                key = category["category_id"]
                elements = elements_for_category(source_elements, key)
                sheet = build_sheet(
                    doc, catalog, category["label"], key, elements, fields[key],
                    parameter_mode, build_parameter_usage_map(doc, elements),
                )
                if sheet is not None:
                    sheet["layout"] = old_sheets.get(key, {}).get("layout") or {}
                    if key in schedule_by_category and key not in old_sheets:
                        sheet["layout"], issues = build_schedule_layout(
                            doc, schedule_by_category[key], sheet
                        )
                        schedule_issues.extend(issues)
                    sheets.append(sheet)
            if not sheets:
                forms.alert("No category has rows and selected parameters.", title=__title__)
                step = 2
                continue
            if schedule_issues:
                forms.alert(
                    "Some schedule settings could not be transferred:\n\n{0}\n\n"
                    "These settings will not be included in saved presets.".format(
                        "\n".join(sorted(set(schedule_issues)))
                    ),
                    title=__title__,
                )
            result = {
                "selectionMode": selection_mode,
                "parameterMode": parameter_mode,
                "sheets": sheets,
                "_sourceElementIds": [element_id_value(e.Id) for e in source_elements],
            }
            return result, source_elements
