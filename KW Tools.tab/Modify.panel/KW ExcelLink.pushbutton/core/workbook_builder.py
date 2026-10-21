# -*- coding: utf-8 -*-
"""Builds workbook sheets from Revit elements, including from an imported XLSX."""

import os

from core.column_builder import build_columns, project_rows
from core.element_refs import ReferenceCatalog, make_element_id
from core.extract import extract_rows
from core.parameter_map import build_parameter_usage_map
from core.selection import category_key, category_options, elements_for_category
from core.types import MODE_INSTANCES, MODE_TYPES, element_id_value
from core.type_names import attach_type_names


def build_sheet(doc, catalog, label, category_id, elements, parameters,
                parameter_mode, usage_map):
    rows = extract_rows(doc, elements, parameter_mode, parameters, catalog)
    if not rows:
        return None
    columns = build_columns(parameters, usage_map, parameter_mode)
    category = elements[0].Category if elements else None
    return {
        "name": label,
        "categoryId": category_id,
        "categoryKey": category_key(category) if category is not None else None,
        "parameterUsage": usage_map,
        "parameters": list(parameters),
        "columns": columns,
        "rows": project_rows(rows, columns, catalog),
        "typeNames": attach_type_names(doc, rows, catalog),
    }


def _resolve_element(doc, unique_id, element_id):
    element = None
    if unique_id:
        element = doc.GetElement(unique_id)
    if element is None and element_id:
        try:
            element = doc.GetElement(make_element_id(element_id))
        except Exception:
            element = None
    return element


def build_preset_workbook(doc, preset, selection_mode, source_elements):
    """Build a workbook from a saved preset without running the wizard.

    Returns (workbook, issues); workbook is None when nothing matches. Missing
    categories and parameters are reported, not fatal, so a preset made in
    one project still opens in another.
    """
    from core.presets import match_category

    parameter_mode = preset.get("parameterMode")
    if parameter_mode not in (MODE_TYPES, MODE_INSTANCES):
        raise ValueError(
            "The preset does not record a valid parameter mode ({0}).".format(
                parameter_mode
            )
        )
    options = category_options(source_elements)
    catalog = ReferenceCatalog(doc)
    issues = []
    sheets = []
    for entry in preset.get("sheets") or []:
        label = entry.get("categoryName") or entry.get("categoryKey")
        option = match_category(entry, options)
        if option is None:
            issues.append({
                "sheet": label,
                "message": "No elements of this category in '{0}'; sheet skipped.".format(
                    selection_mode
                ),
            })
            continue
        elements = elements_for_category(source_elements, option["category_id"])
        usage_map = build_parameter_usage_map(doc, elements)
        wanted = list(entry.get("parameters") or [])
        parameters = [name for name in wanted if name in usage_map]
        for name in wanted:
            if name not in usage_map:
                issues.append({
                    "sheet": option["label"],
                    "column": name,
                    "message": "Parameter not found on these elements; column skipped.",
                })
        if not parameters:
            issues.append({
                "sheet": option["label"],
                "message": "None of the preset parameters exist here; sheet skipped.",
            })
            continue
        sheet = build_sheet(
            doc, catalog, option["label"], option["category_id"], elements,
            parameters, parameter_mode, usage_map,
        )
        if sheet is None:
            issues.append({"sheet": option["label"], "message": "No rows; sheet skipped."})
            continue
        sheet["layout"] = entry.get("layout") or {}
        sheets.append(sheet)

    if not sheets:
        return None, issues
    workbook = {
        "selectionMode": selection_mode,
        "parameterMode": parameter_mode,
        "presetName": preset.get("name"),
        "sheets": sheets,
        "_sourceElementIds": [
            element_id_value(element.Id) for element in source_elements
        ],
    }
    return workbook, issues


def build_import_workbook(doc, file_path):
    """Rebuild the grid described by an ExcelLink XLSX from current Revit values.

    Returns (workbook, source_elements, issues, missing_count). The workbook
    carries 'importUpdates' (cells whose XLSX value differs from Revit) and
    'importSummary'; workbook is None when nothing in the file matches.
    """
    from core.xlsx_import import diff_xlsx, read_import_plan

    plan = read_import_plan(file_path)
    parameter_mode = plan["parameterMode"]
    if parameter_mode not in (MODE_TYPES, MODE_INSTANCES):
        raise ValueError(
            "The workbook does not record a valid parameter mode ({0}).".format(
                parameter_mode
            )
        )

    catalog = ReferenceCatalog(doc)
    source_elements = []
    seen_ids = set()
    missing = 0
    sheets = []
    for entry in plan["sheets"]:
        elements = []
        for unique_id, element_id in zip(entry["uniqueIds"], entry["elementIds"]):
            element = _resolve_element(doc, unique_id, element_id)
            if element is None:
                missing += 1
                continue
            elements.append(element)
            key = element_id_value(element.Id)
            if key not in seen_ids:
                seen_ids.add(key)
                source_elements.append(element)
        if not elements:
            continue
        category_id = entry["categoryId"]
        label = dict(
            (item["category_id"], item["label"])
            for item in category_options(elements)
        ).get(category_id, entry["xlsxName"])
        usage_map = build_parameter_usage_map(doc, elements)
        sheet = build_sheet(
            doc, catalog, label, category_id, elements, entry["parameters"],
            parameter_mode, usage_map,
        )
        if sheet is not None:
            sheets.append(sheet)

    if not sheets:
        return None, source_elements, plan["issues"], missing

    workbook = {
        "selectionMode": "Imported XLSX",
        "parameterMode": parameter_mode,
        "importFile": os.path.basename(file_path),
        "sheets": sheets,
        "_sourceElementIds": [
            element_id_value(element.Id) for element in source_elements
        ],
    }
    diff = diff_xlsx(workbook, file_path)
    workbook["importUpdates"] = diff["updates"]
    workbook["importSummary"] = diff["summary"]
    return workbook, source_elements, plan["issues"] + diff["issues"], missing
