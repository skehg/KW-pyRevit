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
    "Entire Project File",
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
    if selection_mode == "Entire Project":
        selection_mode = "Entire Project File"
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


def _scope_summary(selection_mode, source_elements):
    return "{0} | {1} element(s) in scope".format(
        selection_mode, len(source_elements or [])
    )


def _category_record(option):
    label = option["label"]
    name = label.rsplit(" [", 1)[0] if label.endswith("]") else label
    key = option.get("builtin") or str(option["category_id"])
    return {
        "categoryId": option["category_id"],
        "categoryKey": key,
        "name": name,
    }


def _sheet_categories(sheet):
    categories = sheet.get("categories") or []
    if categories:
        return categories
    if sheet.get("categoryId") is not None:
        return [{
            "categoryId": sheet.get("categoryId"),
            "categoryKey": sheet.get("categoryKey"),
            "name": sheet.get("name"),
        }]
    return []


def _elements_for_categories(elements, categories):
    result = []
    for category in categories:
        result.extend(elements_for_category(elements, category["category_id"]))
    return result


def run_wizard(uidoc, doc, workbook=None, source_elements=None, sheet_index=0):
    """Navigate without rebuilding the workbook until every step is accepted."""
    previous = workbook or {}
    launch_selection = (
        resolve_source_elements(uidoc, "Selected Elements")
        if workbook is None and uidoc is not None else []
    )
    launch_category_ids = set(
        item["category_id"] for item in category_options(launch_selection)
    ) if launch_selection else set()
    selection_mode = previous.get("selectionMode") or (
        "Selected Elements" if launch_selection else "Current View"
    )
    if selection_mode == "Entire Project":
        selection_mode = "Entire Project File"
    parameter_mode = previous.get("parameterMode") or PARAMETER_MODES[1]
    old_sheet_list = list(previous.get("sheets") or [])
    old_sheets = {}
    old_layout_by_category = {}
    combined_previous = None
    selected_ids = set()
    for sheet in old_sheet_list:
        if sheet.get("categoryId") is not None:
            try:
                category_id = int(sheet["categoryId"])
                old_sheets[category_id] = sheet
                selected_ids.add(category_id)
            except (TypeError, ValueError):
                pass
        for category in _sheet_categories(sheet):
            try:
                selected_ids.add(int(category.get("categoryId")))
            except (TypeError, ValueError):
                pass
            old_layout_by_category[
                category.get("categoryKey") or category.get("categoryId")
            ] = sheet.get("layout") or {}
        if previous.get("gridLayout") == "combined" or sheet.get("categoryId") is None:
            combined_previous = sheet
    fields = dict(
        (key, list(sheet.get("parameters") or []))
        for key, sheet in old_sheets.items()
    )
    combined_fields = list(
        (combined_previous or {}).get("parameters") or []
    )
    schedule = None
    schedule_layout_defaulted = set()
    options = category_options(source_elements) if source_elements else []
    step = 4 if workbook is not None else 1
    category_index = max(0, min(sheet_index, max(len(old_sheets) - 1, 0)))
    categories = []
    grid_layout = previous.get("gridLayout")
    category_selections = (
        {selection_mode: set(selected_ids)} if workbook is not None else {}
    )
    if grid_layout not in ("combined", "separate"):
        grid_layout = "combined" if combined_previous is not None else "separate"
    if workbook is not None:
        # Keep the workbook's sheet order when returning from the grid.
        by_id = dict((item["category_id"], item) for item in options)
        ordered_ids = []
        for sheet in old_sheet_list:
            for category in _sheet_categories(sheet):
                try:
                    category_id = int(category["categoryId"])
                except (TypeError, ValueError):
                    continue
                if category_id in by_id and category_id not in ordered_ids:
                    ordered_ids.append(category_id)
        categories = [by_id[key] for key in ordered_ids]
        if grid_layout == "combined" and categories:
            category_index = 0
        if not categories:
            step = 2
    while True:
        if step == 1:
            choices, default_item = _step_one_options()
            dialog = ChoiceWizardWindow(
                choices, "Step 1 of 5 - Selection Mode", [selection_mode], back=False,
                context_text="Entire Project File includes all project types. Entire Model "
                "includes placed elements and only their used types. Scope and category "
                "counts are shown before parameter selection."
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
            available_ids = set(item["category_id"] for item in options)
            selected_ids = category_selections.get(selection_mode)
            if selected_ids is None:
                selected_ids = (
                    available_ids if schedule is not None
                    else launch_category_ids & available_ids
                )
            if workbook is None:
                grid_layout = None
            step = 2
        elif step == 2:
            default_layout = grid_layout or (
                "combined" if schedule is not None and len(options) > 1
                else "separate"
            )
            dialog = ChoiceWizardWindow(
                [item["label"] for item in options],
                "Step 2 of 5 - Category Selection",
                [item["label"] for item in options if item["category_id"] in selected_ids],
                multiple=True,
                context_text="{0} | {1} categories found".format(
                    _scope_summary(selection_mode, source_elements), len(options)
                ),
                grid_layout=default_layout,
            )
            dialog.ShowDialog()
            if dialog.action == "cancel":
                return None
            selected_ids = set(item["category_id"] for item in options
                               if item["label"] in dialog.selected)
            category_selections[selection_mode] = set(selected_ids)
            if dialog.action == "back":
                grid_layout = getattr(dialog, "grid_layout", default_layout)
                step = 1
                continue
            categories = [item for item in options if item["category_id"] in selected_ids]
            if not categories:
                forms.alert("Choose at least one category.", title=__title__)
                grid_layout = getattr(dialog, "grid_layout", default_layout)
                continue
            grid_layout = getattr(dialog, "grid_layout", default_layout)
            if grid_layout not in ("combined", "separate"):
                grid_layout = default_layout
            if grid_layout == "combined":
                if not combined_fields:
                    combined_fields = []
                    for category in categories:
                        combined_fields.extend(
                            key for key in fields.get(category["category_id"], [])
                            if key not in combined_fields
                        )
            elif combined_fields:
                for category in categories:
                    if category["category_id"] not in fields:
                        fields[category["category_id"]] = list(combined_fields)
            step = 3
        elif step == 3:
            dialog = ChoiceWizardWindow(
                PARAMETER_MODES, "Step 3 of 5 - Parameter Mode", [parameter_mode],
                context_text="{0} | {1} category sheet(s) selected".format(
                    _scope_summary(selection_mode, source_elements),
                    1 if grid_layout == "combined" else len(categories)
                )
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
            combined = grid_layout == "combined"
            category = categories[category_index] if categories else None
            if combined:
                elements = _elements_for_categories(source_elements, categories)
                usage = build_parameter_usage_map(doc, elements)
                selected_fields = combined_fields
                category_label = "Combined categories"
                step_index = 0
                step_count = 1
            else:
                key = category["category_id"]
                elements = elements_for_category(source_elements, key)
                usage = build_parameter_usage_map(doc, elements)
                selected_fields = fields.get(key, [])
                category_label = category["label"]
                step_index = category_index
                step_count = len(categories)
            if not usage:
                forms.alert("This category has no available parameters.", title=__title__)
                step = 2
                continue
            field_store_key = "combined" if combined else key
            if schedule is not None and field_store_key not in schedule_layout_defaulted:
                if combined or key not in fields:
                    seeded = schedule_parameters(schedule, usage)
                    if combined:
                        combined_fields = seeded
                        selected_fields = combined_fields
                    else:
                        fields[key] = seeded
                        selected_fields = fields[key]
                schedule_layout_defaulted.add(field_store_key)
            dialog = ParameterWizardWindow(
                category_label, usage, parameter_mode, list(selected_fields or []),
                last=combined or category_index == len(categories) - 1,
                context_text="{0} | {1}{2} | {3} element(s) | {4}".format(
                    selection_mode,
                    "Combined grid" if combined else "Category {0} of {1}".format(
                        step_index + 1, step_count
                    ),
                    " ({0} categories)".format(len(categories)) if combined else "",
                    len(elements), parameter_mode
                ),
            )
            dialog.ShowDialog()
            if dialog.action == "cancel":
                return None
            chosen = list(dialog.selected_parameters or [])
            if combined:
                combined_fields = chosen
            else:
                fields[key] = chosen
            if dialog.action == "back":
                if not combined and category_index:
                    category_index -= 1
                else:
                    step = 3
                continue
            if not combined and category_index < len(categories) - 1:
                category_index += 1
                continue
            catalog = ReferenceCatalog(doc)
            sheets = []
            schedule_issues = []
            sheet_groups = (
                [(None, "Combined categories", categories, elements, usage, combined_fields)]
                if combined else
                [
                    (
                        item["category_id"], item["label"], [item],
                        elements_for_category(source_elements, item["category_id"]),
                        None, fields.get(item["category_id"], [])
                    )
                    for item in categories
                ]
            )
            for category_id, label, sheet_categories, elements, known_usage, params in sheet_groups:
                usage_map = known_usage or build_parameter_usage_map(doc, elements)
                sheet = build_sheet(
                    doc, catalog, label, category_id, elements, params,
                    parameter_mode, usage_map,
                    categories=[_category_record(item) for item in sheet_categories],
                )
                if sheet is not None:
                    if combined:
                        prior_layout = (
                            (combined_previous or {}).get("layout")
                            if previous.get("gridLayout") == "combined" else None
                        )
                        sheet["layout"] = prior_layout or {}
                    else:
                        category_key = sheet.get("categoryKey") or _category_record(
                            sheet_categories[0]
                        )["categoryKey"]
                        sheet["layout"] = (
                            old_sheets.get(category_id, {}).get("layout")
                            or old_layout_by_category.get(category_key)
                            or {}
                        )
                    if schedule is not None and not sheet.get("layout"):
                        sheet["layout"], issues = build_schedule_layout(
                            doc, schedule, sheet
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
                "gridLayout": grid_layout,
                "sheets": sheets,
                "_sourceElementIds": [element_id_value(e.Id) for e in source_elements],
            }
            return result, source_elements
