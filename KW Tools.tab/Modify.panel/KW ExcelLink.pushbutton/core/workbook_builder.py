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


def _category_records(elements):
    records = {}
    for element in elements or []:
        category = getattr(element, "Category", None)
        if category is None:
            continue
        category_id = element_id_value(category.Id)
        if category_id in records:
            continue
        key = category_key(category)
        records[category_id] = {
            "categoryId": category_id,
            "categoryKey": key or str(category_id),
            "name": category.Name,
        }
    return sorted(records.values(), key=lambda item: (item["name"].lower(), item["categoryId"]))


def _combined_category_key(categories):
    keys = sorted(
        item.get("categoryKey") or str(item.get("categoryId"))
        for item in categories
    )
    return "combined:" + "|".join(keys)


def build_sheet(doc, catalog, label, category_id, elements, parameters,
                parameter_mode, usage_map, categories=None):
    rows = extract_rows(
        doc, elements, parameter_mode, parameters, catalog, usage_map=usage_map
    )
    if not rows:
        return None
    columns = build_columns(parameters, usage_map, parameter_mode)
    categories = list(categories) if categories is not None else _category_records(elements)
    combined = category_id is None
    if combined:
        for column in columns:
            if column.get("field") == "Category":
                column["visible"] = True
    return {
        "name": label,
        "categoryId": category_id,
        "categoryKey": (
            _combined_category_key(categories) if combined else
            categories[0]["categoryKey"] if categories else None
        ),
        "sheetKey": (
            _combined_category_key(categories) if combined else
            categories[0]["categoryKey"] if categories else None
        ),
        "categories": categories,
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
    grid_layout = preset.get("gridLayout") or "separate"
    for entry in preset.get("sheets") or []:
        requested_categories = entry.get("categories") or []
        if not requested_categories and entry.get("categoryId") is not None:
            requested_categories = [{
                "categoryId": entry.get("categoryId"),
                "categoryKey": entry.get("categoryKey"),
                "name": entry.get("categoryName"),
            }]
        matched_options = []
        for requested in requested_categories:
            option = match_category(requested, options)
            if option is not None:
                matched_options.append(option)
            else:
                missing_label = requested.get("name") or requested.get("categoryKey")
                issues.append({
                    "sheet": entry.get("categoryName") or missing_label,
                    "message": "No elements of category '{0}' in '{1}'.".format(
                        missing_label, selection_mode
                    ),
                })
        if requested_categories and not matched_options:
            continue
        if not requested_categories:
            # Earlier presets stored one category per sheet.
            option = match_category(entry, options)
            if option is None:
                issues.append({
                    "sheet": entry.get("categoryName") or entry.get("categoryKey"),
                    "message": "No elements of this category in '{0}'; sheet skipped.".format(
                        selection_mode
                    ),
                })
                continue
            matched_options = [option]
        category_ids = set(item["category_id"] for item in matched_options)
        category_items = [
            item for item in options if item["category_id"] in category_ids
        ]
        categories = [
            {
                "categoryId": item["category_id"],
                "categoryKey": item.get("builtin") or str(item["category_id"]),
                "name": item["label"].rsplit(" [", 1)[0],
            }
            for item in category_items
        ]
        elements = [
            element for element in source_elements
            if getattr(getattr(element, "Category", None), "Id", None) is not None
            and element_id_value(element.Category.Id) in category_ids
        ]
        label = (
            entry.get("categoryName") or entry.get("name") or
            ("Combined categories" if len(categories) > 1 else category_items[0]["label"])
        )
        usage_map = build_parameter_usage_map(doc, elements)
        wanted = list(entry.get("parameters") or entry.get("parameterKeys") or [])
        parameters = [key for key in wanted if key in usage_map]
        for key in wanted:
            if key not in usage_map:
                issues.append({
                    "sheet": label,
                    "column": key,
                    "message": "Parameter not found on these elements; column skipped.",
                })
        if not parameters:
            issues.append({
                "sheet": label,
                "message": "None of the preset parameters exist here; sheet skipped.",
            })
            continue
        sheet = build_sheet(
            doc, catalog, label,
            category_items[0]["category_id"]
            if grid_layout != "combined" and category_items else None,
            elements, parameters, parameter_mode, usage_map,
            categories=categories,
        )
        if sheet is None:
            issues.append({"sheet": label, "message": "No rows; sheet skipped."})
            continue
        sheet["layout"] = entry.get("layout") or {}
        sheet["sheetKey"] = entry.get("sheetKey") or sheet.get("sheetKey")
        sheets.append(sheet)

    if not sheets:
        return None, issues
    workbook = {
        "selectionMode": selection_mode,
        "parameterMode": parameter_mode,
        "gridLayout": grid_layout,
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
    grid_layout = plan.get("gridLayout") or "separate"
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
        categories = entry.get("categories") or _category_records(elements)
        requested_ids = set(
            item.get("categoryId") for item in categories
            if item.get("categoryId") is not None
        )
        categories = [
            item for item in _category_records(elements)
            if not requested_ids or item["categoryId"] in requested_ids
        ]
        category_id = entry.get("categoryId")
        if grid_layout == "combined" or len(categories) > 1:
            category_id = None
        elif category_id is None and categories:
            category_id = categories[0]["categoryId"]
        label = entry.get("xlsxName") or (
            "Combined categories" if category_id is None else
            categories[0]["name"] if categories else "Imported sheet"
        )
        usage_map = build_parameter_usage_map(doc, elements)
        requested_usage = entry.get("parameterUsage") or {}
        for key, metadata in requested_usage.items():
            if isinstance(metadata, dict):
                usage_map.setdefault(key, {}).update(metadata)
        parameters = entry.get("parameterKeys") or entry.get("parameters") or []
        sheet = build_sheet(
            doc, catalog, label, category_id, elements, parameters,
            parameter_mode, usage_map, categories=categories,
        )
        if sheet is not None:
            sheet["sheetKey"] = entry.get("sheetKey") or sheet.get("sheetKey")
            sheets.append(sheet)

    if not sheets:
        return None, source_elements, plan["issues"], missing

    workbook = {
        "selectionMode": "Imported XLSX",
        "parameterMode": parameter_mode,
        "gridLayout": grid_layout,
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
